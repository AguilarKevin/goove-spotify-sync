"""BLE driver for the Govee H617A.

Owns the BleakClient lifecycle: connect, write, periodic keep-alive, reconnect.
Designed to be driven from an asyncio event loop on a background thread.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from contextlib import suppress
from dataclasses import dataclass

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from . import protocol

log = logging.getLogger(__name__)

DEVICE_NAME_PREFIXES = ("ihoment_H617A", "Govee_H617A", "GBK_H617A")
KEEP_ALIVE_INTERVAL_S = 2.0
RECONNECT_BACKOFF_S = 5.0


@dataclass
class StripState:
    connected: bool = False
    last_error: str | None = None


async def discover(timeout: float = 6.0) -> list[BLEDevice]:
    devices = await BleakScanner.discover(timeout=timeout)
    return [d for d in devices if d.name and d.name.startswith(DEVICE_NAME_PREFIXES)]


class GoveeStrip:
    """A single H617A connection.

    Use as `async with GoveeStrip(address) as strip: await strip.set_color(...)`.
    The context manager owns the keep-alive task. Outside the context, the
    `connect_forever()` helper keeps reconnecting on failure.
    """

    def __init__(self, address: str) -> None:
        self.address = address
        self.state = StripState()
        self._client: BleakClient | None = None
        self._keep_alive_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()

    async def __aenter__(self) -> "GoveeStrip":
        await self._connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._disconnect()

    async def _connect(self) -> None:
        client = BleakClient(self.address)
        await client.connect()
        self._client = client
        self.state.connected = True
        self.state.last_error = None
        self._keep_alive_task = asyncio.create_task(self._keep_alive_loop())
        log.info("connected to %s", self.address)

    async def _disconnect(self) -> None:
        if self._keep_alive_task:
            self._keep_alive_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._keep_alive_task
            self._keep_alive_task = None
        if self._client and self._client.is_connected:
            with suppress(Exception):
                await self._client.disconnect()
        self._client = None
        self.state.connected = False

    async def _write(self, packet: bytes) -> None:
        if not self._client or not self._client.is_connected:
            raise RuntimeError("not connected")
        async with self._write_lock:
            await self._client.write_gatt_char(
                protocol.WRITE_CHAR_UUID, packet, response=False
            )

    async def _keep_alive_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(KEEP_ALIVE_INTERVAL_S)
                try:
                    await self._write(protocol.keep_alive())
                except Exception as e:
                    log.warning("keep-alive failed: %s", e)
                    return
        except asyncio.CancelledError:
            pass

    async def set_power(self, on: bool) -> None:
        await self._write(protocol.power(on))

    async def set_color(self, r: int, g: int, b: int) -> None:
        await self._write(protocol.color(r, g, b))

    async def set_brightness(self, percent: int) -> None:
        await self._write(protocol.brightness(percent))

    async def connect_forever(self, on_connect=None) -> None:
        """Keep reconnecting on disconnect. Intended to run as a long-lived task."""
        while True:
            try:
                await self._connect()
                if on_connect:
                    await on_connect(self)
                while self._client and self._client.is_connected:
                    await asyncio.sleep(1.0)
                log.info("link dropped, will reconnect")
            except asyncio.CancelledError:
                await self._disconnect()
                raise
            except Exception as e:
                self.state.last_error = str(e)
                log.warning("connect failed: %s", e)
            finally:
                await self._disconnect()
            await asyncio.sleep(RECONNECT_BACKOFF_S)


async def _cli_discover() -> int:
    print("scanning for H617A devices (6s)…")
    devices = await discover()
    if not devices:
        print("none found. Make sure the strip is powered and in range.")
        return 1
    for d in devices:
        print(f"  {d.address}  {d.name}")
    return 0


async def _cli_color(address: str, r: int, g: int, b: int) -> int:
    async with GoveeStrip(address) as strip:
        await strip.set_power(True)
        await strip.set_color(r, g, b)
        await asyncio.sleep(0.5)
    print(f"wrote rgb({r},{g},{b}) to {address}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aa2g.govee.ble")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover", help="scan for nearby Govee H617A devices")
    p_color = sub.add_parser("color", help="set the strip to an RGB color")
    p_color.add_argument("address", help="BLE address (from `discover`)")
    p_color.add_argument("r", type=int)
    p_color.add_argument("g", type=int)
    p_color.add_argument("b", type=int)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.cmd == "discover":
        return asyncio.run(_cli_discover())
    if args.cmd == "color":
        return asyncio.run(_cli_color(args.address, args.r, args.g, args.b))
    return 2


if __name__ == "__main__":
    sys.exit(main())
