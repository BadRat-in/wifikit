# Security Policy

## Scope

`wifikit` is a host-side driver for the ESP32 Marauder firmware and standard
cracking tools. Vulnerabilities in **this project** (e.g. unsafe handling of
serial input, command injection in the Crack tab, dependency issues) are in
scope. Vulnerabilities in the Marauder firmware, `hashcat`, `aircrack-ng`, or
`esptool` should be reported to those upstream projects.

## Reporting a vulnerability

Please **do not** open a public issue for security reports. Instead, use GitHub's
private **[Report a vulnerability](https://github.com/BadRat-in/wifikit/security/advisories/new)**
advisory feature, or email the maintainer at `ravindra@budgurjar.org`.

Include a description, reproduction steps, and impact. We aim to acknowledge
reports within a few days.

## Responsible use

This tool is for authorized security testing and education only. Reports that
amount to "it can be used to attack networks" are not vulnerabilities — that is
the documented, intended, and legally-gated purpose of the tool.
