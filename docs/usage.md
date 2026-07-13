# Usage

How to install wifikit, flash the board, and drive it from the TUI or CLI.
For the full capture-and-crack walkthrough see
[capture-to-crack.md](capture-to-crack.md); for the design see
[architecture.md](architecture.md).

> ⚠️ **Authorized-use only.** wifikit is for security testing and education on
> networks you **own** or have **explicit written permission** to test.
> Deauthentication and handshake capture affect real users — never run them
> against third parties.

## Install

Requires **Python 3.10+**. This project standardises on [uv][uv].

```bash
uv tool install wifikit          # once published to PyPI — global command
```

Or run straight from a clone:

```bash
git clone https://github.com/BadRat-in/wifikit && cd wifikit
uv sync                          # create the venv + install deps
uv run wifikit                   # run without installing globally
```

Every command below is written as `wifikit …`; from a clone, prefix it with
`uv run` (e.g. `uv run wifikit --cli`).

## Flash the ESP32

`wifikit-flash` downloads the correct classic-ESP32 Marauder build (fetched from
the official release — nothing is vendored here) and writes it with `esptool`.

```bash
wifikit-flash            # auto-detect port, flash at a safe 115200 baud
wifikit-flash --erase    # wipe flash first, then write
wifikit-flash --baud 115200          # override the flash baud rate
wifikit-flash --port /dev/cu.usbserial-XXXX   # skip auto-detect
```

| Flag       | Default    | Purpose                                    |
| :--------- | :--------- | :----------------------------------------- |
| `--port`   | auto       | Serial device (auto-detected by USB-UART). |
| `--baud`   | `115200`   | Flash baud; safe for CP210x/CH340 chips.   |
| `--erase`  | off        | Fully erase flash before writing.          |

A classic **ESP32-WROOM-32** uses Marauder's **`old_hardware`** build; the
`flipper` build is for the **ESP32-S2** (a different chip, fails with `Unexpected
chip ID`) — `wifikit-flash` picks the right one for you. More detail lives in
[firmware.md](firmware.md).

## Launch

```bash
wifikit                                 # TUI (the default everyday interface)
wifikit --cli                           # line-based REPL instead of the TUI
wifikit --exec "scanall" --timeout 15   # one-shot: send, print output, exit
wifikit --list-ports                    # list candidate serial ports and exit
wifikit --port /dev/cu.usbserial-XXXX   # target a specific device
wifikit --no-reset                      # don't reset the board on connect
wifikit --demo                          # TUI with sample data, no board needed
```

`--timeout` (default `6`) is how long `--exec` reads before exiting.
`--port` and `--no-reset` apply to every mode.

## The TUI

The default interface: a single-screen dashboard with four tabs.

| Tab          | What it shows                                                |
| :----------- | :---------------------------------------------------------- |
| **Targets**  | Discovered APs (`list -a`) — one selectable row per AP.     |
| **Stations** | Clients grouped by AP (`list -c`) — select one to deauth.   |
| **Console**  | Raw Marauder output + an input box to send any command.     |
| **Crack**    | Runs `hashcat`/`aircrack-ng` on your machine, streamed live.|

Both tables **auto-populate live during a scan** — wifikit polls `list -a` and
`list -c` on a timer, so rows appear without a keypress (and refresh once more
when the scan stops).

### Hotkeys

| Key      | Action                                                     |
| :------- | :--------------------------------------------------------- |
| `s`      | Scan (`scanall`).                                          |
| `x`      | Stop scanning.                                             |
| `r`      | Refresh the target and station lists.                      |
| `a` / ↵  | Open the Actions menu for the highlighted target.          |
| `d`      | Deauth the highlighted AP.                                 |
| `p`      | Capture PMKID from the highlighted AP.                     |
| `c`      | Capture (alias of `p` — PMKID).                            |
| `Ctrl+R` | Reconnect the serial session.                              |
| `q`      | Quit.                                                       |

### Rows and the Actions menu

- **Enter on an AP row** (Targets tab) opens the **Actions** menu for that AP.
- **Enter on a Station row** (Stations tab) deauths *that specific client*.

The Actions menu offers:

- **Select as target** — `select -a <idx>`.
- **Deauth (force disconnect)**.
- **Capture PMKID → Mac (.pcap)**.
- **Capture handshake → Mac (.pcap)**.
- **Set radio to this channel**.
- **Stop all activity**.

Capturing is **SD-free**: the pcap streams over USB straight into `./captures`,
then the **Crack** tab is pre-filled with a ready hashcat command. See
[capture-to-crack.md](capture-to-crack.md) for the full loop.

## The REPL (`--cli`)

A line-based console with local echo, history (`~/.wifikit_history`), and
tab-completion of Marauder commands — a painless replacement for `screen`, which
Marauder's non-echoing CLI makes miserable. Type any Marauder command, or one of
these meta-commands (handled locally, never sent to the board):

| Meta-command        | Effect                                             |
| :------------------ | :------------------------------------------------- |
| `:help`             | Show the meta-command list.                        |
| `:reset`            | Reboot the board.                                  |
| `:ports`            | List candidate serial ports.                       |
| `:log <file>`       | Tee session output to a file.                      |
| `:log off`          | Stop logging.                                      |
| `:capture`          | Print the standalone `wifikit --capture` command.  |
| `:quit`             | Exit (also `:q`, or Ctrl-D).                        |

`:capture` doesn't run inline (a capture needs its own serial reader); it prints
the exact `wifikit --port … --capture --channel …` command to run instead.

## SD-free capture from the CLI

Stream a pcap over USB without an SD card:

```bash
wifikit --capture --channel 3                       # PMKID, 20s (defaults)
wifikit --capture --channel 3 --seconds 30          # longer window
wifikit --capture --channel 3 --mode handshake      # handshake instead of PMKID
wifikit --capture --channel 3 --out captures/lab.pcap
```

| Flag        | Default             | Purpose                                  |
| :---------- | :------------------ | :--------------------------------------- |
| `--channel` | *(required)*        | AP's channel to capture on.              |
| `--seconds` | `20`                | How long to stream.                      |
| `--mode`    | `pmkid`             | `pmkid` or `handshake`.                  |
| `--out`     | `captures/<ts>.pcap`| Output `.pcap` path.                     |

It writes to `captures/` and reports frames plus the EAPOL count; when EAPOL is
present it converts to an `hc22000` line via `hcxpcapngtool`. No EAPOL means
nothing crackable was captured — a PMKID/handshake needs a client
(re)association, usually via a brief authorised deauth of a client on your own
AP. Full loop: [capture-to-crack.md](capture-to-crack.md).

## Everyday flow

1. **Flash** the board once — `wifikit-flash`.
2. **Launch** the TUI — `wifikit`.
3. **Scan** — press `s`; the Targets and Stations tables fill in live. Press
   `x` to stop.
4. **Pick an AP** — highlight its row, press **Enter** → **Deauth** briefly to
   force a client to reconnect.
5. **Capture** — **Enter** → **Capture PMKID/handshake** (or `p`); the pcap
   lands in `./captures` and the Crack tab is pre-filled.
6. **Crack** — in the Crack tab, run e.g.
   `hashcat -m 22000 capture.hc22000 wordlist.txt`; output streams live.

Something not working? See [troubleshooting.md](troubleshooting.md).

[uv]: https://github.com/astral-sh/uv
