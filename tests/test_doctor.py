"""
Unit tests for the external-dependency report (:mod:`wifikit.doctor`).

Exercises the pure platform-selection and report-formatting logic; tool presence
itself is system-dependent and not asserted.
"""

from wifikit.doctor import (
    EXTERNAL_TOOLS,
    check_tools,
    format_report,
    install_hint,
)

_HINTS = {"darwin": "brew install foo", "linux": "sudo apt install foo"}


def test_install_hint_selects_platform():
    assert install_hint(_HINTS, "linux") == "sudo apt install foo"
    assert install_hint(_HINTS, "linux2") == "sudo apt install foo"  # legacy value
    assert install_hint(_HINTS, "darwin") == "brew install foo"


def test_install_hint_windows_fallback():
    hint = install_hint(_HINTS, "win32")
    assert "brew install foo" in hint
    assert "package manager" in hint


def test_format_report_marks_present_and_missing():
    rows = [
        ("hashcat", "crack WPA", "/usr/bin/hashcat", "brew install hashcat"),
        ("hcxpcapngtool", "convert pcap", None, "brew install hcxtools"),
    ]
    report = format_report(rows)
    assert "[OK]      hashcat" in report
    assert "/usr/bin/hashcat" in report
    assert "[MISSING] hcxpcapngtool" in report
    assert "install: brew install hcxtools" in report
    # The reassuring note appears only when something is missing.
    assert "scanning, deauth and capture work without these" in report


def test_format_report_no_note_when_all_present():
    rows = [("hashcat", "crack WPA", "/usr/bin/hashcat", "brew install hashcat")]
    assert "work without these" not in format_report(rows)


def test_check_tools_shape():
    rows = check_tools(platform="darwin")
    assert len(rows) == len(EXTERNAL_TOOLS)
    for name, _purpose, path, hint in rows:
        assert isinstance(name, str) and name
        assert isinstance(hint, str) and hint
        assert path is None or isinstance(path, str)
