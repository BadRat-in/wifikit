"""
wifikit — a terminal UI + CLI for driving an ESP32 running the Marauder
firmware, for authorized WiFi security testing and learning.

The package is split into small, single-responsibility modules:

* ``session``  — USB-serial transport: port auto-detection and a threaded
  reader/writer wrapper around the board.
* ``marauder`` — knowledge about the Marauder firmware: its command set and
  the format of its ``list`` output (parsed into :class:`~wifikit.marauder.Target`).
* ``cli``      — argparse entry point, a line-based REPL, and one-shot exec mode.
* ``tui``      — the Textual dashboard (the default, everyday interface).
* ``flash``    — downloads the correct classic-ESP32 build and flashes it.

See the project README for the authorized-use policy. Only operate on networks
you own or are explicitly permitted to test.
"""

__version__ = "0.1.0"
