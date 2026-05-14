"""System audio capture via BlackHole (or any input device).

The user routes Spotify's output through BlackHole (typically via a
Multi-Output Device in Audio MIDI Setup), and we read those samples here.
Audio is captured on a sounddevice thread and pushed into an asyncio queue
as mono float32 frames so onset detection can consume them in the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 48000
DEFAULT_BLOCK_SIZE = 1024  # ~21ms at 48kHz — plenty fine-grained for onsets


@dataclass
class AudioDevice:
    index: int
    name: str
    channels: int
    sample_rate: float


def list_input_devices() -> list[AudioDevice]:
    out: list[AudioDevice] = []
    for i, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] > 0:
            out.append(
                AudioDevice(
                    index=i,
                    name=info["name"],
                    channels=info["max_input_channels"],
                    sample_rate=info["default_samplerate"],
                )
            )
    return out


def find_blackhole() -> AudioDevice | None:
    for dev in list_input_devices():
        if "blackhole" in dev.name.lower():
            return dev
    return None


class AudioCapture:
    """Wraps a sounddevice InputStream and exposes a frame queue."""

    def __init__(
        self,
        device: AudioDevice,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        block_size: int = DEFAULT_BLOCK_SIZE,
        queue_maxsize: int = 16,
    ) -> None:
        self.device = device
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.frames: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=queue_maxsize)
        self._stream: sd.InputStream | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:
        if status:
            log.debug("audio status: %s", status)
        mono = indata.mean(axis=1).astype(np.float32, copy=True)
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        # Use call_soon_threadsafe to bridge the audio thread → asyncio loop.
        loop.call_soon_threadsafe(self._push, mono)

    def _push(self, mono: np.ndarray) -> None:
        if self.frames.full():
            try:
                self.frames.get_nowait()  # drop oldest
            except asyncio.QueueEmpty:
                pass
        self.frames.put_nowait(mono)

    async def __aenter__(self) -> "AudioCapture":
        self._loop = asyncio.get_running_loop()
        self._stream = sd.InputStream(
            device=self.device.index,
            channels=min(self.device.channels, 2),
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        log.info("audio capture started on '%s'", self.device.name)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
