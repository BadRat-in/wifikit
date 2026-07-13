"""
session.py — USB-serial transport to the ESP32 board.

Provides serial-port auto-detection (skipping Bluetooth/debug ports) and
:class:`Esp32Session`, a thin wrapper that runs a background reader thread and
hands decoded, sanitized text to a callback. Keeping all I/O here lets the CLI
and TUI share one battle-tested transport layer.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import serial
from serial.tools import list_ports

# Serial speed the Marauder firmware uses.
BAUD = 115200

# USB-UART bridge chips commonly found on ESP32 DevKits, keyed by (VID, PID).
KNOWN_UART_IDS: dict[tuple[int, int], str] = {
    (0x10C4, 0xEA60): "CP210x (Silicon Labs)",
    (0x1A86, 0x7523): "CH340 (WCH)",
    (0x1A86, 0x55D4): "CH9102 (WCH)",
    (0x0403, 0x6001): "FT232 (FTDI)",
    (0x303A, 0x1001): "ESP32 native USB",
}


def sanitize(text: str) -> str:
    """
    Strip non-printable bytes so garbled ROM-boot output can't corrupt the
    terminal, while preserving tabs, newlines and printable ASCII.

    Parameters
    ----------
    text : str
        Raw decoded text from the serial port.

    Returns
    -------
    str
        Text containing only tab/newline/carriage-return and printable ASCII.
    """
    return "".join(c for c in text if c in "\t\n\r" or 0x20 <= ord(c) <= 0x7E)


def score_port(p) -> int:
    """
    Heuristically score a serial port for "is this the ESP32?" (higher = better).

    Known UART chip VID/PIDs score highest; usbserial-style names add points;
    Bluetooth/debug/audio ports go negative so they are never auto-selected.

    Parameters
    ----------
    p : serial.tools.list_ports_common.ListPortInfo
        A discovered serial port.

    Returns
    -------
    int
        Confidence score.
    """
    score = 0
    if p.vid is not None and (p.vid, p.pid) in KNOWN_UART_IDS:
        score += 100
    blob = f"{p.device} {p.description or ''} {p.manufacturer or ''}".lower()
    for good in ("usbserial", "slab", "wchusbserial", "usbmodem"):
        if good in blob:
            score += 10
    for bad in ("bluetooth", "debug-console", "incoming", "n/a"):
        if bad in blob:
            score -= 100
    return score


def list_candidate_ports() -> list[tuple[int, object]]:
    """Return all serial ports as ``(score, port_info)``, best score first."""
    ports = [(score_port(p), p) for p in list_ports.comports()]
    return sorted(ports, key=lambda t: t[0], reverse=True)


def find_port(preferred: str | None = None) -> str:
    """
    Resolve the ESP32 serial device, auto-detecting when not given.

    Parameters
    ----------
    preferred : str | None
        Explicit device path; returned as-is if provided.

    Returns
    -------
    str
        The chosen serial device path.

    Raises
    ------
    SystemExit
        If no plausible ESP32 port can be found.
    """
    if preferred:
        return preferred
    ranked = list_candidate_ports()
    if not ranked or ranked[0][0] <= 0:
        raise SystemExit(
            "No ESP32 serial port found. Plug the board in, or pass --port. "
            "Use --list-ports to see what's available."
        )
    return ranked[0][1].device


class Esp32Session:
    """
    Manages one serial connection plus a background reader thread.

    The reader continuously pulls bytes from the port and hands decoded,
    sanitized text to ``on_data``, decoupling I/O from the UI so streaming
    firmware output never blocks or garbles the interface.
    """

    def __init__(
        self,
        port: str,
        on_data: Callable[[str], None],
        baud: int = BAUD,
        on_raw: Callable[[bytes], None] | None = None,
    ) -> None:
        """
        Parameters
        ----------
        port : str
            Serial device path.
        on_data : Callable[[str], None]
            Called with each chunk of decoded, sanitized text as it arrives.
        baud : int
            Baud rate (default 115200, matching Marauder).
        on_raw : Callable[[bytes], None] | None
            Optional tap that receives each chunk of **raw, undecoded bytes**
            before sanitisation. Needed for binary capture streams (Marauder's
            ``-serial`` pcap output), whose bytes :func:`sanitize` would destroy.
            Settable at any time (the reader re-reads it each loop), so a UI can
            switch capture on/off mid-session. ``None`` disables the tap.
        """
        self.port = port
        self.baud = baud
        self.on_data = on_data
        self.on_raw = on_raw
        self.ser: serial.Serial | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def open(self, reset: bool = True) -> None:
        """
        Open the port and start the reader thread.

        DTR/RTS are pre-seeded to the "run" state before opening to avoid an
        unintended reset; an explicit reset is issued only if requested.

        Parameters
        ----------
        reset : bool
            If True, pulse the board's reset line so we capture a fresh boot.
        """
        ser = serial.Serial()
        ser.port = self.port
        ser.baudrate = self.baud
        ser.timeout = 0.1
        ser.dtr = False  # GPIO0 high -> normal boot
        ser.rts = False  # EN high    -> not in reset
        ser.open()
        self.ser = ser
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        if reset:
            self.reset()

    def _reader(self) -> None:
        """Background loop: read serial, decode, sanitize, emit via on_data."""
        assert self.ser is not None
        while not self._stop.is_set():
            try:
                data = self.ser.read(4096)
            except (serial.SerialException, OSError):
                self.on_data("\n[wifikit] serial disconnected\n")
                return
            if data:
                # Raw tap first: binary capture blobs must be seen intact,
                # before sanitisation strips their non-printable bytes.
                if self.on_raw is not None:
                    self.on_raw(data)
                self.on_data(sanitize(data.decode("utf-8", errors="replace")))

    def reset(self) -> None:
        """Pulse EN (via RTS) low->high with GPIO0 high to reboot into the app."""
        assert self.ser is not None
        self.ser.dtr = False  # GPIO0 high -> normal boot
        self.ser.rts = True  # EN low     -> hold in reset
        time.sleep(0.1)
        self.ser.rts = False  # EN high    -> release; boots the flashed app

    def send(self, line: str) -> None:
        """Send one command line to the board, terminated with CR/LF."""
        assert self.ser is not None
        self.ser.write((line + "\r\n").encode())

    def close(self) -> None:
        """Stop the reader thread and close the port."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self.ser and self.ser.is_open:
            self.ser.close()
