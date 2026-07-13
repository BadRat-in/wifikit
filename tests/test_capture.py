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
    SavePcapStreamParser,
    looks_like_pcap,
)

# A known-valid 24-byte little-endian libpcap global header
# (linktype 105 = IEEE802_11), used as a stand-in capture payload.
PCAP = (
    b"\xd4\xc3\xb2\xa1\x02\x00\x04\x00"
    + b"\x00" * 8
    + b"\xff\xff\x00\x00"
    + b"\x69\x00\x00\x00"
)


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
