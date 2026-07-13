# Contributing to wifikit

Thanks for your interest! Contributions of all kinds are welcome — bug reports,
features, docs, and board-compatibility notes.

## Ground rules

- **Authorized use only.** This project exists for lawful security testing and
  education. Do not submit code whose primary purpose is to attack third-party
  networks, evade detection maliciously, or otherwise facilitate unlawful use.
- Be respectful — see the [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

We use [uv](https://github.com/astral-sh/uv) for environments and packaging.

```bash
git clone https://github.com/BadRat-in/wifikit
cd wifikit
uv sync                 # venv + runtime + dev deps
```

Before opening a PR, make sure these pass:

```bash
uv run ruff check .     # lint
uv run ruff format --check .
uv run pytest           # unit tests (no hardware required)
```

## Guidelines

- **Docstrings & comments**: every module and public function should have a
  docstring explaining *what* and *why*; comment non-obvious logic.
- **Keep firmware knowledge in `marauder.py`** and transport in `session.py` so
  the UIs stay firmware-agnostic.
- **Small, focused commits** with clear messages (Conventional Commits style,
  e.g. `feat(tui): add station table`).
- Add or update tests for parsing/logic changes.
- Do not vendor Marauder firmware binaries into the repo — they are fetched at
  flash time.

## Reporting bugs

Open an issue with your board model, `wifikit --list-ports` output, the command
you ran, and what happened. For security-sensitive reports, see
[SECURITY.md](SECURITY.md).
