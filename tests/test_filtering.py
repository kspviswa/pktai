import pytest

from pktai_tui.services.filtering import filter_packets, Lexer, Parser


class FakeLayer:
    def __init__(self, **fields):
        for k, v in fields.items():
            setattr(self, k, v)

    def get_field(self, name):
        return getattr(self, name, None)


class FakePacket:
    def __init__(self, **layers):
        for lname, lobj in layers.items():
            setattr(self, lname, lobj)


def test_protocol_only():
    pkts = [
        FakePacket(ip=FakeLayer(src="1.2.3.4")),
        FakePacket(tcp=FakeLayer(srcport=80)),
        FakePacket(sctp=FakeLayer(dstport=38412), ngap=FakeLayer()),
    ]
    out = filter_packets(pkts, "ngap")
    assert len(out) == 1 and hasattr(out[0], "ngap")


def test_field_equality_ip_src():
    pkts = [
        FakePacket(ip=FakeLayer(src="1.2.3.4")),
        FakePacket(ip=FakeLayer(src="10.0.0.1")),
    ]
    out = filter_packets(pkts, "ip.src == 1.2.3.4")
    assert len(out) == 1 and out[0].ip.src == "1.2.3.4"


def test_sctp_and_ngap():
    pkts = [
        FakePacket(sctp=FakeLayer(dstport=1111)),
        FakePacket(sctp=FakeLayer(dstport=38412)),
        FakePacket(sctp=FakeLayer(dstport=38412), ngap=FakeLayer()),
    ]
    out = filter_packets(pkts, "sctp.dstport == 38412 && ngap")
    assert len(out) == 1 and hasattr(out[0], "ngap") and out[0].sctp.dstport == 38412


def test_or_with_parentheses():
    pkts = [
        FakePacket(ip=FakeLayer(src="1.2.3.4", dst="10.0.0.2")),
        FakePacket(ip=FakeLayer(src="10.0.0.1", dst="1.2.3.4")),
        FakePacket(ip=FakeLayer(src="10.0.0.1", dst="10.0.0.2")),
    ]
    out = filter_packets(pkts, "(ip.src == 1.2.3.4) || (ip.dst == 1.2.3.4)")
    assert len(out) == 2


def test_presence_and_not_equal():
    pkts = [
        FakePacket(ip=FakeLayer(src="10.0.0.1")),
        FakePacket(ip=FakeLayer(src="1.2.3.4")),
        FakePacket(tcp=FakeLayer(srcport=80)),
    ]
    out = filter_packets(pkts, "ip.src != 10.0.0.1 && ip")
    # should select the second packet only
    assert len(out) == 1 and hasattr(out[0], "ip") and out[0].ip.src == "1.2.3.4"


def test_unknown_protocol():
    pkts = [FakePacket(ip=FakeLayer(src="1.2.3.4"))]
    out = filter_packets(pkts, "unknownproto")
    assert len(out) == 0


def test_unknown_field_safe_false():
    pkts = [FakePacket(ip=FakeLayer(src="1.2.3.4"))]
    out = filter_packets(pkts, "ip.unknownfield == 1")
    assert len(out) == 0


def test_unsupported_operator_contains():
    with pytest.raises(NotImplementedError):
        # tokenization should raise NotImplementedError
        filter_packets([], "http.host contains example")


def test_empty_filter_returns_all():
    pkts = [FakePacket(), FakePacket()]
    out = filter_packets(pkts, "  ")
    assert len(out) == 2
