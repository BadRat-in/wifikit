"""
Unit tests for persistent user settings (:mod:`wifikit.config`).

Exercises the :class:`Config` dataclass defaults, the JSON save/load round-trip
(including graceful handling of missing, corrupt, and forward-compatible files),
and the automatic wordlist resolution. All filesystem access is redirected to
pytest's ``tmp_path`` so the real user config file is never touched.
"""

from wifikit.config import Config, load_config, save_config


def test_defaults():
    config = Config()
    assert config.capture_seconds == 20
    assert config.auto_deauth is False
    assert config.deauth_seconds == 5
    assert config.wordlist == ""
    assert config.auto_convert is True
    assert config.captures_dir == "captures"
    assert config.theme == "textual-dark"
    assert config.port == ""


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "c.json"
    config = Config(
        capture_seconds=42,
        auto_deauth=True,
        deauth_seconds=9,
        wordlist="custom.txt",
        auto_convert=False,
        captures_dir="/tmp/caps",
        theme="textual-light",
        port="/dev/ttyUSB0",
    )
    save_config(config, path)
    assert load_config(path) == config


def test_load_missing_file_returns_defaults(tmp_path):
    assert load_config(tmp_path / "nope.json") == Config()


def test_load_corrupt_file_returns_defaults(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{ not json")
    assert load_config(path) == Config()


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "extra.json"
    path.write_text('{"capture_seconds": 99, "nonsense": 1}')
    config = load_config(path)
    assert config.capture_seconds == 99


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "a" / "b" / "c.json"
    save_config(Config(), path)
    assert path.exists()


def test_resolved_wordlist_explicit():
    assert Config(wordlist="foo.txt").resolved_wordlist() == "foo.txt"


def test_resolved_wordlist_fallback_to_example(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert Config(wordlist="").resolved_wordlist() == "wordlists/example-passwords.txt"
