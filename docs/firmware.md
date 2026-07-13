# Firmware

What firmware runs on the board wifikit drives, how the correct build is
flashed, the one feature that makes SD-free capture possible, and the
(optional, not required) directions a future firmware could take.

> ⚠️ **Authorized-use only.** wifikit and any firmware it drives are for
> security testing and education on networks you **own** or have **explicit
> written permission** to test.

## What runs today

wifikit drives **stock [ESP32 Marauder][marauder] v1.13.0** by
[justcallmekoko][jcmk]. The firmware does all of the WiFi radio work —
scanning, deauthentication, and sniffing 802.11 frames — and exposes a text
command line over USB serial. wifikit only **drives** that command line; it
does **not** vendor, patch, or fork the firmware. The board stays on the
official upstream binaries so you can update it from Marauder's own releases at
any time.

Everything wifikit does is host-side: it sends Marauder commands, parses the
replies into live tables, and reassembles streamed captures. See
[architecture.md](architecture.md) for how the host code is layered.

## The right build for a classic ESP32-WROOM-32

Marauder ships many firmware variants, and picking the wrong one is the single
most common flashing mistake. For a bare **classic ESP32-WROOM-32** (chip ID
0), the correct combination is:

- the **`old_hardware`** application build, plus
- the **`MarauderV4`** bootloader / partition set.

The `flipper` build, **despite its name**, targets the ESP32-**S2** — flashing
it onto a classic WROOM-32 fails with `Unexpected chip ID`. When in doubt,
`old_hardware` is the classic-ESP32 answer.

### Flash offsets

`wifikit-flash` writes four images at the offsets Marauder expects (from
`src/wifikit/flash.py`):

| Image | Offset | Source |
| :-- | :-- | :-- |
| `esp32_marauder.ino.bootloader.bin` | `0x1000` | `FlashFiles/MarauderV4/` |
| `esp32_marauder.ino.partitions.bin` | `0x8000` | `FlashFiles/MarauderV4/` |
| `boot_app0.bin` | `0xE000` | `FlashFiles/MarauderV4/` |
| `*old_hardware.bin` (application) | `0x10000` | latest GitHub release asset |

`wifikit-flash` **fetches these from the official release / repository at flash
time** — the binaries are never vendored into wifikit (they are upstream's to
distribute). The bootloader, partitions, and `boot_app0` come from the repo's
`FlashFiles/MarauderV4` path; the application is the latest release asset whose
name ends in `old_hardware.bin`.

Flash and talk to the board at **115200 baud**. Some USB-UART chips fail a
mid-session jump to higher rates (`Unable to verify flash chip connection`), so
115200 is the safe default for both flashing and the live session. See
[usage.md](usage.md) to run the flasher and open the UI, and
[troubleshooting.md](troubleshooting.md) if a flash stalls.

## The key enabling feature: `-serial` pcap streaming

The reason wifikit needs **no microSD card** is a single stock-firmware
feature: Marauder's **`-serial`** flag streams the **raw pcap bytes** out USB
(UART0) — the same bytes it would otherwise write to an SD file. Because the
ESP32 is already tethered to the host over USB, that stream is all we need to
reassemble a `.pcap` on the Mac.

An earlier note in this project claimed stock Marauder could only emit
*counters* over serial; that was a run *without* `-serial` (and/or with
`SavePCAP` off). Verified against the v1.13.0 source, the real behaviour is:

- **`CommandLine.cpp:1369`** — `-serial` is parsed into `save_serial`, a
  **universal flag** valid for all scan/attack commands (*"Dump pcap/log to
  serial too"*).
- **`Buffer.cpp:152-154`** — the stream is delimited by the string markers
  **`[BUF/BEGIN]`** and **`[BUF/CLOSE]`**.
- **`Buffer.cpp:172`** — `Serial.write(...)` emits the **raw pcap bytes** (the
  same bytes destined for the SD file) out UART0.
- **`Buffer.cpp:98-102`** — the serial path is **gated by the `SavePCAP`
  setting**; if `SavePCAP` is false, streaming is forced off regardless of
  `-serial`.

So the recipe is: enable pcap saving once (`settings -s SavePCAP true`), then
add `-serial` to any capture (e.g. `sniffpmkid -c 3 -serial`). The host reads
USB at 115200, keeps the bytes between each marker pair, and writes a `.pcap`.
The full workflow — including converting to `hc22000` and cracking — is in
[capture-to-crack.md](capture-to-crack.md).

## Optional future firmware track (NOT required)

> Everything in this section is a **learning / experimentation track only**.
> Stock Marauder's `-serial` path above already delivers SD-free capture, so
> **none of this is needed** to complete the scan → capture → crack loop.

A from-scratch **custom sniffer firmware** could filter frames *on-device* and
stream only the interesting ones, instead of streaming every captured buffer.
The design is straightforward:

```
ESP32 (custom sniffer FW)              Mac (wifikit)
─────────────────────────              ─────────────
promiscuous RX on channel N            reads framed serial
  → filter in the RX callback:         → deframes / validates
      • EAPOL (EtherType 0x888e)       → writes .pcap AND/OR
      • RSN PMKID in assoc / M1        → assembles hc22000 line
      • one beacon (for the SSID)      → hands to hashcat
  → frame over USB (COBS/length) ─────►
```

On-device it would enable promiscuous mode
(`esp_wifi_set_promiscuous` + `esp_wifi_set_promiscuous_rx_cb`), match data
frames whose LLC/SNAP payload is EAPOL (`AA AA 03 00 00 00 88 8E`) plus
association frames carrying an RSN PMKID and one beacon per target, then send
each kept frame length-prefixed (COBS or SLIP so boundaries survive) over the
UART. The payoff is less serial traffic and less host-side filtering — but for
normal use it buys nothing over stock `-serial`, which already works and is
hardware-verified.

### The from-scratch Rust consideration

The maintainer is weighing writing firmware **from scratch in Rust** for the
classic ESP32, purely as a learning exercise. An honest reading of the
constraints (from [CAPTURE_STREAMING.md](../CAPTURE_STREAMING.md)):

- **RAM is fine** for a `no_std` build on **esp-hal** + **esp-wifi**. A
  handshake/PMKID is kilobytes, not megabytes.
- The **WiFi MAC/PHY is a closed Espressif blob**. `esp-wifi` *wraps* that
  blob; it **cannot be reimplemented**. Any Rust firmware still links the same
  proprietary radio blob — there is no pure-Rust 802.11 stack for this part.
- **Raw-frame injection / deauth TX is the immature part** of `esp-wifi`
  today. **Receive / promiscuous is more usable than transmit**, so a passive
  sniffer is far more tractable in Rust than an injection/deauth attacker.
- The classic ESP32 is **Xtensa**, so it needs the **`espup`** toolchain (a
  patched Rust). A **RISC-V** part (ESP32-**C3** / **C6**) would use upstream
  Rust directly and is the friendlier target if starting fresh.

Crucially, this is a **decoupled learning track**. wifikit's host side is
**capture-source-agnostic** (see [architecture.md](architecture.md)): it just
consumes pcap-framed bytes over serial. So **any** firmware — stock Marauder
today, a Rust or ESP-IDF sniffer later — that streams pcap-framed bytes over
the UART plugs into the same host code **unchanged**. The Rust experiment can
be pursued independently without touching wifikit.

## References

- **Marauder firmware:** [justcallmekoko/ESP32Marauder][marauder] (v1.13.0) —
  the firmware wifikit drives.
- **`-serial` pcap streaming (verified in v1.13.0 source):**
  `CommandLine.cpp:1369` (`-serial` → `save_serial`),
  `Buffer.cpp:98-102` (`SavePCAP` gate),
  `Buffer.cpp:152-154` (`[BUF/BEGIN]` / `[BUF/CLOSE]` markers),
  `Buffer.cpp:172` (`Serial.write` of raw pcap bytes).
- **ESP-IDF promiscuous mode:** `esp_wifi_set_promiscuous`,
  `esp_wifi_set_promiscuous_rx_cb`.
- **Frame identifiers:** EAPOL over 802.11 = LLC/SNAP `AA AA 03 00 00 00` +
  EtherType `0x88 8E`; PMKID = RSN PMKID KDE in the AP's first EAPOL-Key (M1).
- **Rust-on-ESP32 track:** [esp-hal][esp-hal], [esp-wifi][esp-wifi], and
  [espup][espup] (the Xtensa toolchain for the classic ESP32).

[marauder]: https://github.com/justcallmekoko/ESP32Marauder
[jcmk]: https://github.com/justcallmekoko
[esp-hal]: https://github.com/esp-rs/esp-hal
[esp-wifi]: https://github.com/esp-rs/esp-hal/tree/main/esp-wifi
[espup]: https://github.com/esp-rs/espup
