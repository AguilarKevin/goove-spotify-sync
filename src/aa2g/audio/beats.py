"""Real-time onset detection via spectral flux.

Consumes mono float32 frames from `AudioCapture` and emits `BeatEvent`s on
an asyncio queue. The detection is intentionally simple — energy spikes in
the low-mid spectrum, thresholded against a rolling median.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from collections import deque

import numpy as np

from .capture import AudioCapture

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BeatEvent:
    timestamp: float  # monotonic seconds
    strength: float   # 0–1, how much over threshold


@dataclass
class OnsetConfig:
    fft_size: int = 1024
    low_bin: int = 1     # skip DC
    high_bin: int = 100  # focus on bass/low-mids (~100 bins × 23Hz ≈ 2.3kHz at 48kHz)
    rolling_window_frames: int = 43  # ~1s of history at 1024-sample frames @ 48kHz
    threshold_mult: float = 1.7      # how many MADs above the median counts as an onset
    refractory_ms: float = 120.0     # minimum gap between consecutive beats


class OnsetDetector:
    def __init__(self, capture: AudioCapture, config: OnsetConfig | None = None) -> None:
        self.capture = capture
        self.config = config or OnsetConfig()
        self.events: asyncio.Queue[BeatEvent] = asyncio.Queue(maxsize=64)
        self._prev_mag: np.ndarray | None = None
        self._flux_history: deque[float] = deque(maxlen=self.config.rolling_window_frames)
        self._last_beat_t: float = 0.0
        self._buffer: np.ndarray = np.zeros(0, dtype=np.float32)
        self._task: asyncio.Task[None] | None = None
        self._window = np.hanning(self.config.fft_size).astype(np.float32)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        try:
            while True:
                frame = await self.capture.frames.get()
                self._buffer = np.concatenate((self._buffer, frame))
                while self._buffer.size >= self.config.fft_size:
                    chunk = self._buffer[: self.config.fft_size]
                    self._buffer = self._buffer[self.config.fft_size :]
                    self._process(chunk)
        except asyncio.CancelledError:
            raise

    def _process(self, chunk: np.ndarray) -> None:
        spectrum = np.fft.rfft(chunk * self._window)
        mag = np.abs(spectrum)[self.config.low_bin : self.config.high_bin]

        if self._prev_mag is None or self._prev_mag.shape != mag.shape:
            self._prev_mag = mag
            return

        diff = mag - self._prev_mag
        flux = float(np.sum(np.maximum(diff, 0.0)))
        self._prev_mag = mag

        history = self._flux_history
        history.append(flux)
        if len(history) < history.maxlen:
            return

        arr = np.fromiter(history, dtype=np.float32)
        median = float(np.median(arr))
        mad = float(np.median(np.abs(arr - median))) + 1e-6
        threshold = median + self.config.threshold_mult * mad

        now = time.monotonic()
        if (
            flux > threshold
            and (now - self._last_beat_t) * 1000.0 >= self.config.refractory_ms
        ):
            strength = min(1.0, (flux - threshold) / (threshold + 1e-6))
            self._last_beat_t = now
            try:
                self.events.put_nowait(BeatEvent(timestamp=now, strength=strength))
            except asyncio.QueueFull:
                pass
