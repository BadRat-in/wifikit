# wifikit

**A terminal UI + CLI for driving an ESP32 running the [ESP32 Marauder][marauder] firmware — for authorized WiFi security testing and learning.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![CI](https://github.com/BadRat-in/wifikit/actions/workflows/ci.yml/badge.svg)](https://github.com/BadRat-in/wifikit/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Built with Textual](https://img.shields.io/badge/built%20with-Textual-5a2ca0.svg)](https://github.com/Textualize/textual)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

`wifikit` turns the raw Marauder serial command line into a single-screen,
target-oriented dashboard. Instead of memorising commands or juggling the
multi-terminal aircrack-ng workflow (airodump here, aireplay there, aircrack in
a third window), you **scan**, **pick a target from a live table**, and act on
it from a menu or with hotkeys — then run the host-side crack from the same UI.

---

## ⚠️ Legal & authorized-use notice

This is a tool for **authorized security testing and education only**. Attacking
networks you do not own or lack **explicit written permission** to test is
illegal in most jurisdictions.

- Only use `wifikit` against **your own** networks/devices or those you are
  contractually authorized to assess.
- Deauthentication and handshake capture affect real users on a network — never
  run them against third parties.
- The authors accept **no liability** for misuse. By using this software you
  agree you are solely responsible for complying with all applicable laws.

`wifikit` is a *front-end*: it drives the already-open-source ESP32 Marauder
firmware and standard tools like `hashcat`/`aircrack-ng`. It contains no novel
attack code.

---

## Features

- 🖥️ **Textual TUI** (default): live AP table, tabbed layout, mouse + keyboard.
- 🎯 **Target-oriented**: select an AP, then Deauth / Capture PMKID / Capture
  handshake / set channel — via an Actions menu (Enter or right-click) or hotkeys.
- 👥 **Stations tab**: clients grouped by AP (via Marauder's `list -c`), populated
  live during a scan; select a station to deauth it directly.
- 📥 **SD-free capture**: `wifikit --capture --channel N` streams the pcap over
  USB (Marauder's `-serial`) into `captures/` — no microSD card needed.
- 🔌 **Auto-detects** the ESP32's serial port (by USB-UART chip), ignoring
  Bluetooth/debug ports.
- ⌨️ **Nice REPL** (`--cli`): local echo, history and tab-completion — a painless
  replacement for `screen`, which Marauder's non-echoing CLI makes miserable.
- 🤖 **Scriptable** one-shot mode (`--exec "scanall"`).
- 🧨 **Integrated cracking**: run `hashcat`/`aircrack-ng` in a Crack tab with live
  streaming output — scan → deauth → capture → crack in one place.
- ⚡ **One-command flashing** of the correct classic-ESP32 build (`wifikit-flash`).

```
 ● /dev/cu.usbserial-….   |   SCANNING   |   APs: 4   | [s]can [x]stop [r]efresh
┌ Targets ─┬ Console ─┬ Crack ─────────────────────────────────────────────────┐
│ Idx  CH   ESSID / BSSID          RSSI                                          │
│  0    3   rb_alderson            -72   ← cursor; press Enter for Actions       │
│  1    3   8e:86:dd:a0:8b:68      -73                                           │
│  2    3   rb_alderson            -84                                           │
└──────────────────────────────────────────────────────────────────────────────┘
 s Scan  x Stop  r Refresh  a Actions  d Deauth  p PMKID  ^r Reconnect  q Quit
```

## Hardware

- An **ESP32** board (developed and tested on a classic **ESP32-WROOM-32**
  DevKit) flashed with **ESP32 Marauder**.
- A **microSD module** (SPI) is **optional** — capture streams over USB via
  Marauder's `-serial`, so an SD card is only needed for *untethered* capture
  (running the board off the host).

## Install

Requires Python 3.10+. Using [uv][uv] (recommended):

```bash
uv tool install wifikit          # once published to PyPI
# or run from a clone:
uv venv && uv pip install -e .
```

With pipx:

```bash
pipx install wifikit
```

## Flash the ESP32

`wifikit-flash` downloads the **correct classic-ESP32 build** (the `old_hardware`
app plus the matching bootloader/partition table) and writes it. It does **not**
vendor Marauder's binaries — they are fetched from the official release.

```bash
wifikit-flash            # auto-detect port, flash at a safe 115200 baud
wifikit-flash --erase    # wipe flash first
```

> Note: the Marauder `flipper` build is for the ESP32-**S2** and will **not** run
> on a classic WROOM-32 (`Unexpected chip ID`). `wifikit-flash` picks the right
> one for you.

## Usage

```bash
wifikit                       # launch the TUI (auto-detect the board)
wifikit --cli                 # line-based REPL instead of the TUI
wifikit --exec "scanall" --timeout 15   # one-shot, print output, exit
wifikit --capture --channel 3 # stream a pcap over USB into captures/ (no SD)
wifikit --list-ports          # show candidate serial ports
```

`--capture` also accepts `--seconds S`, `--mode pmkid|handshake`, and `--out
PATH`. It enables Marauder's `SavePCAP`, sniffs with `-serial`, and reassembles
the streamed `.pcap` on the host.

**TUI hotkeys:** `s` scan · `x` stop · `r` refresh list · `a`/Enter actions ·
`d` deauth selected · `p` PMKID selected · `Ctrl-R` reconnect · `q` quit. The
**Stations** tab lists clients grouped by AP and fills live during a scan.

### The capture → crack loop (on *your own* network)

No SD card required — the capture streams over USB straight to your Mac.

1. `s` to scan, `x` to stop — the table fills live from Marauder's `list -a`.
2. Highlight your AP, press **Enter** → **Capture (stream to Mac)**, or from the
   CLI run `wifikit --capture --channel N` (add `--seconds S`, `--mode
   pmkid|handshake`, `--out PATH`).
3. **Deauth** briefly to force a client to reconnect (generates a handshake).
4. `wifikit` enables Marauder's `SavePCAP`, runs the sniff with `-serial`, and
   **reassembles the streamed `.pcap` into `captures/`** — then converts it via
   `hcxpcapngtool` to an `hc22000` line.
5. In the **Crack** tab, run e.g.
   `hashcat -m 22000 capture.hc22000 wordlist.txt` — output streams live.

## How it works

```
              ┌────────────── wifikit (Python) ──────────────┐
  ESP32  <──USB serial──>  session.py  ──>  tui.py / cli.py
  Marauder                 (threaded I/O)     (UI + parsing)
                                   │
                              marauder.py  (command set + `list` parser)
                                   │
                              flash.py  (esptool + firmware fetch)
```

- `session.py` — port auto-detect + a threaded serial reader/writer.
- `marauder.py` — the firmware's command set and `list` parser (APs + stations).
- `capture.py` — demuxes Marauder's `-serial` pcap stream into a `.pcap` and
  (optionally) converts it to `hc22000` via `hcxpcapngtool`.
- `cli.py` / `tui.py` — the two front-ends (REPL and Textual dashboard).
- `flash.py` — one-command flashing via `esptool`.

## Development

```bash
uv sync                       # create venv + install deps (incl. dev group)
uv run ruff check .           # lint
uv run ruff format .          # format
uv run pytest                 # tests (parser/port logic run without hardware)
```

Please read [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). Security reports: see [SECURITY.md](SECURITY.md).

## Acknowledgements & credits

`wifikit` stands entirely on the shoulders of these projects — please star and
support them:

- **[ESP32 Marauder][marauder]** by **[justcallmekoko][jcmk]** — the firmware
  that does all the actual WiFi/BLE work. `wifikit` is only a host-side driver
  for it; the firmware binaries it flashes are built and distributed by that
  project.
- **[Textual][textual]** & **Rich** by Textualize — the TUI framework.
- **[pyserial][pyserial]** — serial transport.
- **[esptool][esptool]** by Espressif — flashing.
- **[prompt_toolkit][ptk]** — the REPL experience.
- **[hashcat][hashcat]** and **[aircrack-ng][aircrack]** — the cracking tools the
  Crack tab drives.

## License

[MIT](LICENSE) © 2026 Ravindra Singh. The ESP32 Marauder firmware is the property
of its respective authors under its own license.

[marauder]: https://github.com/justcallmekoko/ESP32Marauder
[jcmk]: https://github.com/justcallmekoko
[textual]: https://github.com/Textualize/textual
[pyserial]: https://github.com/pyserial/pyserial
[esptool]: https://github.com/espressif/esptool
[ptk]: https://github.com/prompt-toolkit/python-prompt-toolkit
[hashcat]: https://hashcat.net/hashcat/
[aircrack]: https://www.aircrack-ng.org/
[uv]: https://github.com/astral-sh/uv
