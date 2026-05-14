"""Shared state between the asyncio worker thread and the menu-bar UI thread.

All writes happen on the worker thread; UI thread reads. Each field is a
plain Python reference (atomic assignment), so a lock isn't needed for the
single-writer/multi-reader case.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .color.extract import Palette
from .spotify.client import NowPlaying

CONFIG_DIR = Path.home() / ".config" / "aa2g"
STATE_PATH = CONFIG_DIR / "state.json"

VALID_MODES = ("solid", "pulse", "strobe")
VALID_STRATEGIES = ("dominant", "vibrant", "muted", "dark_vibrant")


@dataclass
class PersistedSettings:
    """Saved to disk in ~/.config/aa2g/state.json."""
    mode: str = "solid"
    palette_strategy: str = "vibrant"
    idle_color: tuple[int, int, int] | None = None  # None == "turn off when idle"
    ble_address: str | None = None
    audio_device_name: str | None = None  # match-by-name; survives device-index churn
    sync_enabled: bool = True

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with STATE_PATH.open("w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls) -> "PersistedSettings":
        if not STATE_PATH.exists():
            return cls()
        with STATE_PATH.open() as f:
            data = json.load(f)
        if data.get("idle_color") is not None:
            data["idle_color"] = tuple(data["idle_color"])
        return cls(**data)


@dataclass
class AppState:
    settings: PersistedSettings = field(default_factory=PersistedSettings.load)
    now_playing: NowPlaying | None = None
    palette: Palette | None = None
    strip_connected: bool = False
    spotify_signed_in: bool = False
    last_error: str | None = None
