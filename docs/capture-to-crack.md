# Capture → crack (no SD card)

The definitive guide to wifikit's SD-free capture loop: stream a WiFi
capture off the ESP32 over the same USB cable, then crack it on your
Mac. No microSD module, no custom firmware.

> ⚠️ **Authorized-use only.** Everything here targets networks you
> **own** or have **explicit written permission** to test. Capturing or
> cracking traffic on networks you don't control is illegal in most
> jurisdictions. See the [legal notice](../README.md#-legal--authorized-use-notice).

See also: [usage.md](usage.md) to get the board flashed and the TUI
running, [architecture.md](architecture.md) for the host-side data flow,
[firmware.md](firmware.md) for what runs on the ESP32, and
[troubleshooting.md](troubleshooting.md) when something doesn't line up.

## The idea

A bare ESP32-WROOM-32 DevKit has **no SD card**, so stock ESP32 Marauder
can't *save* a `.pcap` to disk for cracking. The usual advice is to solder
on a microSD SPI module — but you don't need one. The board is already
tethered to your Mac over USB, so instead of *storing* the capture we let
the firmware *forward* it.

Stock Marauder **v1.13.0** can stream the raw pcap bytes out the **same USB
serial link** you already use to drive it, gated behind one flag and one
setting:

- the `-serial` flag on any scan/attack command, and
- the `SavePCAP` setting turned on.

No SD card. No custom firmware. This is **verified against the firmware
source _and_ on real hardware** — on the live board a `-serial` sniff
streamed the capture, wifikit reassembled a valid pcap, and **tcpdump
decoded genuine 802.11 beacons** out of it.

## How it works under the hood

You enable pcap saving once (it persists in settings):

```
settings -s SavePCAP true
```

then run a sniff with the universal `-serial` flag, for example:

```
sniffpmkid -c 3 -serial      # PMKID on channel 3
sniffpwn -serial             # WPA 4-way handshake sniff
```

With both in place, the firmware writes the **exact pcap byte buffer** —
the same bytes it would otherwise write to an SD file — out UART0, wrapped
in ASCII markers:

```
…console text…  [BUF/BEGIN]  <raw pcap bytes>  [BUF/CLOSE]  …console text…
```

On the host, wifikit's `SavePcapStreamParser` (in
[`src/wifikit/capture.py`](../src/wifikit/capture.py)) demultiplexes those
blobs out of the interleaved serial stream — tolerating console text mixed
in and markers/blobs split across reads — and concatenates them into a
valid `.pcap` (libpcap link-type **105**, `IEEE802_11`).

### Where this lives in the firmware

Confirmed in the `justcallmekoko/ESP32Marauder` v1.13.0 source:

| Location | What it does |
| :-- | :-- |
| `CommandLine.cpp:1369` | Sets `save_serial` from the `-serial` flag — *"Dump pcap/log to serial too, valid for all scan/attack commands"*, so it's universal. |
| `Buffer.cpp:152-154` | Frames the stream with the `[BUF/BEGIN]` / `[BUF/CLOSE]` markers. |
| `Buffer.cpp:172` | `Serial.write(buf, …)` — writes the **raw pcap bytes** out UART0 (the same bytes an SD file would get). |
| `Buffer.cpp:98-102` | The `SavePCAP` gate: if `SavePCAP` is false, serial streaming is forced off regardless of `-serial`. |

An earlier note in this project claimed stock Marauder could only emit
*counters* over serial. That was wrong — it was a run *without* `-serial`
(and/or with `SavePCAP` off), which is exactly the counters-only telemetry
the firmware emits in that case.

## Two ways to run it

### TUI (recommended)

1. Scan (`s`), let the target table fill in, and move the cursor to the AP.
2. Trigger a capture — press `c`, or `a`/Enter to open **Actions** and
   choose **Capture (stream handshake/PMKID to Mac)**. It's a single
   action, not a PMKID/handshake choice: `sniffpmkid -serial` records the
   PMKID *and* any 4-way-handshake EAPOL frames into one pcap, and
   `hcxpcapngtool` extracts whichever actually landed.
3. The pcap lands in **`./captures/`** and the **Crack tab** is pre-filled
   with the next command (a `hcxpcapngtool` conversion, or a ready
   `hashcat -m 22000 …` line when EAPOL was captured). To run the crack,
   switch to the **Crack tab** and **press Enter** in that pre-filled box —
   the output streams live in the tab.

The TUI taps the session's raw byte stream into the parser only for the
capture window, so binary pcap bytes never get mangled by the text CLI.

### CLI

```bash
wifikit --capture --channel N [--seconds S] [--mode pmkid|handshake] [--out PATH]
```

- `--channel N` is **required** (the target AP's channel — there is no
  sensible default).
- `--seconds S` — capture duration; default **20**.
- `--mode` — `pmkid` (default) or `handshake`.
- `--out PATH` — output path; default `captures/<timestamp>.pcap`.

Example:

```bash
wifikit --capture --channel 8 --seconds 30 --mode handshake --out captures/lab.pcap
```

The CLI prints a summary (pcap path, blob/byte counts, pcap validity, and
frame / EAPOL counts) and, when EAPOL was captured, auto-converts to
`hc22000` if `hcxtools` is installed.

## What you actually need to crack

The crackable material is tiny — kilobytes, not megabytes, which is exactly
why it's comfortable over a 115200-baud link. Both feed hashcat mode
**22000**:

- **PMKID** — a single 16-byte value derived from the AP's first EAPOL (M1)
  frame. Often **clientless**: the AP alone can yield it, no connected
  station required.
- **4-way handshake** — a few small **EAPOL** frames plus one beacon (for
  the SSID). Requires a client to authenticate.

## Honesty: capturing something crackable is traffic-dependent

**A PMKID or handshake only appears when a client (re)associates during your
capture window.** A passive capture on a quiet network commonly yields
**beacons but 0 EAPOL frames** — a perfectly valid pcap with nothing
crackable in it. This is normal and expected; it was exactly what the
hardware-verified passive runs produced.

To force the material to appear, run a brief **authorised** deauth of a
client on **your own** AP so it disconnects and reconnects:

- **Automatically:** turn on **Auto-deauth before capture** in the
  **Settings** tab. Capture then fires a deauth burst first (its length is
  the **Deauth burst (seconds)** setting) and immediately sniffs — one
  coordinated action, no separate step. This is ineffective against
  PMF/802.11w networks, which reject the deauth.
- **Manually:** open **Actions → Deauth** on the AP (or select a client in
  the **Stations** tab and press Enter to deauth just that station), then
  start the capture.
- Either way, the reconnection triggers a fresh EAPOL exchange that lands
  in your capture window.

wifikit tells you honestly whether you got anything, because it reports
`frames` and `EAPOL` counts **parsed from the pcap itself** — by scanning
each 802.11 frame for the LLC/SNAP + EtherType-`0x888E` EAPOL signature —
**not** from the firmware's console text. (The firmware's banner prints
"PMKID"/"EAPOL" regardless of what actually landed in the capture, so those
console flags were false positives and are not trusted.) If `EAPOL: 0`,
there is nothing to crack yet — deauth and try again.

## Cracking on the host

Once you have a pcap with EAPOL frames, convert it to a hashcat `22000`
file and crack:

```bash
brew install hcxtools                          # provides hcxpcapngtool
hcxpcapngtool -o out.hc22000 out.pcap          # pcap → hc22000
hashcat -m 22000 out.hc22000 wordlists/rockyou.txt      # crack (offline, no radio)
```

wifikit **auto-converts** for you when `hcxtools` is installed *and* EAPOL
frames were captured — the CLI prints the resulting `.hc22000` path, and the
TUI pre-fills the Crack tab with the ready `hashcat -m 22000 … wordlists/rockyou.txt`
command (the wordlist comes from the **Default wordlist** setting, blank =
auto-pick). You don't have to retype anything: switch to the **Crack tab**
and **press Enter** in the pre-filled input box to launch the crack, and its
output streams live in the tab. When `hcxtools` isn't installed, it pre-fills
the `hcxpcapngtool` conversion command instead so you can run it once the
tool is on `PATH`. The `.pcap` is always usable directly in Wireshark or with
`aircrack-ng` too; `hc22000` is just the most convenient hashcat input.

The cracking itself runs entirely on your Mac — it's pure offline math
(PBKDF2-HMAC-SHA1) and needs no radio, which is why the ESP32 (a 240 MHz
MCU) never does it.

## Tip: always capture on the AP's *current* channel

A target's channel can change — a mesh network may hop channels between
sessions (the lab AP `rb_alderson` was seen on ch 3, then 8, then 10). If
you sniff the wrong channel you'll get nothing.

Always capture on the AP's **current** channel, read from `list -a` at
capture time. The TUI and CLI already do this: they use the **selected AP's
live channel** rather than a hard-coded one, so as long as you scan first
and pick the AP, the capture pins the radio to the right channel.

## End-to-end walkthrough

A full authorised loop from cold start to a cracked (or attempted) key:

1. **Scan.** Launch the TUI (`wifikit`), press `s`, and wait for the target
   table to fill in.
2. **Pick the AP.** Move the cursor onto **your own** AP. Note its channel
   in the `CH` column — the capture will use it automatically.
3. **(Optional) force a handshake.** If the network is quiet, either turn on
   **Auto-deauth before capture** in **Settings** (Capture then bursts a
   deauth before it sniffs) or open **Actions → Deauth** on the AP (or deauth
   a specific client from the Stations tab) so a client reconnects during the
   next step.
4. **Capture.** Press `c`, or use **Actions → Capture (stream
   handshake/PMKID to Mac)** — one action captures both. The pcap streams
   over USB and lands in `./captures/`. Equivalently from the CLI:

   ```bash
   wifikit --capture --channel 8 --seconds 30
   ```

5. **Check.** Read the reported `frames` / `EAPOL` counts. If `EAPOL: 0`,
   go back to step 3 and deauth again.
6. **Convert.** With EAPOL captured, wifikit auto-runs the conversion (with
   `hcxtools` installed); otherwise run it yourself:

   ```bash
   hcxpcapngtool -o captures/out.hc22000 captures/out.pcap
   ```

7. **Crack.** In the TUI's **Crack tab** the `hashcat -m 22000 …` command is
   already pre-filled — just **press Enter** in that box to run it (output
   streams live). Or run it yourself in any shell:

   ```bash
   hashcat -m 22000 captures/out.hc22000 wordlists/rockyou.txt
   ```

That's the whole loop, on one USB cable, with no SD card and no custom
firmware.
