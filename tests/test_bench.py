"""
Unit tests for the crack-speed estimator (:mod:`wifikit.bench`).

These exercise the pure parsing/estimation helpers with no GPU or hashcat
present — that is where an off-by-a-unit or bad-regex bug would hide.
"""

from wifikit.bench import (
    KEYSPACES,
    crack_time_table,
    human_duration,
    parse_hashrate,
)


def test_parse_hashrate_plain_hs():
    line = "Speed.#02........:    81055 H/s (33.77ms) @ Accel:224 Loops:1024"
    assert parse_hashrate(line) == 81055.0


def test_parse_hashrate_scales_units():
    assert parse_hashrate("Speed.#01....: 1234.5 kH/s") == 1_234_500.0
    assert parse_hashrate("Speed.#01....: 2.5 MH/s") == 2_500_000.0


def test_parse_hashrate_takes_max_across_devices():
    text = "Speed.#01....: 40000 H/s\nSpeed.#02....: 81055 H/s\n"
    assert parse_hashrate(text) == 81055.0


def test_parse_hashrate_none_when_absent():
    assert parse_hashrate("no speed here\nStarted: ...") is None


def test_human_duration_scales():
    assert human_duration(30) == "30.0 sec"
    assert human_duration(90) == "1.5 min"
    assert human_duration(7200) == "2.0 hours"
    assert human_duration(172800) == "2.0 days"
    # ~2.6k years for a full 8-char ASCII keyspace at ~81k H/s.
    assert human_duration(95**8 / 81000).endswith("k years")


def test_crack_time_table_shape_and_ordering():
    table = crack_time_table(81000)
    assert len(table) == len(KEYSPACES)
    labels, counts, times = zip(*table, strict=True)
    assert "rockyou" in labels[0].lower()  # cheapest keyspace first
    # Keyspaces are curated smallest→largest, so times grow monotonically.
    assert list(counts) == sorted(counts)
    # rockyou (~14M) at 81k H/s ≈ 3 minutes.
    assert times[0].endswith("min")
