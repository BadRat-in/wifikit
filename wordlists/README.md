# Wordlists

Cracking a captured WPA handshake/PMKID with `hashcat -m 22000` is a **dictionary
attack**: hashcat hashes each candidate line and checks it against the capture.
So the crack is only as good as the wordlist you point it at.

> ⚠️ **Authorized-use only.** Use wordlists to test the strength of networks you
> own or are permitted to assess.

## What's here

| File | Committed? | Purpose |
| :-- | :-- | :-- |
| `example-passwords.txt` | ✅ yes | A tiny (~140-line) **example** of common weak WPA passphrases — enough to demo the crack flow and catch obviously weak keys. Not for real cracking. |
| `rockyou.txt`, `*.txt` (others) | 🚫 gitignored | Your **real** wordlists live here locally and are never committed (they're large, and often real password dumps). |

The repo's `.gitignore` keeps everything in this folder **out of git except**
`example-passwords.txt` and this `README.md`, so you can drop big wordlists here
without bloating the repo.

## Get a real wordlist (stays on your machine)

The classic starting point is **rockyou.txt** (~14 million real passwords):

```bash
# Download into this folder (gitignored):
curl -L -o wordlists/rockyou.txt \
  https://github.com/brannondorsey/naive-hashcat/releases/download/data/rockyou.txt

# On Kali/Parrot it ships gzipped:
#   gunzip -k /usr/share/wordlists/rockyou.txt.gz -c > wordlists/rockyou.txt
```

Bigger/《targeted》 lists: [SecLists](https://github.com/danielmiessler/SecLists)
(`Passwords/`), or generate custom ones with `crunch` / hashcat mask attacks.

## Use it

```bash
# quick demo against the example list
hashcat -m 22000 captures/mycapture.hc22000 wordlists/example-passwords.txt

# a real run
hashcat -m 22000 captures/mycapture.hc22000 wordlists/rockyou.txt

# with rules to mangle each word (much better hit rate)
hashcat -m 22000 captures/mycapture.hc22000 wordlists/rockyou.txt -r /opt/homebrew/share/hashcat/rules/best64.rule
```

In the wifikit TUI, the **Capture** action pre-fills a `hashcat` command in the
Crack tab — just point it at the wordlist you want. See
[docs/capture-to-crack.md](../docs/capture-to-crack.md) and
[docs/performance.md](../docs/performance.md) for the full loop and crack-speed
numbers.
