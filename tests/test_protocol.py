import pytest

from aa2g.govee import protocol


def test_frame_length_always_20():
    assert len(protocol.power(True)) == 20
    assert len(protocol.power(False)) == 20
    assert len(protocol.color(123, 45, 67)) == 20
    assert len(protocol.brightness(50)) == 20
    assert len(protocol.keep_alive()) == 20


def test_xor_checksum_known_values():
    assert protocol.xor_checksum(b"\x33\x01\x01") == 0x33 ^ 0x01 ^ 0x01
    assert protocol.xor_checksum(b"") == 0
    assert protocol.xor_checksum(b"\xff\xff") == 0


def test_power_on_frame():
    frame = protocol.power(True)
    assert frame[:3] == b"\x33\x01\x01"
    assert frame[3:19] == b"\x00" * 16
    assert frame[19] == protocol.xor_checksum(frame[:19])


def test_power_off_frame():
    frame = protocol.power(False)
    assert frame[:3] == b"\x33\x01\x00"
    assert frame[19] == protocol.xor_checksum(frame[:19])


def test_color_frame_layout():
    frame = protocol.color(0xAB, 0xCD, 0xEF)
    assert frame[:4] == b"\x33\x05\x15\x01"
    assert frame[4:7] == b"\xab\xcd\xef"
    assert frame[7:12] == b"\x00" * 5
    assert frame[12:14] == b"\xff\x7f"
    assert frame[14:19] == b"\x00" * 5
    assert frame[19] == protocol.xor_checksum(frame[:19])


def test_color_rejects_out_of_range():
    with pytest.raises(ValueError):
        protocol.color(-1, 0, 0)
    with pytest.raises(ValueError):
        protocol.color(0, 256, 0)


def test_brightness_frame():
    frame = protocol.brightness(75)
    assert frame[:3] == b"\x33\x04\x4b"
    assert frame[19] == protocol.xor_checksum(frame[:19])


def test_brightness_rejects_out_of_range():
    with pytest.raises(ValueError):
        protocol.brightness(101)
    with pytest.raises(ValueError):
        protocol.brightness(-1)


def test_keep_alive_frame():
    frame = protocol.keep_alive()
    assert frame[0] == 0xAA
    assert frame[1] == 0x01
    assert frame[2:19] == b"\x00" * 17
    assert frame[19] == 0xAB
