# Architecture

How wifikit is put together and why. wifikit is a **host-side driver**: it owns a
serial link to an ESP32 running Marauder, translates the firmware's text CLI into
structured data, and presents it through two front-ends (a TUI and a CLI) that
share one transport and one parser.

> ⚠️ **Authorized-use only.** Operate solely on networks you own or may lawfully
> test.

## Module map

```
src/wifikit/
  session.py   # serial transport: port auto-detect + threaded reader/writer
  marauder.py  # firmware knowledge: command set + list-output parsers
  capture.py   # SD-free capture: demux Marauder's -serial pcap stream on the host
  cli.py       # argparse entry: REPL (--cli), one-shot (--exec), capture (--capture)
  tui.py       # Textual dashboard: tables, actions, capture worker, Crack tab
  flash.py     # wifikit-flash: fetch the correct build + esptool write-flash
```

Each layer has one job, and dependencies flow **downward** only:

- **`session.py`** knows nothing about Marauder — just bytes in/out of a serial
  port. It auto-detects the board by USB-UART chip and runs a background reader
  thread so streaming firmware output never blocks the UI.
- **`marauder.py`** is the *only* file that knows Marauder's text formats. If the
  firmware's output changes, this is the one place to touch. It holds the command
  list and the parsers (`parse_list_line` for APs, `parse_station_lines` for
  stations).
- **`capture.py`** knows the `-serial` pcap wire format (the `[BUF/BEGIN]…
  [BUF/CLOSE]` framing) and reassembles a `.pcap` on the host.
- **`cli.py`** and **`tui.py`** are the two front-ends. They depend on the three
  layers above but not on each other.

## Data flow

```
ESP32 ──USB serial──► session.py (reader thread) ──► on_data(text) ──► queue
                                     │                                     │
                                     └─ on_raw(bytes) ─► capture parser    ▼
                                                                      UI timer drains
                                                                      queue on the UI
                                                                      thread ─► marauder
                                                                      parsers ─► tables
host command ◄── session.send() ◄── tx()/action ◄── keypress / menu / CLI arg
```

1. Bytes arrive on the reader thread. Two taps fire: `on_data` gets **decoded,
   sanitized text** (for the console/parsers); `on_raw` gets **raw bytes** (for
   binary pcap capture — see below).
2. The TUI drains queued text on a **UI-thread timer** (Textual requires all
   widget mutation on one thread), splits it into lines, and hands each to the
   Marauder parsers, which update the AP and Station tables.
3. User actions (hotkeys, the Actions menu, CLI flags) turn into Marauder
   commands and go out through `session.send()`.

### Threading model

Serial I/O runs on a background thread in `Esp32Session`; the UI never blocks on
it. The thread hands data to callbacks; the TUI's callback just enqueues text and
a 50 ms timer moves it onto the UI thread. This is why streaming scan output
stays smooth and never garbles the interface.

## Selection model

Marauder addresses targets by the **index it prints**, so wifikit parses and
reuses exactly those indices:

- **APs:** `list -a` prints `[idx][CH:n] name rssi`; you act on one with
  `select -a <idx>`.
- **Stations:** `list -c` prints clients **grouped under their AP** (an AP header
  line, then indented `  [idx] MAC` rows). You act on one with `select -c <idx>`.
  Because station rows have a different shape and no channel/RSSI, they need a
  *stateful* parser (`parse_station_lines`), not the AP regex.

While a scan runs, the TUI polls `list -a` and `list -c` on a timer so both
tables **fill in live** (raw `scanall` output isn't indexed and can't be parsed
into selectable rows).

## The capture path (why `on_raw` exists)

Capturing a handshake/PMKID without an SD card relies on Marauder's `-serial`
flag, which streams the **raw pcap bytes** out the same UART as the text CLI,
wrapped in `[BUF/BEGIN]…[BUF/CLOSE]` markers. Those bytes are **binary** — the
text tap's `sanitize()` would destroy them. So `session.py` exposes a second
`on_raw` tap that receives untouched bytes, which `capture.py`'s
`SavePcapStreamParser` demultiplexes into a `.pcap`. The full workflow is in
[capture-to-crack.md](capture-to-crack.md).

This design keeps the host **capture-source-agnostic**: anything that streams
pcap-framed bytes over serial (stock Marauder today, a custom sniffer firmware
later) plugs into the same host code. See [firmware.md](firmware.md).

## Testing

The pure logic — Marauder output parsing, port scoring, the capture demux and
pcap frame stats — is unit-tested with **no hardware attached** (`tests/`). That
is where parsing/framing bugs would otherwise hide. Front-end wiring is smoke-
tested headlessly via Textual's test harness.
