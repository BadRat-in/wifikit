"""
marauder.py — knowledge specific to the ESP32 Marauder firmware.

Isolating the firmware's command set and output formats here means the
transport (``session``) and the UIs (``cli``/``tui``) stay firmware-agnostic;
if Marauder's output changes, this is the only file to touch.

Credit: the firmware itself is ESP32 Marauder by ``justcallmekoko``
(https://github.com/justcallmekoko/ESP32Marauder). wifikit only drives it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# Top-level Marauder CLI commands (from `help` on v1.13.0), used for completion.
MARAUDER_COMMANDS: list[str] = [
    "channel",
    "settings",
    "clearlist",
    "reboot",
    "update",
    "ls",
    "led",
    "gpsdata",
    "gps",
    "nmea",
    "gpspoi",
    "gpstracker",
    "evilportal",
    "karma",
    "packetcount",
    "pingscan",
    "arpscan",
    "portscan",
    "sigmon",
    "scanall",
    "sniffraw",
    "sniffbeacon",
    "sniffprobe",
    "sniffpwn",
    "sniffpinescan",
    "sniffmultissid",
    "sniffdeauth",
    "sniffpmkid",
    "sniffsae",
    "stopscan",
    "wardrive",
    "wardrivepoi",
    "mactrack",
    "attack",
    "info",
    "list",
    "select",
    "ssid",
    "save",
    "load",
    "join",
    "randapmac",
    "randstamac",
    "cloneapmac",
    "clonestamac",
    "add",
    "sniffbt",
    "blespam",
    "spoofat",
    "sniffskim",
    "brightness",
]

# A row of `list -a` output, e.g.  "[0][CH:3] rb_alderson -72"
AP_LINE = re.compile(r"^\[(\d+)\]\[CH:(\d+)\]\s+(.*?)\s+(-?\d+)\s*$")

# Station list is `list -c` (NOT `list -s`, which lists SSIDs). Its output is
# *grouped by AP* and needs a stateful, two-shape parser:
#   AP header (column 0, trailing colon):  "[0] rb_alderson -72:"
#   Station row (indented, optional flag): "  [3] AA:BB:CC:DD:EE:FF (selected)"
# The station index is Marauder's *global* station index (what `select -c <idx>`
# expects); the row carries only that index and a MAC — no channel or RSSI.
STA_AP_HEADER = re.compile(r"^\[(\d+)\]\s+(.*?)\s+(-?\d+):\s*$")
STA_ROW = re.compile(r"^\s+\[(\d+)\]\s+([0-9A-Fa-f:]{17})(?:\s+\(selected\))?\s*$")

# MAC prefixes that denote multicast/broadcast destinations, not real clients
# (IPv6 mDNS `33:33:*`, IPv4 multicast `01:00:5e:*`, broadcast `ff:ff:ff:*`).
_NON_CLIENT_PREFIXES = ("33:33:", "01:00:5e:", "ff:ff:ff:")


@dataclass
class Target:
    """
    One access point (or station) as reported by Marauder's ``list`` command.

    Attributes
    ----------
    idx : int
        Marauder's internal select-index — the value ``select -a <idx>`` expects.
    ch : int
        WiFi channel.
    name : str
        ESSID, or the BSSID when the network is hidden / not broadcasting a name.
    rssi : int
        Signal strength in dBm (negative; closer to 0 is stronger).
    """

    idx: int
    ch: int
    name: str
    rssi: int


def parse_list_line(line: str) -> Target | None:
    """
    Parse a single line of Marauder ``list -a``/``list -s`` output.

    Parameters
    ----------
    line : str
        One stripped line of serial output.

    Returns
    -------
    Target | None
        A populated :class:`Target` if the line is a list entry, else ``None``.

    Examples
    --------
    >>> parse_list_line("[0][CH:3] rb_alderson -72")
    Target(idx=0, ch=3, name='rb_alderson', rssi=-72)
    >>> parse_list_line("0 selected") is None
    True
    """
    m = AP_LINE.match(line)
    if not m:
        return None
    return Target(idx=int(m[1]), ch=int(m[2]), name=m[3], rssi=int(m[4]))


@dataclass
class Station:
    """
    One connected client (station) as reported by Marauder's ``list -c``.

    Attributes
    ----------
    idx : int
        Marauder's *global* station select-index — what ``select -c <idx>``
        expects.
    mac : str
        The station's MAC address (17-char colon form).
    ap_idx : int | None
        Index (in the AP list) of the access point this station is associated
        with, derived from the grouping in ``list -c`` output. ``None`` if the
        station appeared without a preceding AP header (shouldn't normally
        happen).
    ap_name : str | None
        ESSID/BSSID of the associated AP, for display.
    selected : bool
        Whether Marauder currently has this station selected (``(selected)``
        suffix in the output).
    """

    idx: int
    mac: str
    ap_idx: int | None = None
    ap_name: str | None = None
    selected: bool = False


def parse_station_lines(lines: Iterable[str]) -> list[Station]:
    """
    Parse a block of Marauder ``list -c`` output into :class:`Station` objects.

    ``list -c`` prints clients **grouped under their access point**, so this is a
    stateful parse over a *block* of raw (un-stripped) lines rather than a
    per-line function: an AP header line sets the "current AP", and each indented
    station row that follows is attributed to it. Multicast/broadcast pseudo
    "stations" are filtered out. Lines that match neither shape (banners, the AP
    list, prompts) are ignored, so it is safe to feed a mixed console buffer.

    Parameters
    ----------
    lines : Iterable[str]
        Raw serial lines, **with indentation preserved** (station rows are
        distinguished from AP headers by their leading whitespace).

    Returns
    -------
    list[Station]
        Real client stations, in the order encountered.

    Examples
    --------
    >>> block = [
    ...     "[0] rb_alderson -72:",
    ...     "  [3] AA:BB:CC:DD:EE:FF",
    ...     "  [5] 11:22:33:44:55:66 (selected)",
    ... ]
    >>> [ (s.idx, s.mac, s.ap_idx, s.selected) for s in parse_station_lines(block) ]
    [(3, 'AA:BB:CC:DD:EE:FF', 0, False), (5, '11:22:33:44:55:66', 0, True)]
    """
    stations: list[Station] = []
    cur_ap_idx: int | None = None
    cur_ap_name: str | None = None
    for line in lines:
        header = STA_AP_HEADER.match(line)
        if header is not None:
            cur_ap_idx = int(header[1])
            cur_ap_name = header[2]
            continue
        row = STA_ROW.match(line)
        if row is None:
            continue
        mac = row[2]
        # Skip multicast/broadcast destinations — they aren't real clients.
        if mac.lower().startswith(_NON_CLIENT_PREFIXES):
            continue
        stations.append(
            Station(
                idx=int(row[1]),
                mac=mac,
                ap_idx=cur_ap_idx,
                ap_name=cur_ap_name,
                selected="(selected)" in line,
            )
        )
    return stations
