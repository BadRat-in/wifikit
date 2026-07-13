"""
doctor.py — report the external tools wifikit needs and how to install them.

wifikit ships as a pip package, so its **Python** dependencies (pyserial,
prompt_toolkit, textual, esptool) install automatically with
``pip install wifikit``. But the heavy lifting on the host is done by **native
CLI tools that pip cannot install** — you install those with your OS package
manager. ``wifikit --doctor`` shows which are present, which are missing, and the
exact command to install each on this platform, so a new user isn't left guessing.

The tool set is intentionally *optional*: scanning, deauth and capture work with
none of them; they are only needed for the cracking half of the workflow.

**Authorized-use only.**
"""

from __future__ import annotations

import shutil
import sys

# External CLI tools wifikit shells out to. Each entry is:
#   (command, purpose, required?, {platform: install command})
# "required" is False for everything — wifikit degrades gracefully — but the
# report flags missing tools you'd need for the crack step.
EXTERNAL_TOOLS: list[tuple[str, str, dict[str, str]]] = [
    (
        "hashcat",
        "crack captured WPA (Crack tab, --benchmark)",
        {"darwin": "brew install hashcat", "linux": "sudo apt install hashcat"},
    ),
    (
        "hcxpcapngtool",
        "convert .pcap -> .hc22000 for hashcat",
        {"darwin": "brew install hcxtools", "linux": "sudo apt install hcxtools"},
    ),
    (
        "aircrack-ng",
        "alternative cracker (optional)",
        {
            "darwin": "brew install aircrack-ng",
            "linux": "sudo apt install aircrack-ng",
        },
    ),
]


def install_hint(hints: dict[str, str], platform: str) -> str:
    """
    Pick the install command for the current platform, with a sane fallback.

    Parameters
    ----------
    hints : dict[str, str]
        Platform → install command (keys ``"darwin"`` / ``"linux"``).
    platform : str
        A ``sys.platform`` value.

    Returns
    -------
    str
        The best install command for this platform (falls back to the macOS/brew
        hint, then a generic pointer for anything unrecognised like Windows).
    """
    if platform.startswith("linux"):
        return hints.get("linux", "see the tool's website")
    if platform == "darwin":
        return hints.get("darwin", "see the tool's website")
    # Windows / other: brew/apt don't apply — point at the projects.
    return hints.get("darwin", "see the tool's website") + "  (or your package manager)"


def check_tools(
    platform: str = sys.platform,
) -> list[tuple[str, str, str | None, str]]:
    """
    Resolve each external tool on ``PATH``.

    Returns
    -------
    list[tuple[str, str, str | None, str]]
        ``(name, purpose, path_or_None, install_command)`` per tool.
    """
    rows = []
    for name, purpose, hints in EXTERNAL_TOOLS:
        rows.append((name, purpose, shutil.which(name), install_hint(hints, platform)))
    return rows


def format_report(rows: list[tuple[str, str, str | None, str]]) -> str:
    """Render the dependency report from :func:`check_tools` rows."""
    lines = [
        "wifikit dependency check",
        "",
        "Python deps (installed automatically with wifikit):",
        "  [OK] pyserial · prompt_toolkit · textual · esptool",
        "",
        "External tools (install separately — pip cannot):",
    ]
    for name, purpose, path, hint in rows:
        if path:
            lines.append(f"  [OK]      {name:<15} {path}")
        else:
            lines.append(f"  [MISSING] {name:<15} — {purpose}")
            lines.append(f"            install: {hint}")
    lines += [
        "",
        "Firmware: no manual download — `wifikit-flash` fetches the correct "
        "Marauder build on demand.",
    ]
    missing = [n for n, _, p, _ in rows if p is None]
    if missing:
        lines.append("")
        lines.append(
            "Note: scanning, deauth and capture work without these; they are only "
            "needed to crack a captured handshake/PMKID."
        )
    return "\n".join(lines)


def run_doctor() -> int:
    """
    Print the external-tool report. Always returns 0 (informational).

    Returns
    -------
    int
        Process exit code (0).
    """
    print(format_report(check_tools()))
    return 0
