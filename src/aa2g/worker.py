"""The background worker. Runs an asyncio loop that owns:
  - the BLE strip connection (with reconnect)
  - the Spotify poller (track + palette)
  - the audio capture + onset detector (beat events)
  - the currently-selected mode (consuming the above)

The menu bar UI talks to it via thread-safe coroutine submissions.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from .audio.beats import OnsetDetector
from .audio.capture import AudioCapture, AudioDevice, find_blackhole, list_input_devices
from .govee.ble import GoveeStrip
from .modes import MODES
from .spotify.poller import run_poller
from .state import AppState

log = logging.getLogger(__name__)


class Worker:
    """Lifecycle owner for the asyncio loop running on a background thread."""

    def __init__(self, state: AppState) -> None:
        self.state = state
        self.loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._tasks: dict[str, asyncio.Task] = {}
        self._strip: GoveeStrip | None = None
        self._capture: AudioCapture | None = None
        self._detector: OnsetDetector | None = None
        self._ready = threading.Event()

    # ── lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="aa2g-worker")
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def stop(self) -> None:
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self._thread:
            self._thread.join(timeout=3.0)

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        try:
            self.loop.run_forever()
        finally:
            self.loop.run_until_complete(self._shutdown())
            self.loop.close()

    async def _shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    # ── thread-safe entry points (called from UI thread) ────────────────

    def submit(self, coro_factory):
        """Schedule a coroutine on the worker loop from another thread."""
        if not self.loop or not self.loop.is_running():
            return None
        return asyncio.run_coroutine_threadsafe(coro_factory(), self.loop)

    def restart_mode(self) -> None:
        self.submit(self._restart_mode)

    def start_all(self) -> None:
        self.submit(self._start_all)

    # ── internal coroutines ─────────────────────────────────────────────

    async def _start_all(self) -> None:
        if not self.state.settings.sync_enabled:
            return
        await self._start_strip()
        await self._start_audio()
        await self._start_spotify()
        await self._restart_mode()

    async def _start_strip(self) -> None:
        addr = self.state.settings.ble_address
        if not addr:
            log.warning("no BLE address configured — run Re-pair from the menu")
            return
        if "strip" in self._tasks:
            return
        strip = GoveeStrip(addr)
        self._strip = strip

        async def keep_connected() -> None:
            async def on_connect(s: GoveeStrip) -> None:
                self.state.strip_connected = True
                try:
                    await s.set_power(True)
                except Exception as e:
                    log.warning("power-on failed: %s", e)

            try:
                await strip.connect_forever(on_connect=on_connect)
            finally:
                self.state.strip_connected = False

        self._tasks["strip"] = asyncio.create_task(keep_connected())

    async def _start_audio(self) -> None:
        if "audio" in self._tasks:
            return
        device = self._pick_audio_device()
        if device is None:
            log.warning("no BlackHole device found — beat detection disabled")
            return
        self.state.settings.audio_device_name = device.name
        self._capture = AudioCapture(device)
        self._detector = OnsetDetector(self._capture)

        async def run_audio() -> None:
            async with self._capture:  # type: ignore[arg-type]
                self._detector.start()  # type: ignore[union-attr]
                try:
                    await asyncio.Event().wait()  # block until cancelled
                finally:
                    await self._detector.stop()  # type: ignore[union-attr]

        self._tasks["audio"] = asyncio.create_task(run_audio())

    def _pick_audio_device(self) -> AudioDevice | None:
        target_name = self.state.settings.audio_device_name
        if target_name:
            for dev in list_input_devices():
                if dev.name == target_name:
                    return dev
        return find_blackhole()

    async def _start_spotify(self) -> None:
        if "spotify" in self._tasks:
            return
        self._tasks["spotify"] = asyncio.create_task(run_poller(self.state))

    async def _restart_mode(self) -> None:
        old = self._tasks.pop("mode", None)
        if old is not None:
            old.cancel()
            try:
                await old
            except (asyncio.CancelledError, Exception):
                pass
        if not self.state.settings.sync_enabled:
            return
        if self._strip is None or self._detector is None:
            return
        mode_cls = MODES.get(self.state.settings.mode, MODES["solid"])
        mode = mode_cls()
        self._tasks["mode"] = asyncio.create_task(
            mode.run(self._strip, self.state, self._detector.events)
        )
