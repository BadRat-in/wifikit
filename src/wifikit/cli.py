"""
cli.py — command-line entry point for wifikit.

Provides three ways to talk to the board:

* the **TUI** (default when run with no mode flags) — see :mod:`wifikit.tui`;
* a line-based **REPL** (``--cli``) with echo, history and completion — a
  drop-in, nicer replacement for ``screen`` that Marauder's non-echoing CLI
  otherwise makes painful;
* a **one-shot** mode (``--exec``) that sends a single command and prints the
  reply, for scripting and automation;
* an **SD-free capture** mode (``--capture``) that streams a pcap over serial via
  Marauder's ``-serial`` flag and saves it (see :mod:`wifikit.capture`).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from . import capture
from .marauder import MARAUDER_COMMANDS
from .session import BAUD, Esp32Session, find_port, list_candidate_ports

# Local meta-commands handled by the REPL (not forwarded to the board).
META_COMMANDS = [":help", ":reset", ":ports", ":log", ":capture", ":quit"]

# Command history for the REPL, kept in the user's home (works when installed).
HISTORY_PATH = os.path.expanduser("~/.wifikit_history")


def run_once(port: str, command: str, timeout: float, reset: bool) -> int:
    """
    One-shot mode: connect, optionally reset, send one command, print output.

    Parameters
    ----------
    port : str
        Serial device path.
    command : str
        Marauder command to send.
    timeout : float
        Seconds to read after sending the command.
    reset : bool
        Reset (and wait for boot) before sending.

    Returns
    -------
    int
        Process exit code.
    """
    chunks: list[str] = []
    dev = Esp32Session(port, on_data=chunks.append)
    dev.open(reset=reset)
    if reset:
        time.sleep(4.0)  # let WiFi/GPS/SD init finish so the CLI is listening
    dev.send(command)
    time.sleep(timeout)
    dev.close()
    sys.stdout.write("".join(chunks))
    sys.stdout.flush()
    return 0


def run_capture_cli(
    port: str | None,
    *,
    channel: int,
    seconds: float,
    mode: str,
    out_path: str | None,
    reset: bool,
) -> int:
    """
    SD-free capture mode: stream a pcap over serial, save it, and try to convert.

    Drives :func:`wifikit.capture.run_capture` end to end, prints a concise
    human-readable summary of the resulting :class:`~wifikit.capture.CaptureResult`
    (output path, blob/byte counts, pcap validity, and whether EAPOL/PMKID were
    seen), then — when a pcap was actually written — attempts a hashcat ``22000``
    conversion via :func:`wifikit.capture.convert_hc22000` and reports the
    ``.hc22000`` path (or a hint to install ``hcxtools`` when the tool is absent).

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
        Where to write the ``.pcap``; a timestamped default is used when ``None``.
    reset : bool
        Reset the board on connect before sending commands.

    Returns
    -------
    int
        Process exit code (0 on success).
    """
    result = capture.run_capture(
        port,
        channel=channel,
        seconds=seconds,
        mode=mode,
        out_path=out_path,
        reset=reset,
    )

    # Concise summary of what the capture recovered.
    print(f"[wifikit] capture mode={mode} channel={channel} seconds={seconds:g}")
    print(f"  pcap:       {result.pcap_path or '(none written)'}")
    print(f"  blobs:      {result.blob_count}")
    print(f"  bytes:      {result.byte_count}")
    print(f"  valid pcap: {result.valid_pcap}")
    print(f"  frames:     {result.frame_count}  (EAPOL: {result.eapol_frames})")

    # No EAPOL means nothing crackable was captured (beacons/mgmt only). A PMKID
    # or handshake appears only when a client (re)associates during the window —
    # forcing that needs an authorised deauth of a client on your own network.
    if result.pcap_path and result.eapol_frames == 0:
        print(
            "  note:       no EAPOL captured — needs a client (re)association; "
            "run a brief deauth on your own AP to elicit one."
        )

    # Only attempt conversion when EAPOL frames were actually captured.
    if result.pcap_path and result.eapol_frames > 0:
        hc = capture.convert_hc22000(result.pcap_path)
        if hc:
            print(f"  hc22000:    {hc}")
        else:
            print("  hc22000:    (install hcxtools to convert: brew install hcxtools)")
    return 0


def run_interactive(port: str, reset: bool) -> int:
    """
    Line-based REPL with local echo, history, completion and streamed output.

    prompt_toolkit is imported lazily so ``--exec``/``--list-ports`` work even
    if it is not installed.

    Parameters
    ----------
    port : str
        Serial device path.
    reset : bool
        Reset the board on connect for a clean boot banner.

    Returns
    -------
    int
        Process exit code.
    """
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.patch_stdout import patch_stdout

    log_file = {"fh": None}

    def on_data(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()
        if log_file["fh"]:
            log_file["fh"].write(text)
            log_file["fh"].flush()

    dev = Esp32Session(port, on_data=on_data)
    dev.open(reset=reset)

    completer = WordCompleter(MARAUDER_COMMANDS + META_COMMANDS, ignore_case=True)
    session = PromptSession(
        history=FileHistory(HISTORY_PATH),
        auto_suggest=AutoSuggestFromHistory(),
        completer=completer,
    )

    print(
        f"[wifikit] connected on {port} @ {BAUD}. "
        f"Type Marauder commands, or :help for meta-commands. Ctrl-D to quit."
    )

    with patch_stdout():
        while True:
            try:
                line = session.prompt("wifikit> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line.startswith(":"):
                if line in (":quit", ":q"):
                    break
                elif line == ":reset":
                    dev.reset()
                elif line == ":ports":
                    for score, p in list_candidate_ports():
                        print(f"  [{score:>4}] {p.device}  {p.description or ''}")
                elif line == ":help":
                    print("  :reset  reboot board   :ports  list serial ports")
                    print("  :log <file> | :log off  tee output   :quit  exit")
                    print("  :capture <channel> [seconds] [mode]  SD-free pcap")
                elif line.startswith(":capture"):
                    # The REPL already holds this port open with its own reader
                    # thread; running a capture here would spawn a second reader
                    # on the same device. Instead, print the exact standalone
                    # command to run (the capture path opens its own session).
                    parts = line.split()
                    ch = parts[1] if len(parts) > 1 else "<channel>"
                    extra = ""
                    if len(parts) > 2:
                        extra += f" --seconds {parts[2]}"
                    if len(parts) > 3:
                        extra += f" --mode {parts[3]}"
                    print("  :capture runs a standalone capture (needs its own")
                    print("  serial reader). Quit this REPL (:quit) and run:")
                    print(f"    wifikit --port {port} --capture --channel {ch}{extra}")
                elif line.startswith(":log"):
                    parts = line.split(maxsplit=1)
                    if len(parts) == 2 and parts[1] != "off":
                        log_file["fh"] = open(parts[1], "a")
                        print(f"  logging to {parts[1]}")
                    else:
                        if log_file["fh"]:
                            log_file["fh"].close()
                        log_file["fh"] = None
                        print("  logging off")
                else:
                    print(f"  unknown meta-command: {line} (try :help)")
                continue
            dev.send(line)

    if log_file["fh"]:
        log_file["fh"].close()
    dev.close()
    print("\n[wifikit] session closed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser (kept separate so it can be unit-tested)."""
    ap = argparse.ArgumentParser(
        prog="wifikit",
        description="Terminal UI + CLI for an ESP32 Marauder WiFi test rig. "
        "Authorized use only — test networks you own or may lawfully test.",
    )
    ap.add_argument("--port", help="Serial device (default: auto-detect).")
    ap.add_argument(
        "--no-reset", action="store_true", help="Do not reset the board on connect."
    )
    ap.add_argument(
        "--list-ports",
        action="store_true",
        help="List candidate serial ports and exit.",
    )
    ap.add_argument(
        "--cli",
        action="store_true",
        help="Force the line-based REPL instead of the TUI.",
    )
    ap.add_argument(
        "--demo",
        action="store_true",
        help="Launch the TUI with sample data and no board (for trying the UI).",
    )
    ap.add_argument(
        "--exec", metavar="CMD", help="One-shot: send CMD, print output, exit."
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=6.0,
        help="Seconds to read in --exec mode (default 6).",
    )
    ap.add_argument(
        "--capture",
        action="store_true",
        help="SD-free capture: stream a pcap over serial via Marauder's "
        "-serial and save it.",
    )
    ap.add_argument(
        "--channel",
        type=int,
        help="WiFi channel to capture on (required with --capture).",
    )
    ap.add_argument(
        "--seconds",
        type=float,
        default=20.0,
        help="Capture duration in seconds (default 20).",
    )
    ap.add_argument(
        "--mode",
        choices=["pmkid", "handshake"],
        default="pmkid",
        help="Capture mode.",
    )
    ap.add_argument(
        "--out",
        metavar="PATH",
        help="Output .pcap path (default captures/<timestamp>.pcap).",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the selected mode."""
    args = build_parser().parse_args(argv)

    if args.list_ports:
        for score, p in list_candidate_ports():
            print(f"[{score:>4}] {p.device:35} {p.description or ''}")
        return 0

    if args.exec is not None:
        return run_once(
            find_port(args.port), args.exec, args.timeout, not args.no_reset
        )
    if args.capture:
        # --channel has no sensible default: the target AP's channel is required.
        if args.channel is None:
            print("error: --capture requires --channel N", file=sys.stderr)
            return 2
        return run_capture_cli(
            args.port,
            channel=args.channel,
            seconds=args.seconds,
            mode=args.mode,
            out_path=args.out,
            reset=not args.no_reset,
        )
    if args.cli:
        return run_interactive(find_port(args.port), not args.no_reset)

    # Default: launch the graphical TUI (the intended everyday interface).
    from .tui import run as run_tui

    return run_tui(args.port, demo=args.demo)


if __name__ == "__main__":
    raise SystemExit(main())
