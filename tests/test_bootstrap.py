"""
Unit tests for the external-tool installer (:mod:`wifikit.bootstrap`).

The package-manager detection and command-building logic is pure (the ``which``
resolver is injected), so it is fully testable without touching the real system
or running any installs.
"""

from wifikit.bootstrap import (
    detect_manager,
    install_argv,
    missing_packages,
)


def _which_none(_name: str) -> str | None:
    return None


def _present(*names: str):
    """Return a fake ``which`` that resolves only the given command names."""

    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in names else None

    return which


def test_detect_manager_macos():
    assert detect_manager("darwin", which=_present("brew")) == "brew"
    assert detect_manager("darwin", which=_which_none) is None


def test_detect_manager_linux_prefers_apt():
    assert detect_manager("linux", which=_present("apt-get", "dnf")) == "apt"


def test_detect_manager_linux_pacman_only():
    assert detect_manager("linux", which=_present("pacman")) == "pacman"


def test_detect_manager_unsupported_platform():
    assert detect_manager("win32", which=_present("brew", "apt-get")) is None


def test_missing_packages_recommended_only_by_default():
    # Nothing installed -> the two recommended tools, mapped to package names.
    assert missing_packages("brew", which=_which_none) == ["hashcat", "hcxtools"]


def test_missing_packages_include_optional():
    got = missing_packages("apt", include_optional=True, which=_which_none)
    assert got == ["hashcat", "hcxtools", "aircrack-ng"]


def test_missing_packages_skips_present_tools():
    # hashcat present -> only the hcxtools package (for hcxpcapngtool) is missing.
    assert missing_packages("brew", which=_present("hashcat")) == ["hcxtools"]


def test_install_argv_per_manager():
    assert install_argv("brew", ["hashcat"]) == ["brew", "install", "hashcat"]
    assert install_argv("apt", ["hashcat", "hcxtools"]) == [
        "sudo",
        "apt-get",
        "install",
        "-y",
        "hashcat",
        "hcxtools",
    ]
    assert install_argv("pacman", ["hashcat"]) == [
        "sudo",
        "pacman",
        "-S",
        "--noconfirm",
        "hashcat",
    ]
