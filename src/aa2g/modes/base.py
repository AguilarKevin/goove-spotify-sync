"""Mode interface. A mode drives the strip's color over time, optionally
consuming beat events. Modes are cancellable; switching modes from the menu
cancels the current task and starts the new mode with the same state."""

from __future__ import annotations

import asyncio
from typing import Protocol

from ..audio.beats import BeatEvent
from ..govee.ble import GoveeStrip
from ..state import AppState


class Mode(Protocol):
    async def run(
        self,
        strip: GoveeStrip,
        state: AppState,
        beats: asyncio.Queue[BeatEvent],
    ) -> None: ...


def _lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * max(0.0, min(1.0, t))))


def lerp_rgb(
    a: tuple[int, int, int], b: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    return (_lerp(a[0], b[0], t), _lerp(a[1], b[1], t), _lerp(a[2], b[2], t))
