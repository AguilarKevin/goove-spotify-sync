"""Solid mode: smoothly fade from the previous color to the current palette
pick whenever the palette changes. Ignores beat events."""

from __future__ import annotations

import asyncio
import logging

from ..audio.beats import BeatEvent
from ..govee.ble import GoveeStrip
from ..state import AppState
from .base import lerp_rgb

log = logging.getLogger(__name__)

FADE_DURATION_S = 0.8
FADE_STEPS = 12
POLL_INTERVAL_S = 0.2


class SolidMode:
    async def run(
        self,
        strip: GoveeStrip,
        state: AppState,
        beats: asyncio.Queue[BeatEvent],
    ) -> None:
        current = (0, 0, 0)
        last_target: tuple[int, int, int] | None = None
        while True:
            target = self._target(state)
            if target is not None and target != last_target:
                await self._fade(strip, current, target)
                current = target
                last_target = target
            await asyncio.sleep(POLL_INTERVAL_S)

    @staticmethod
    def _target(state: AppState) -> tuple[int, int, int] | None:
        if state.palette is not None and state.now_playing and state.now_playing.is_playing:
            return state.palette.pick(state.settings.palette_strategy)
        return state.settings.idle_color  # may be None → no update

    @staticmethod
    async def _fade(
        strip: GoveeStrip,
        start: tuple[int, int, int],
        end: tuple[int, int, int],
    ) -> None:
        step_dt = FADE_DURATION_S / FADE_STEPS
        for i in range(1, FADE_STEPS + 1):
            t = i / FADE_STEPS
            r, g, b = lerp_rgb(start, end, t)
            try:
                await strip.set_color(r, g, b)
            except Exception as e:
                log.warning("fade write failed: %s", e)
                return
            await asyncio.sleep(step_dt)
