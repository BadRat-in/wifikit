"""
config.py — persistent user settings for wifikit.

Holds the handful of knobs a user reasonably wants to tune (capture length,
whether Capture auto-deauths, the default wordlist, output locations, UI theme,
serial port) and persists them as JSON under the platform config dir so they
survive across runs. JSON is used rather than TOML because writing TOML needs a
third-party package, whereas ``json`` is stdlib on every supported Python.

The TUI's **Settings** tab reads and writes a :class:`Config`; the CLI reads it
for its defaults. Everything degrades gracefully: a missing or corrupt file just
yields the defaults.

**Authorized-use only.**
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

# Where the settings file lives (honours XDG_CONFIG_HOME, else ~/.config).
_XDG = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
CONFIG_PATH = Path(_XDG) / "wifikit" / "config.json"


@dataclass
class Config:
    """
    User-configurable settings, with sensible defaults.

    Attributes
    ----------
    capture_seconds : int
        How long each Capture streams before stopping.
    auto_deauth : bool
        If True, Capture first fires a deauth burst (see ``deauth_seconds``) to
        force a client to reassociate, then sniffs — one coordinated action.
    deauth_seconds : int
        Length of that deauth burst.
    wordlist : str
        Path prefilled into the Crack tab's hashcat command. Empty means
        "resolve automatically" (see :meth:`resolved_wordlist`).
    auto_convert : bool
        Convert a captured ``.pcap`` to ``.hc22000`` via ``hcxpcapngtool`` when
        it is installed.
    captures_dir : str
        Directory where captured ``.pcap`` files are written.
    theme : str
        Textual theme name for the UI.
    port : str
        Serial device override; empty means auto-detect.
    """

    capture_seconds: int = 20
    auto_deauth: bool = False
    deauth_seconds: int = 5
    wordlist: str = ""
    auto_convert: bool = True
    captures_dir: str = "captures"
    theme: str = "textual-dark"
    port: str = ""

    def resolved_wordlist(self) -> str:
        """Return the configured wordlist, or auto-pick one if unset."""
        if self.wordlist:
            return self.wordlist
        rockyou = Path(self.captures_dir).parent / "wordlists" / "rockyou.txt"
        real = Path("wordlists/rockyou.txt")
        if real.exists() or rockyou.exists():
            return "wordlists/rockyou.txt"
        return "wordlists/example-passwords.txt"


def load_config(path: Path = CONFIG_PATH) -> Config:
    """
    Load settings from ``path``, falling back to defaults for anything missing.

    Unknown keys in the file are ignored, so an older/newer config never crashes
    a load. A missing or unreadable/corrupt file yields an all-defaults Config.
    """
    data: dict = {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    known = {f.name for f in fields(Config)}
    clean = {k: v for k, v in data.items() if k in known}
    return Config(**clean)


def save_config(config: Config, path: Path = CONFIG_PATH) -> None:
    """Write ``config`` to ``path`` as pretty JSON, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2) + "\n")
