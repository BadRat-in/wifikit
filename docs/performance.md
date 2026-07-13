# Performance & GPU

How fast is the crack step, and where does the GPU fit in? The capture side of
wifikit is trivial (a few KB over a 115200-baud serial link); the compute cost is
entirely in **cracking the WPA handshake/PMKID with `hashcat -m 22000`**, which is
GPU-bound. This page has real measured numbers and how to reproduce them.

> ⚠️ **Authorized-use only.** Use these estimates to reason about the strength of
> networks you own or are permitted to test — see [capture-to-crack.md](capture-to-crack.md).

## Measure your own machine

```bash
wifikit --benchmark
```

It runs hashcat's mode-22000 benchmark on your GPU and prints the rate plus a
crack-time table derived from it. No board or capture needed.

## Reference numbers (Apple M3, 8-core GPU, Metal)

Measured with `wifikit --benchmark` (hashcat 7.1.2, mode 22000, 4095 iterations):

**Rate: ~81,000 H/s** — about **4.86 million/min**, **292 million/hour**,
**7.0 billion/day** WPA passphrase candidates.

Time to *exhaust* each keyspace at that rate (a random password is typically
found in about **half** that):

| Attack keyspace | Candidates | Time to exhaust |
| :-- | --: | :-- |
| Common wordlist (rockyou.txt) | 14,344,391 | ~3 min |
| 8-digit PIN (0-9) | 100,000,000 | ~21 min |
| 10-digit phone (0-9) | 10,000,000,000 | ~1.4 days |
| 8-char lowercase (a-z) | 208,827,064,576 | ~30 days |
| 8-char lower + digits | 2,821,109,907,456 | ~1.1 years |
| 8-char mixed-case + digits | 218,340,105,584,896 | ~85 years |
| 8-char full printable ASCII | 6,634,204,312,890,625 | ~2,600 years |

**Read this as:** dictionaries and *structured* guesses (PINs, phone numbers,
dates, `rockyou` + rules) fall in minutes to hours; a genuinely random 8+
character passphrase is infeasible. WPA's 8-char minimum is the brute-force floor.

## Is the GPU already being used? (yes)

hashcat auto-selects the fastest backend — **Metal** on Apple Silicon, **CUDA**
on NVIDIA, **OpenCL/ROCm** elsewhere. There is nothing for wifikit to switch on.
Confirm what it picked:

```bash
hashcat -I        # lists backends/devices; look for Type: GPU
```

On the M3 above this reports `Type: GPU / Name: Apple M3` under **Metal**.

## Why more GPU "tuning" doesn't speed up WPA

Mode 22000 is **PBKDF2-HMAC-SHA1 with 4095 iterations** — arithmetic-bound, so the
GPU is already saturated. Measured on the M3:

| Flags | Rate |
| :-- | :-- |
| default (auto GPU) | ~81,000 H/s |
| `-O -w 4` (optimized kernels, max workload) | ~76,800 H/s (**no gain**) |

`-O` (optimized kernels) also **caps candidate length** (WPA passphrases go up to
63 chars), so it can silently skip long passwords. Net: leave the flags alone.

**The real lever is the attack, not the hardware knob:**

- **Dictionary + rules** — `hashcat -m 22000 cap.hc22000 rockyou.txt -r rules/best64.rule`
- **Targeted masks** — e.g. all 10-digit phones: `-a 3 cap.hc22000 ?d?d?d?d?d?d?d?d?d?d`
- **Known structure** — SSID-derived words, dates, or a vendor's default pattern.

A faster GPU raises the ceiling proportionally (a desktop RTX-class card is
~20–40× an M3 for this mode), but the *strategy* is what turns "2,600 years" into
"3 minutes."

## Where capture time goes (for completeness)

Capture is not compute-bound. A PMKID is ~kilobytes; the limiting factors are
whether a client (re)associates during the window and the 115200-baud link, not
the CPU/GPU. See [capture-to-crack.md](capture-to-crack.md) and
[architecture.md](architecture.md).
