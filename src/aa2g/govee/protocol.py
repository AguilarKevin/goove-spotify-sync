"""Govee H617A BLE frame builders.

Packets are 20 bytes total: 19 data bytes + 1 XOR checksum byte.
Reference: community reverse-engineering of the H617A BLE protocol.
"""

from __future__ import annotations

PACKET_LEN = 20

SERVICE_UUID = "00010203-0405-0607-0809-0a0b0c0d1910"
WRITE_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"


def xor_checksum(data: bytes) -> int:
    result = 0
    for byte in data:
        result ^= byte
    return result


def _frame(*head: int) -> bytes:
    if len(head) > PACKET_LEN - 1:
        raise ValueError(f"frame header too long: {len(head)} bytes")
    body = bytes(head) + b"\x00" * (PACKET_LEN - 1 - len(head))
    return body + bytes([xor_checksum(body)])


def power(on: bool) -> bytes:
    return _frame(0x33, 0x01, 0x01 if on else 0x00)


def color(r: int, g: int, b: int) -> bytes:
    for name, v in (("r", r), ("g", g), ("b", b)):
        if not 0 <= v <= 255:
            raise ValueError(f"{name} out of range: {v}")
    # Bytes 12-13 (0xFF 0x7F) are observed segment-mask values for "all segments".
    return _frame(
        0x33, 0x05, 0x15, 0x01, r, g, b,
        0x00, 0x00, 0x00, 0x00, 0x00,
        0xFF, 0x7F,
    )


def brightness(percent: int) -> bytes:
    if not 0 <= percent <= 100:
        raise ValueError(f"brightness out of range: {percent}")
    return _frame(0x33, 0x04, percent)


def keep_alive() -> bytes:
    # Special-cased: trailing byte is 0xAB, not an XOR checksum.
    return bytes([0xAA, 0x01]) + b"\x00" * 17 + bytes([0xAB])
