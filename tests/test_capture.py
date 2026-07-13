"""
Unit tests for the serial pcap demux (:mod:`wifikit.capture`).

These run without any hardware: they exercise :class:`SavePcapStreamParser`'s
framing logic (recovering ``[BUF/BEGIN]…[BUF/CLOSE]`` blobs from a noisy,
possibly chunk-split byte stream) and the :func:`looks_like_pcap` sanity check,
which is where demux bugs would otherwise hide.
"""

from wifikit.capture import (
    BUF_BEGIN,
    BUF_CLOSE,
    EAPOL_LLC_SNAP,
    SavePcapStreamParser,
    looks_like_pcap,
    pcap_frame_stats,
)

# A known-valid 24-byte little-endian libpcap global header
# (linktype 105 = IEEE802_11), used as a stand-in capture payload.
PCAP = (
    b"\xd4\xc3\xb2\xa1\x02\x00\x04\x00"
    + b"\x00" * 8
    + b"\xff\xff\x00\x00"
    + b"\x69\x00\x00\x00"
)


def _pcap_record(frame: bytes) -> bytes:
    """Wrap a raw frame in a 16-byte little-endian pcap record header."""
    n = len(frame).to_bytes(4, "little")
    return b"\x00" * 8 + n + n + frame  # ts_sec, ts_usec, incl_len, orig_len


def test_single_blob_recovered():
    p = SavePcapStreamParser()
    got = p.feed(BUF_BEGIN + PCAP + BUF_CLOSE)
    assert got == [PCAP]
    assert p.pcap_bytes() == PCAP
    assert looks_like_pcap(p.pcap_bytes())


def test_interleaved_console_noise():
    p = SavePcapStreamParser()
    got = p.feed(b"scanning...\n" + BUF_BEGIN + PCAP + BUF_CLOSE + b"\nEAPOL!!\n")
    assert got == [PCAP]
    assert p.pcap_bytes() == PCAP


def test_blob_split_across_feeds():
    framed = BUF_BEGIN + PCAP + BUF_CLOSE

    # Split inside the payload (after the begin marker + first 10 payload bytes).
    split = len(BUF_BEGIN) + 10
    p = SavePcapStreamParser()
    assert p.feed(framed[:split]) == []
    assert p.feed(framed[split:]) == [PCAP]
    assert p.pcap_bytes() == PCAP

    # Split inside the BUF_CLOSE marker itself.
    split = len(BUF_BEGIN) + len(PCAP) + 3
    p = SavePcapStreamParser()
    assert p.feed(framed[:split]) == []
    assert p.feed(framed[split:]) == [PCAP]
    assert p.pcap_bytes() == PCAP


def test_two_blobs():
    p = SavePcapStreamParser()
    p.feed(BUF_BEGIN + PCAP + BUF_CLOSE + BUF_BEGIN + PCAP + BUF_CLOSE)
    assert p.blob_count() == 2
    assert p.pcap_bytes() == PCAP + PCAP


def test_looks_like_pcap_rejects_junk():
    assert not looks_like_pcap(b"not a pcap")


def test_pcap_frame_stats_counts_frames_and_eapol():
    # Two frames: a plain beacon-ish frame (no EAPOL) and one carrying the
    # LLC/SNAP + EtherType 0x888E EAPOL signature.
    beacon = b"\x80\x00" + b"\x11" * 20
    eapol = b"\x08\x02" + b"\x22" * 10 + EAPOL_LLC_SNAP + b"\x03\x00\x5f"
    data = PCAP + _pcap_record(beacon) + _pcap_record(eapol)
    frames, eapol_count = pcap_frame_stats(data)
    assert frames == 2
    assert eapol_count == 1


def test_pcap_frame_stats_rejects_non_pcap():
    # Non-pcap input (and a header-only pcap with no records) yields no frames.
    assert pcap_frame_stats(b"not a pcap") == (0, 0)
    assert pcap_frame_stats(PCAP) == (0, 0)
