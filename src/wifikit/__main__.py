"""Enable ``python -m wifikit`` to launch the same entry point as ``wifikit``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
