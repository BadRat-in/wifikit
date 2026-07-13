"""
capture.py — SD-free WiFi capture by demuxing Marauder's ``-serial`` pcap stream.

Why this exists
--------------
A bare ESP32-WROOM-32 DevKit has no microSD card, so stock ESP32 Marauder cannot
*save* a ``.pcap`` to disk for cracking. It can, however, **stream the pcap bytes
over the USB serial link**: when a capture command is run with the ``-serial``
flag (and the ``SavePCAP`` setting is enabled), the firmware writes the exact
pcap byte buffer out UART0, framed by the ASCII markers ``[BUF/BEGIN]`` and
``[BUF/CLOSE]`` (see ``Buffer.cpp`` / ``CommandLine.cpp`` in the firmware). Since
the board is already tethered to the Mac over USB, we let it *forward* frames
instead of *storing* them — one cable, no extra hardware, and the whole
scan → capture → crack loop stays inside ``wifikit``.

This module is the host side of that scheme:

* :class:`SavePcapStreamParser` demultiplexes the marker-framed pcap blobs out of
  the raw serial byte stream (tolerating interleaved console text and blobs split
  across reads). It is pure and unit-testable — no hardware needed.
* :func:`run_capture` drives an :class:`~wifikit.session.Esp32Session` end to end:
  enable ``SavePCAP``, start the ``-serial`` sniff, collect the streamed pcap, and
  write it to disk.
* :func:`convert_hc22000` optionally turns the ``.pcap`` into a hashcat ``22000``
  file via ``hcxpcapngtool`` when that tool is installed.

Design note — pluggable capture source
--------------------------------------
The parser and :func:`run_capture` only assume "a stream of pcap bytes framed by
begin/close markers arrives over serial." That keeps the host side firmware
agnostic: a future custom sniffer firmware (C++ or Rust) can expose the same
serial contract and reuse this code unchanged.

**Authorized-use only.** Capture handshakes/PMKIDs solely on networks you own or
are permitted to test.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

from .session import Esp32Session, find_port

# Marker bytes the firmware wraps around each flushed pcap byte buffer.
BUF_BEGIN = b"[BUF/BEGIN]"
BUF_CLOSE = b"[BUF/CLOSE]"

# libpcap global-header magic in the byte orders a stream may arrive in
# (LE/BE, microsecond and nanosecond variants). Used only to sanity-check that
# what we recovered actually looks like a pcap.
PCAP_MAGICS = (
    b"\xa1\xb2\xc3\xd4",  # microsecond, big-endian value / BE file
    b"\xd4\xc3\xb2\xa1",  # microsecond, little-endian file (ESP32 writes this)
    b"\xa1\xb2\x3c\x4d",  # nanosecond, BE
    b"\x4d\x3c\xb2\xa1",  # nanosecond, LE
)

# LLC/SNAP header + EtherType 0x888E that prefixes an EAPOL payload inside an
# 802.11 data frame. Presence of this in a captured frame means a *real* EAPOL
# key frame (the crackable part of a handshake/PMKID) — unlike the firmware's
# console banner, which prints "PMKID"/"EAPOL" regardless of what was captured.
EAPOL_LLC_SNAP = b"\xaa\xaa\x03\x00\x00\x00\x88\x8e"

# The one Marauder command wifikit uses to capture crackable frames. Despite the
# name, ``sniffpmkid`` captures both clientless PMKIDs and the EAPOL frames of a
# full 4-way handshake; ``hcxpcapngtool`` extracts whichever is present. So there
# is a single capture command, not a PMKID-vs-handshake choice. ``-serial`` makes
# it stream the pcap over USB. (``sniffpwn`` is a Pwnagotchi beacon sniffer, NOT
# a handshake capturer — do not use it here.)
SNIFF_COMMAND = "sniffpmkid -c {channel} -serial"

# Kept for the CLI's ``--mode`` flag (both map to the same command now).
CAPTURE_MODES = {"pmkid": [SNIFF_COMMAND], "handshake": [SNIFF_COMMAND]}


def looks_like_pcap(data: bytes) -> bool:
    """
    Return True if ``data`` begins with a recognised libpcap magic number.

    Parameters
    ----------
    data : bytes
        Candidate pcap bytes (e.g. the concatenation of streamed blobs).

    Returns
    -------
    bool
        True if the first four bytes match a known pcap magic, else False.
    """
    return len(data) >= 4 and data[:4] in PCAP_MAGICS


def pcap_frame_stats(data: bytes) -> tuple[int, int]:
    """
    Walk a pcap byte stream and count total frames and EAPOL frames.

    Reads the 24-byte global header (honouring its endianness), then iterates the
    16-byte-prefixed packet records. A frame counts as EAPOL if it contains the
    LLC/SNAP + EtherType-0x888E signature (:data:`EAPOL_LLC_SNAP`) — this is the
    *only* trustworthy "did we capture something crackable?" signal, because the
    firmware's console banner prints "PMKID"/"EAPOL" regardless of what actually
    landed in the capture.

    Parameters
    ----------
    data : bytes
        The assembled pcap bytes.

    Returns
    -------
    tuple[int, int]
        ``(frame_count, eapol_frame_count)``; ``(0, 0)`` if not a parseable pcap.
    """
    if not looks_like_pcap(data) or len(data) < 24:
        return (0, 0)
    # First magic byte 0xD4/0x4D ⇒ little-endian file; 0xA1 ⇒ big-endian.
    order = "little" if data[0] in (0xD4, 0x4D) else "big"
    frames = 0
    eapol = 0
    off = 24
    total = len(data)
    while off + 16 <= total:
        incl = int.from_bytes(data[off + 8 : off + 12], order)
        off += 16
        if incl == 0 or off + incl > total:
            break  # truncated final record (stream cut mid-flush) — stop cleanly
        frame = data[off : off + incl]
        off += incl
        frames += 1
        if EAPOL_LLC_SNAP in frame:
            eapol += 1
    return (frames, eapol)


class SavePcapStreamParser:
    """
    Extract ``[BUF/BEGIN]…[BUF/CLOSE]`` pcap blobs from a raw serial byte stream.

    Marauder interleaves human-readable console lines with binary pcap buffers on
    the same UART. This parser buffers incoming bytes and yields the payload of
    each complete begin/close block, correctly handling markers or blobs that are
    split across separate reads. It is thread-safe so it can be fed directly from
    :class:`~wifikit.session.Esp32Session`'s reader thread via ``on_raw``.

    Concatenating the recovered blobs in order reconstructs the pcap byte stream
    the firmware would otherwise have written to its SD card.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._lock = threading.Lock()
        # Completed blob payloads, in arrival order.
        self.blobs: list[bytes] = []

    def feed(self, data: bytes) -> list[bytes]:
        """
        Add raw bytes to the parser and return any newly completed blobs.

        Parameters
        ----------
        data : bytes
            A chunk of raw serial bytes (undecoded).

        Returns
        -------
        list[bytes]
            Payloads of any begin/close blocks that completed with this chunk.
            Also appended to :attr:`blobs`.
        """
        with self._lock:
            self._buf.extend(data)
            new = self._extract()
            self.blobs.extend(new)
            return new

    def _extract(self) -> list[bytes]:
        """Consume complete blocks from the buffer (caller holds the lock)."""
        out: list[bytes] = []
        while True:
            begin = self._buf.find(BUF_BEGIN)
            if begin == -1:
                # No begin marker yet. Drop consumed noise but retain the tail
                # in case a begin marker is split across the next read.
                keep = len(BUF_BEGIN) - 1
                if len(self._buf) > keep:
                    del self._buf[: len(self._buf) - keep]
                return out
            close = self._buf.find(BUF_CLOSE, begin + len(BUF_BEGIN))
            if close == -1:
                # Have a begin but not yet its close: discard leading noise and
                # keep everything from the begin marker for the next read.
                if begin > 0:
                    del self._buf[:begin]
                return out
            out.append(bytes(self._buf[begin + len(BUF_BEGIN) : close]))
            del self._buf[: close + len(BUF_CLOSE)]

    def pcap_bytes(self) -> bytes:
        """Return all recovered blobs concatenated into one pcap byte stream."""
        with self._lock:
            return b"".join(self.blobs)

    def blob_count(self) -> int:
        """Return the number of complete blobs recovered so far."""
        with self._lock:
            return len(self.blobs)


@dataclass
class CaptureResult:
    """
    Outcome of a :func:`run_capture` session.

    Attributes
    ----------
    pcap_path : str | None
        Path to the written ``.pcap``, or ``None`` if no pcap bytes were captured.
    blob_count : int
        Number of ``[BUF/BEGIN]…[BUF/CLOSE]`` blocks received.
    byte_count : int
        Total pcap bytes written.
    valid_pcap : bool
        Whether the recovered bytes start with a recognised pcap magic.
    frame_count : int
        Number of 802.11 frames in the captured pcap.
    eapol_frames : int
        Number of frames containing an EAPOL payload — the trustworthy signal
        that something crackable (handshake/PMKID) was actually captured, parsed
        from the frames themselves rather than the firmware's console banner.
    log_tail : list[str]
        The last few console lines, for a human-readable summary.
    """

    pcap_path: str | None
    blob_count: int
    byte_count: int
    valid_pcap: bool
    frame_count: int
    eapol_frames: int
    log_tail: list[str] = field(default_factory=list)


def _default_out_path() -> str:
    """Build a timestamped default capture path under ``captures/``."""
    # int(time.time()) keeps the name filesystem-safe and roughly sortable.
    return os.path.join("captures", f"capture-{int(time.time())}.pcap")


def run_capture(
    port: str | None = None,
    *,
    channel: int,
    seconds: float = 20.0,
    mode: str = "pmkid",
    out_path: str | None = None,
    reset: bool = True,
) -> CaptureResult:
    """
    Capture a pcap over serial by driving Marauder's ``-serial`` sniff, then save.

    Opens a session, enables ``SavePCAP``, starts the mode's sniff command with
    ``-serial``, streams for ``seconds``, stops, and writes the reconstructed
    ``.pcap``. Blocking — intended for the CLI ``--capture`` path. The TUI drives
    the same protocol via its own reader instead of calling this.

    Parameters
    ----------
    port : str | None
        Serial device path; auto-detected when ``None``.
    channel : int
        WiFi channel to capture on (the target AP's channel).
    seconds : float
        How long to stream after starting the sniff.
    mode : str
        ``"pmkid"`` or ``"handshake"`` — selects the Marauder command sequence.
    out_path : str | None
        Where to write the ``.pcap``; a timestamped default under ``captures/``
        is used when ``None``.
    reset : bool
        Reset the board on connect (waits for the firmware to boot before
        sending commands).

    Returns
    -------
    CaptureResult
        Summary of what was captured and where it was written.

    Raises
    ------
    ValueError
        If ``mode`` is not a known capture mode.
    """
    if mode not in CAPTURE_MODES:
        raise ValueError(
            f"unknown capture mode {mode!r}; expected one of {list(CAPTURE_MODES)}"
        )

    parser = SavePcapStreamParser()
    lines: list[str] = []
    linebuf = ""

    def on_text(text: str) -> None:
        # Keep decoded console text for EAPOL/PMKID detection and the summary.
        nonlocal linebuf
        linebuf += text
        *complete, linebuf = linebuf.split("\n")
        lines.extend(s.strip() for s in complete)

    dev = Esp32Session(find_port(port), on_data=on_text, on_raw=parser.feed)
    dev.open(reset=reset)
    try:
        if reset:
            # Marauder's WiFi/SD init must finish before the CLI accepts input.
            time.sleep(4.0)
        # Enable the serial pcap path (no-op if already on), then start sniffing.
        dev.send("settings -s SavePCAP true")
        time.sleep(0.5)
        for tmpl in CAPTURE_MODES[mode]:
            dev.send(tmpl.format(channel=channel))
            time.sleep(0.2)
        time.sleep(seconds)
        dev.send("stopscan")
        time.sleep(0.5)
    finally:
        dev.close()

    pcap = parser.pcap_bytes()
    out = out_path or _default_out_path()
    written: str | None = None
    if pcap:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "wb") as fh:
            fh.write(pcap)
        written = out

    frames, eapol = pcap_frame_stats(pcap)
    return CaptureResult(
        pcap_path=written,
        blob_count=parser.blob_count(),
        byte_count=len(pcap),
        valid_pcap=looks_like_pcap(pcap),
        frame_count=frames,
        eapol_frames=eapol,
        log_tail=lines[-8:],
    )


def convert_hc22000(pcap_path: str, out_path: str | None = None) -> str | None:
    """
    Convert a captured ``.pcap`` to a hashcat ``22000`` file, if tooling exists.

    Shells out to ``hcxpcapngtool`` (from ``hcxtools``) when it is on ``PATH``.
    This is optional: the ``.pcap`` is always usable directly in Wireshark or via
    ``aircrack-ng``; ``hc22000`` is just the most convenient input for
    ``hashcat -m 22000``.

    Parameters
    ----------
    pcap_path : str
        Path to the captured pcap.
    out_path : str | None
        Output ``.hc22000`` path; defaults to ``pcap_path`` with the suffix
        replaced.

    Returns
    -------
    str | None
        The ``.hc22000`` path if conversion produced a non-empty file, else
        ``None`` (tool missing or nothing crackable found).
    """
    tool = shutil.which("hcxpcapngtool")
    if not tool:
        return None
    out = out_path or (os.path.splitext(pcap_path)[0] + ".hc22000")
    try:
        subprocess.run(
            [tool, "-o", out, pcap_path],
            check=False,
            capture_output=True,
        )
    except OSError:
        return None
    # hcxpcapngtool always exits 0; a crackable result means a non-empty file.
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    return None
