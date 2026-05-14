"""Pulse mode: hold the palette color, briefly brighten on each beat.

We can't easily modulate brightness *during* a hold while a color command is
in flight, so we approximate by writing a dimmed version then snapping back
to full color on the beat. Effect is a flash that decays.
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..audio.beats import BeatEvent
from ..govee.ble import GoveeStrip
from ..state import AppState

log = logging.getLogger(__name__)

DIM_FACTOR = 0.55      # baseline brightness while waiting
FLASH_DECAY_S = 0.15   # how long the bright peak holds before returning to dim
IDLE_REFRESH_S = 1.0   # re-send color occasionally even without beats


def _scaled(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return (
        int(round(rgb[0] * factor)),
        int(round(rgb[1] * factor)),
        int(round(rgb[2] * factor)),
    )


class PulseMode:
    async def run(
        self,
        strip: GoveeStrip,
        state: AppState,
        beats: asyncio.Queue[BeatEvent],
    ) -> None:
        last_write = 0.0
        last_color: tuple[int, int, int] | None = None
        flash_until = 0.0

        while True:
            base = self._base_color(state)
            if base is None:
                await asyncio.sleep(0.2)
                continue

            now = time.monotonic()
            try:
                beat = await asyncio.wait_for(beats.get(), timeout=0.05)
                flash_until = now + FLASH_DECAY_S
                target = base
            except asyncio.TimeoutError:
                target = base if now < flash_until else _scaled(base, DIM_FACTOR)

            if target != last_color or (now - last_write) > IDLE_REFRESH_S:
                try:
                    await strip.set_color(*target)
                    last_color = target
                    last_write = now
                except Exception as e:
                    log.warning("pulse write failed: %s", e)
                    await asyncio.sleep(0.5)

    @staticmethod
    def _base_color(state: AppState) -> tuple[int, int, int] | None:
        if state.palette is not None and state.now_playing and state.now_playing.is_playing:
            return state.palette.pick(state.settings.palette_strategy)
        return state.settings.idle_color
