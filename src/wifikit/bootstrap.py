"""
bootstrap.py — one-command install of the external CLI tools wifikit needs.

``pip install wifikit`` brings the Python dependencies, and ``wifikit-flash``
fetches the firmware on demand — but the native cracking tools (``hashcat``,
``hcxtools``) come from your OS package manager. ``wifikit --setup`` closes that
last gap: it detects your package manager (Homebrew / apt / dnf / pacman), works
out which tools are missing, shows the exact command, and installs them.

This is a convenience wrapper around your package manager — it does not download
random binaries; it runs ``brew install`` / ``apt install`` / etc. so the tools
come from the same trusted source you'd use by hand.

**Authorized-use only.**
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable

# Package managers wifikit knows how to drive, in detection order per OS.
# Each maps to the argv prefix that installs one or more packages.
PACKAGE_MANAGERS: dict[str, list[str]] = {
    "brew": ["brew", "install"],
    "apt": ["sudo", "apt-get", "install", "-y"],
    "dnf": ["sudo", "dnf", "install", "-y"],
    "pacman": ["sudo", "pacman", "-S", "--noconfirm"],
}

# The tools wifikit shells out to, with the command probed on PATH and the
# package name per manager (the command and package names often differ, e.g.
# the `hcxpcapngtool` command ships in the `hcxtools` package).
#   (command, {manager: package}, recommended?)
TOOLS: list[tuple[str, dict[str, str], bool]] = [
    ("hashcat", dict.fromkeys(PACKAGE_MANAGERS, "hashcat"), True),
    ("hcxpcapngtool", dict.fromkeys(PACKAGE_MANAGERS, "hcxtools"), True),
    ("aircrack-ng", dict.fromkeys(PACKAGE_MANAGERS, "aircrack-ng"), False),
]


def detect_manager(
    platform: str = sys.platform,
    which: Callable[[str], str | None] = shutil.which,
) -> str | None:
    """
    Pick the OS package manager to use.

    Parameters
    ----------
    platform : str
        A ``sys.platform`` value.
    which : Callable[[str], str | None]
        Resolver for a command on PATH (injected for testing).

    Returns
    -------
    str | None
        A key of :data:`PACKAGE_MANAGERS`, or ``None`` if none is available.
    """
    if platform == "darwin":
        return "brew" if which("brew") else None
    if platform.startswith("linux"):
        for mgr, detect in (("apt", "apt-get"), ("dnf", "dnf"), ("pacman", "pacman")):
            if which(detect):
                return mgr
    return None


def missing_packages(
    manager: str,
    include_optional: bool = False,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """
    Return the package names to install for tools not already on PATH.

    Parameters
    ----------
    manager : str
        A :data:`PACKAGE_MANAGERS` key (selects the package naming).
    include_optional : bool
        Also include non-recommended tools (e.g. ``aircrack-ng``).
    which : Callable[[str], str | None]
        Resolver for a command on PATH (injected for testing).

    Returns
    -------
    list[str]
        Package names for the missing tools, in declaration order.
    """
    pkgs = []
    for cmd, packages, recommended in TOOLS:
        if not recommended and not include_optional:
            continue
        if which(cmd) is None:
            pkgs.append(packages[manager])
    return pkgs


def install_argv(manager: str, packages: list[str]) -> list[str]:
    """Build the full install command for ``manager`` + ``packages``."""
    return PACKAGE_MANAGERS[manager] + packages


def run_setup(include_optional: bool = False, assume_yes: bool = False) -> int:
    """
    Detect the package manager and install any missing external tools.

    Parameters
    ----------
    include_optional : bool
        Also install optional tools (aircrack-ng).
    assume_yes : bool
        Skip the confirmation prompt (required when stdin is not a TTY).

    Returns
    -------
    int
        Process exit code (0 on success / nothing to do; non-zero on failure or
        an unsupported/declined install).
    """
    manager = detect_manager()
    if manager is None:
        print(
            "No supported package manager found (brew/apt/dnf/pacman).\n"
            "Install the tools manually — run `wifikit --doctor` for the commands."
        )
        return 1

    packages = missing_packages(manager, include_optional=include_optional)
    if not packages:
        print("All required external tools are already installed. ✓")
        return 0

    argv = install_argv(manager, packages)
    print(f"Detected package manager: {manager}")
    print(f"Missing tools will be installed with:\n  {' '.join(argv)}\n")

    if not assume_yes:
        if not sys.stdin.isatty():
            print("Re-run with --yes to install non-interactively.")
            return 1
        reply = input("Proceed? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted — nothing installed.")
            return 1

    rc = subprocess.run(argv).returncode
    print()
    # Show the resulting state either way.
    from . import doctor

    doctor.run_doctor()
    if rc != 0:
        print(f"\nInstaller exited with {rc}.")
    return rc
