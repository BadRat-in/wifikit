# Troubleshooting

Common problems and fixes, in a **symptom → cause → fix** shape. If your issue
isn't here, jump to [Still stuck?](#still-stuck) at the bottom.

> ⚠️ **Authorized-use only.** Every fix below assumes you are operating on
> networks you **own** or have **explicit written permission** to test. Deauth
> and handshake capture affect real users — never run them against third
> parties.

Related guides: [usage.md](usage.md) (flashing + running the TUI/CLI),
[capture-to-crack.md](capture-to-crack.md) (the SD-free capture loop), and
[firmware.md](firmware.md) (which build runs on the board).

## Connecting to the board

### "No ESP32 serial port found"

**Symptom.** `wifikit` (or `wifikit-flash`) exits immediately with
`No ESP32 serial port found. Plug the board in, or pass --port.`

**Cause.** The board is unplugged, or its port didn't score high enough to be
auto-selected. Auto-detect ranks ports by USB-UART chip (CP210x, CH340, CH9102,
FTDI, native USB) and deliberately **rejects** Bluetooth and debug-console
ports, so nothing gets picked by accident.

**Fix.** Plug the board in over a **data** USB cable (some are charge-only),
then list what's visible:

```bash
wifikit --list-ports
```

If your board shows up but wasn't auto-chosen, pass it explicitly:

```bash
wifikit --port /dev/cu.usbserial-XXXX
```

### Port busy / "Resource busy" / can't open the port

**Symptom.** Opening the port fails with a *resource busy* / *could not open
port* error, or the TUI shows the port then immediately disconnects.

**Cause.** Another program already holds the serial port — a second `wifikit`
TUI, a `screen` session, the Arduino IDE serial monitor, or another
`wifikit --capture`. A serial port has exactly **one** owner at a time.

**Fix.** Close the other session (quit the other `wifikit`, exit `screen` with
`Ctrl-A K`, close the Arduino serial monitor), then reconnect. Only one program
can own the port at once.

### Garbled boot text / board not responding

**Symptom.** The Console shows mojibake, or the board stops responding to
commands after a while.

**Cause.** The USB-UART chip on a classic WROOM-32 DevKit is stable at
**115200** but **fails a mid-session baud jump** to 460800/921600 (seen as
"Unable to verify flash chip connection" when flashing, or garbage afterward).

**Fix.** Stay at the default **115200** — wifikit uses it everywhere, so don't
override it. To recover a wedged board, reboot it into the app: press
**Ctrl-R** in the TUI, or type `:reset` in the REPL.

## Flashing

### Flashing fails with "Unexpected chip ID"

**Symptom.** `wifikit-flash` (or a manual esptool run) aborts with
`Unexpected chip ID`.

**Cause.** Wrong firmware build for this chip. The Marauder **`flipper`** build,
despite the name, targets the **ESP32-S2** — not a classic WROOM-32.

**Fix.** Use `wifikit-flash`. It fetches the correct **`old_hardware`**
application plus the matching **MarauderV4** bootloader/partition table at the
right offsets, so you never pick the pair by hand:

```bash
wifikit-flash            # auto-detect port, flash at 115200
wifikit-flash --erase    # wipe flash first, then flash
```

See [firmware.md](firmware.md) for which build maps to which board.

## Capture

### Boot banner says "SD Card NOT Supported" / "Failed to mount SD Card"

**Symptom.** On boot the Marauder banner reports the SD card is missing or
failed to mount.

**Cause.** A bare DevKit has **no SD card module** — nothing to mount.

**Fix.** Nothing to fix; this is **expected and fine**. wifikit doesn't need an
SD card: capture streams the pcap over USB via Marauder's `-serial` flag instead
of writing to SD. See [capture-to-crack.md](capture-to-crack.md).

### Capture produced no pcap / 0 blobs

**Symptom.** A capture finishes but writes no `.pcap`, and the result reports
`blob_count = 0`.

**Cause.** The firmware only streams pcap bytes when **`SavePCAP`** is enabled
**and** the sniff runs with **`-serial`** — and even then there must be traffic
on the channel to capture.

**Fix.** wifikit's capture already sends `settings -s SavePCAP true` and appends
`-serial` for you, so the usual culprit is the channel. Make sure you're on the
AP's **current** channel (mesh APs hop — see below) and that there is live
traffic there.

### Capture has frames but 0 EAPOL (nothing crackable)

**Symptom.** The capture summary shows frames captured but `eapol_frames = 0`,
and no handshake to crack.

**Cause.** No client (re)associated during the capture window. Passive sniffing
only sees beacons and management frames; the crackable EAPOL key exchange
happens **when a client joins**.

**Fix.** Force a reconnect: run a **brief, authorised** deauth of a client on
**your own** AP (Actions → Deauth), then capture again. The client re-associates
and the handshake lands in the pcap.

### "hc22000 skipped" / no hashcat file produced

**Symptom.** Capture succeeds but no `.hc22000` file appears; conversion is
skipped.

**Cause.** Either `hcxpcapngtool` (from **hcxtools**) isn't installed, or the
pcap contained **no EAPOL** to convert.

**Fix.** Install the converter, and make sure the capture actually holds EAPOL
first (see the previous entry):

```bash
brew install hcxtools
```

The `.pcap` is always usable directly in Wireshark or `aircrack-ng` regardless;
`hc22000` is just the most convenient input for `hashcat -m 22000`.

## Targets & the live tables

### Target disappeared / it's on a different channel

**Symptom.** An AP you saw last session is gone, or capture on its old channel
gets nothing.

**Cause.** A mesh AP (multiple BSSIDs under one name) can **hop channels**
between sessions — the same network has been seen on ch 3, then 8, then 10.

**Fix.** Re-scan and read the channel from the **live table** each time, rather
than assuming a fixed one. wifikit's capture already uses the selected AP's live
channel.

### Table shows odd MACs like `33:33:*` or `01:00:5e:*`

**Symptom.** MAC-like entries such as `33:33:…` (IPv6) or `01:00:5e:…` (IPv4)
appear alongside real clients.

**Cause.** Those are **multicast/broadcast** addresses, not real stations.

**Fix.** Nothing to do — this is informational. wifikit already filters them out
of the Stations table, so they won't show up there as selectable clients.
(Randomized client MACs, by contrast, have `2`/`6`/`a`/`e` as the second
nibble.)

### Your own Wi-Fi / internet blips during testing

**Symptom.** The host's own connection drops briefly while you scan, capture, or
deauth.

**Cause.** Sniffing or capturing on the **same channel** your host uses can
momentarily perturb its link, and a deauth will definitely disrupt whatever it
targets.

**Fix.** Expected — it self-recovers on its own. Just avoid deauthing the AP
your host relies on to stay online.

## Still stuck?

Open the **Console** tab (or `wifikit --cli`) to read the **raw firmware
output** — the banner, errors, and command replies verbatim are the best clue to
what the board is actually doing. For a one-shot board-state dump, run:

```bash
wifikit --exec "info"
```
