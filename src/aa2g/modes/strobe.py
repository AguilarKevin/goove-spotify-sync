"""Strobe mode: alternate between the primary palette color and a contrast
color on every beat. Drops to every-other-beat if beats arrive faster than
the BLE link can handle."""

from __future__ import annotations

import asyncio
import logging
import time

from ..audio.beats import BeatEvent
from ..govee.ble import GoveeStrip
from ..state import AppState

log = logging.getLogger(__name__)

MIN_BEAT_INTERVAL_S = 0.10  # ~10Hz BLE write cap; below this we skip


class StrobeMode:
    async def run(
        self,
        strip: GoveeStrip,
        state: AppState,
        beats: asyncio.Queue[BeatEvent],
    ) -> None:
        toggle = False
        last_write_t = 0.0
        while True:
            try:
                _beat = await asyncio.wait_for(beats.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            now = time.monotonic()
            if now - last_write_t < MIN_BEAT_INTERVAL_S:
                continue  # downsample

            colors = self._colors(state)
            if colors is None:
                continue
            primary, secondary = colors
            color = primary if not toggle else secondary
            try:
                await strip.set_color(*color)
                toggle = not toggle
                last_write_t = now
            except Exception as e:
                log.warning("strobe write failed: %s", e)
                await asyncio.sleep(0.5)

    @staticmethod
    def _colors(state: AppState):
        if state.palette is None or not state.now_playing or not state.now_playing.is_playing:
            return None
        primary = state.palette.pick(state.settings.palette_strategy)
        # Secondary = whichever palette entry differs most from primary.
        candidates = [
            state.palette.dominant,
            state.palette.vibrant,
            state.palette.muted,
            state.palette.dark_vibrant,
        ]
        secondary = max(candidates, key=lambda c: _distance_sq(c, primary))
        return primary, secondary


def _distance_sq(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
