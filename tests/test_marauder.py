"""
Unit tests for firmware-output parsing and helpers.

These run without any hardware attached — they exercise the pure functions that
turn Marauder's text output into structured data, which is where parsing bugs
would otherwise hide.
"""

from wifikit.marauder import Station, Target, parse_list_line, parse_station_lines
from wifikit.session import sanitize, score_port


class _FakePort:
    """Minimal stand-in for a pyserial ListPortInfo for scoring tests."""

    def __init__(self, device, description="", manufacturer="", vid=None, pid=None):
        self.device = device
        self.description = description
        self.manufacturer = manufacturer
        self.vid = vid
        self.pid = pid


def test_parse_named_ap():
    t = parse_list_line("[0][CH:3] rb_alderson -72")
    assert t == Target(idx=0, ch=3, name="rb_alderson", rssi=-72)


def test_parse_hidden_ap_uses_bssid_as_name():
    t = parse_list_line("[3][CH:11] 0e:ef:15:a9:3b:d2 -84")
    assert t is not None
    assert t.idx == 3 and t.ch == 11 and t.rssi == -84
    assert t.name == "0e:ef:15:a9:3b:d2"


def test_parse_non_list_lines_return_none():
    for line in ("0 selected", "> ", "Scanning for APs and Stations", ""):
        assert parse_list_line(line) is None


def test_parse_ssid_with_spaces():
    t = parse_list_line("[7][CH:6] My Home WiFi -55")
    assert t is not None
    assert t.name == "My Home WiFi"
    assert t.rssi == -55


def test_sanitize_strips_control_bytes_but_keeps_text():
    raw = "ok\x00\x01line\nnext\ttab"
    assert sanitize(raw) == "okline\nnext\ttab"


def test_score_port_prefers_known_uart_and_rejects_bluetooth():
    esp = _FakePort("/dev/cu.usbserial-1", "CP2102", vid=0x10C4, pid=0xEA60)
    bt = _FakePort("/dev/cu.Bluetooth-Incoming-Port")
    assert score_port(esp) > 0
    assert score_port(bt) < 0


def test_parse_stations_grouped_by_ap():
    block = [
        "[0] rb_alderson -72:",
        "  [3] AA:BB:CC:DD:EE:FF",
        "  [5] 11:22:33:44:55:66 (selected)",
        "[1] Cafe_Guest -66:",
        "  [7] DE:AD:BE:EF:00:01",
    ]
    stations = parse_station_lines(block)
    assert len(stations) == 3
    by_idx = {s.idx: s for s in stations}
    assert by_idx[3] == Station(
        idx=3,
        mac="AA:BB:CC:DD:EE:FF",
        ap_idx=0,
        ap_name="rb_alderson",
        selected=False,
    )
    assert by_idx[5].selected is True
    assert by_idx[5].ap_idx == 0 and by_idx[5].ap_name == "rb_alderson"
    assert by_idx[7].ap_idx == 1
    assert by_idx[7].ap_name == "Cafe_Guest"


def test_parse_stations_filters_multicast():
    block = [
        "[0] rb_alderson -72:",
        "  [1] 01:00:5E:00:00:FB",
        "  [2] 33:33:00:00:00:01",
        "  [3] FF:FF:FF:FF:FF:FF",
        "  [4] AA:BB:CC:DD:EE:FF",
    ]
    stations = parse_station_lines(block)
    assert len(stations) == 1
    assert stations[0].idx == 4
    assert stations[0].mac == "AA:BB:CC:DD:EE:FF"


def test_parse_stations_ignores_ap_list_lines():
    block = ["[0][CH:3] rb_alderson -72", "Scanning..."]
    assert parse_station_lines(block) == []
