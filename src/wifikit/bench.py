"""
bench.py — measure WPA cracking speed on this machine and translate it to
real-world "how long would that take?" numbers.

The compute-heavy half of wifikit's workflow is cracking the captured
handshake/PMKID with ``hashcat -m 22000`` (WPA-PBKDF2-HMAC-SHA1). That runs on
the host GPU — hashcat auto-selects it (Metal on Apple Silicon, CUDA/OpenCL
elsewhere), so there is nothing for wifikit to "enable"; the GPU is already the
engine. What is genuinely useful is a reproducible **number**: how many passphrase
candidates per second this machine tests, and therefore how long different attack
keyspaces would take.

``wifikit --benchmark`` runs hashcat's own mode-22000 benchmark, parses the hash
rate, and prints a crack-time table derived from it. The parsing/estimation logic
is pure and unit-tested; only :func:`run_benchmark` needs hashcat installed.

**Authorized-use only.** Estimate crack times to reason about the strength of
networks you own or are permitted to test.
"""

from __future__ import annotations

import re
import shutil
import subprocess

# hashcat mode for WPA/WPA2 from a PMKID or EAPOL handshake.
HASHCAT_MODE = 22000

# SI-suffix multipliers for hashcat's "H/s" / "kH/s" / "MH/s" … output.
_UNIT = {"": 1.0, "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}

# A hashcat benchmark speed line, e.g. "Speed.#02........: 81055 H/s (33.77ms) …".
_SPEED_RE = re.compile(r"Speed\.#\d+[.\s]*:\s*([\d,]+(?:\.\d+)?)\s*([kMGT]?)H/s")

# Representative keyspaces to illustrate crack time. Each is (label, candidates).
# WPA passphrases are 8-63 chars, so 8 chars is the practical brute-force floor.
KEYSPACES: list[tuple[str, int]] = [
    ("Common wordlist (rockyou.txt)", 14_344_391),
    ("8-digit PIN (0-9)", 10**8),
    ("10-digit phone (0-9)", 10**10),
    ("8-char lowercase (a-z)", 26**8),
    ("8-char lower + digits", 36**8),
    ("8-char mixed-case + digits", 62**8),
    ("8-char full printable ASCII", 95**8),
]


def parse_hashrate(text: str) -> float | None:
    """
    Extract the hash rate (candidates/second) from hashcat benchmark output.

    Parameters
    ----------
    text : str
        Captured hashcat output containing one or more ``Speed.#N`` lines.

    Returns
    -------
    float | None
        The highest per-device rate in H/s (a single GPU may appear twice as a
        Metal/OpenCL alias, so the max — not the sum — is the honest figure), or
        ``None`` if no speed line was found.
    """
    rates: list[float] = []
    for value, unit in _SPEED_RE.findall(text):
        rates.append(float(value.replace(",", "")) * _UNIT[unit])
    return max(rates) if rates else None


def human_duration(seconds: float) -> str:
    """
    Format a duration in seconds as a compact human string (s/m/h/d/y).

    Parameters
    ----------
    seconds : float
        Duration in seconds.

    Returns
    -------
    str
        e.g. ``"20.6 min"``, ``"1.4 days"``, ``"2.6k years"``.
    """
    minute, hour, day, year = 60, 3600, 86400, 86400 * 365.25
    if seconds < minute:
        return f"{seconds:.1f} sec"
    if seconds < hour:
        return f"{seconds / minute:.1f} min"
    if seconds < day:
        return f"{seconds / hour:.1f} hours"
    if seconds < year:
        return f"{seconds / day:.1f} days"
    years = seconds / year
    if years >= 1000:
        return f"{years / 1000:.1f}k years"
    return f"{years:.1f} years"


def crack_time_table(rate: float) -> list[tuple[str, int, str]]:
    """
    Build a crack-time table for :data:`KEYSPACES` at a given hash rate.

    Parameters
    ----------
    rate : float
        Candidates tested per second (H/s).

    Returns
    -------
    list[tuple[str, int, str]]
        ``(label, candidates, human_time_to_exhaust)`` rows. The time is for
        exhausting the whole keyspace; on average a random password is found in
        about half that.
    """
    return [(label, n, human_duration(n / rate)) for label, n in KEYSPACES]


def format_report(rate: float) -> str:
    """Render the human-readable benchmark summary + crack-time table."""
    lines = [
        f"WPA (hashcat -m {HASHCAT_MODE}) rate: {rate:,.0f} H/s",
        f"  = {rate * 60:,.0f}/min · {rate * 3600:,.0f}/hour · "
        f"{rate * 86400:,.0f}/day",
        "",
        "Time to exhaust a keyspace at this rate "
        "(a random password is found in ~half):",
    ]
    for label, n, human in crack_time_table(rate):
        lines.append(f"  {label:<32} {n:>22,}  {human}")
    lines.append("")
    lines.append(
        "Takeaway: dictionaries and structured guesses (PINs, phones, dates) fall "
        "fast; random 8+ char passwords are infeasible. Speed comes from a smarter "
        "attack, not more GPU flags — hashcat already saturates the GPU on PBKDF2."
    )
    return "\n".join(lines)


def run_benchmark() -> int:
    """
    Run hashcat's mode-22000 benchmark, then print wifikit's crack-time report.

    Returns
    -------
    int
        Process exit code (0 on success; 1 if hashcat is missing or unparsable).
    """
    if not shutil.which("hashcat"):
        print("hashcat not found — install it first: brew install hashcat")
        return 1
    print(f"Benchmarking hashcat -m {HASHCAT_MODE} (WPA) on the GPU… ", flush=True)
    # Stream hashcat's own output so the user sees the live benchmark, while we
    # capture it to parse the rate afterwards.
    captured: list[str] = []
    proc = subprocess.Popen(
        ["hashcat", "-b", "-m", str(HASHCAT_MODE)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        captured.append(line)
        if line.startswith("Speed.") or "Hash-Mode" in line:
            print("  " + line.rstrip())
    proc.wait()

    rate = parse_hashrate("".join(captured))
    if rate is None:
        print("Could not parse a hash rate from hashcat's output.")
        return 1
    print()
    print(format_report(rate))
    return 0
