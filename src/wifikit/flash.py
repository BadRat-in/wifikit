"""
flash.py — download the correct classic-ESP32 Marauder build and flash it.

Why this exists
--------------
The ESP32 Marauder project ships many firmware variants; the ``flipper`` build,
despite its name, targets the ESP32-**S2**, while a bare **classic ESP32**
(e.g. ESP32-WROOM-32) needs the ``old_hardware`` build plus the matching
bootloader/partition table from the project's ``FlashFiles/MarauderV4`` set.
Picking the wrong pair fails with "Unexpected chip ID". This module encodes the
correct combination and offsets so a newcomer can flash in one command.

We intentionally do **not** vendor Marauder's binaries into this repo (they are
upstream's to distribute). Instead we fetch them at flash time from the official
GitHub release / repository.

Firmware and offsets are Copyright ``justcallmekoko`` — see
https://github.com/justcallmekoko/ESP32Marauder
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from .session import find_port

REPO = "justcallmekoko/ESP32Marauder"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/master/FlashFiles/MarauderV4"

# Classic-ESP32 support files (chip ID 0) and the flash offsets Marauder uses.
SUPPORT_FILES = {
    "esp32_marauder.ino.bootloader.bin": 0x1000,
    "esp32_marauder.ino.partitions.bin": 0x8000,
    "boot_app0.bin": 0xE000,
}
APP_OFFSET = 0x10000
# Bare classic ESP32-WROOM-32 uses the "old_hardware" application build.
APP_ASSET_SUFFIX = "old_hardware.bin"


def _download(url: str, dest: Path) -> None:
    """Download ``url`` to ``dest`` with a User-Agent (GitHub requires one)."""
    req = urllib.request.Request(url, headers={"User-Agent": "wifikit-flash"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as fh:
        fh.write(resp.read())


def _resolve_app_url() -> tuple[str, str]:
    """
    Find the latest release asset ending in ``old_hardware.bin``.

    Returns
    -------
    tuple[str, str]
        ``(asset_name, download_url)``.

    Raises
    ------
    SystemExit
        If no matching asset is present in the latest release.
    """
    req = urllib.request.Request(RELEASES_API, headers={"User-Agent": "wifikit-flash"})
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    for asset in data.get("assets", []):
        if asset["name"].endswith(APP_ASSET_SUFFIX):
            return asset["name"], asset["browser_download_url"]
    raise SystemExit(f"No '*{APP_ASSET_SUFFIX}' asset in the latest {REPO} release.")


def fetch_firmware(dest_dir: Path) -> list[tuple[int, Path]]:
    """
    Download the app + support binaries into ``dest_dir``.

    Parameters
    ----------
    dest_dir : Path
        Directory to place the downloaded ``.bin`` files.

    Returns
    -------
    list[tuple[int, Path]]
        ``(offset, path)`` pairs ready to hand to esptool, app last.
    """
    parts: list[tuple[int, Path]] = []
    for name, offset in SUPPORT_FILES.items():
        out = dest_dir / name
        print(f"  ↓ {name}")
        _download(f"{RAW_BASE}/{name}", out)
        parts.append((offset, out))

    app_name, app_url = _resolve_app_url()
    app_out = dest_dir / app_name
    print(f"  ↓ {app_name}")
    _download(app_url, app_out)
    parts.append((APP_OFFSET, app_out))
    return parts


def flash(port: str, parts: list[tuple[int, Path]], baud: int, erase: bool) -> int:
    """
    Invoke esptool to write all images at their offsets.

    Parameters
    ----------
    port : str
        Serial device path.
    parts : list[tuple[int, Path]]
        ``(offset, path)`` pairs to write.
    baud : int
        Flash baud rate. 115200 is the safe default; some USB-UART chips fail
        the mid-session jump to higher rates.
    erase : bool
        Whether to fully erase flash first.

    Returns
    -------
    int
        esptool's exit code.
    """
    base = [
        sys.executable,
        "-m",
        "esptool",
        "--chip",
        "esp32",
        "--port",
        port,
        "--baud",
        str(baud),
    ]
    if erase:
        print("Erasing flash…")
        subprocess.run(base + ["erase-flash"], check=True)

    cmd = base + [
        "write-flash",
        "-z",
        "--flash-mode",
        "dio",
        "--flash-freq",
        "80m",
        "--flash-size",
        "detect",
    ]
    for offset, path in parts:
        cmd += [hex(offset), str(path)]
    print("Flashing…")
    return subprocess.run(cmd).returncode


def main(argv: list[str] | None = None) -> int:
    """CLI: ``wifikit-flash`` — download and flash classic-ESP32 Marauder."""
    ap = argparse.ArgumentParser(
        prog="wifikit-flash",
        description="Download and flash the classic-ESP32 (WROOM-32) ESP32 "
        "Marauder build. Authorized use only.",
    )
    ap.add_argument("--port", help="Serial device (default: auto-detect).")
    ap.add_argument(
        "--baud",
        type=int,
        default=115200,
        help="Flash baud rate (default 115200; safe for CP210x/CH340).",
    )
    ap.add_argument(
        "--erase", action="store_true", help="Fully erase flash before writing."
    )
    args = ap.parse_args(argv)

    port = find_port(args.port)
    print(f"Target port: {port}")
    with tempfile.TemporaryDirectory(prefix="wifikit-fw-") as tmp:
        parts = fetch_firmware(Path(tmp))
        rc = flash(port, parts, args.baud, args.erase)
    if rc == 0:
        print("Done. Open the UI with:  wifikit")
    else:
        print(
            f"esptool exited with {rc}. If it stalled at a higher baud, "
            f"retry with --baud 115200.",
            file=sys.stderr,
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
