# wifikit documentation

`wifikit` is a Python **TUI + CLI** that drives an **ESP32** flashed with the
[ESP32 Marauder][marauder] firmware, turning its raw serial command line into a
single-screen, target-oriented dashboard: **scan → pick a target → deauth /
capture → crack**. It is a *host-side driver only* — the ESP32 does the WiFi
radio work, and your Mac/PC does the cracking.

> ⚠️ **Authorized-use only.** wifikit is for security testing and education on
> networks you **own** or have **explicit written permission** to test. See the
> [legal notice](../README.md#-legal--authorized-use-notice) in the README.

## The mental model

The one idea that explains every design decision: **the ESP32 is the radio, the
host is the brain.**

- The **ESP32** can scan, deauthenticate, and sniff 802.11 frames, but it
  **cannot crack WPA** (PBKDF2-HMAC-SHA1 is far too heavy for a 240 MHz MCU).
- The **host** (Mac/PC) does the cracking — `hashcat -m 22000` / `aircrack-ng` —
  which is pure offline math and needs no radio.
- They talk over **one USB serial cable at 115200 baud**. wifikit owns that link:
  it sends firmware commands, parses the replies into live tables, and — the key
  capability — **streams captured packets back over the same cable** so no SD
  card is required.

```
   ┌───────────── ESP32 (Marauder firmware) ─────────────┐        ┌──── Host (wifikit) ────┐
   │  scan · deauth · sniff (radio)                       │  USB   │  tables · actions ·    │
   │  streams pcap over serial with the -serial flag  ────┼───────►│  pcap assembly · crack │
   └──────────────────────────────────────────────────────┘ 115200└────────────────────────┘
```

## Start here

| If you want to… | Read |
| :-- | :-- |
| Understand the codebase and data flow | [architecture.md](architecture.md) |
| Flash the board and run the TUI/CLI | [usage.md](usage.md) |
| Capture a handshake/PMKID and crack it (no SD card) | [capture-to-crack.md](capture-to-crack.md) |
| Know what firmware runs and future firmware plans | [firmware.md](firmware.md) |
| Fix a problem (no port, no frames, etc.) | [troubleshooting.md](troubleshooting.md) |

New to the project? Skim [architecture.md](architecture.md) for the model, then
follow [usage.md](usage.md) to get the TUI running, then walk the
[capture-to-crack](capture-to-crack.md) loop.

## What's in the box

- **Textual TUI** (default) — a live AP table, a Stations table, per-target
  actions (deauth / capture / channel), and an integrated Crack tab.
- **CLI** — a nicer REPL than `screen` (`--cli`), one-shot scripting (`--exec`),
  and SD-free capture (`--capture`).
- **`wifikit-flash`** — one command to flash the correct classic-ESP32 build.

## Credits

wifikit stands on [ESP32 Marauder][marauder] by
[justcallmekoko][jcmk] (the firmware that does the actual WiFi work),
[Textual][textual], [pyserial][pyserial], [esptool][esptool],
[hashcat][hashcat], and [hcxtools][hcxtools]. Please star and support them.

[marauder]: https://github.com/justcallmekoko/ESP32Marauder
[jcmk]: https://github.com/justcallmekoko
[textual]: https://github.com/Textualize/textual
[pyserial]: https://github.com/pyserial/pyserial
[esptool]: https://github.com/espressif/esptool
[hashcat]: https://hashcat.net/hashcat/
[hcxtools]: https://github.com/ZerBea/hcxtools
