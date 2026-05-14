"""Spotify Web API client. Only the currently-playing endpoint is used.

Note: audio-analysis / audio-features were deprecated 2024-11-27 for apps
registered after that date, so we don't depend on them. Beat data comes from
local audio capture in `aa2g.audio` instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from . import auth

BASE = "https://api.spotify.com/v1"


@dataclass(frozen=True)
class NowPlaying:
    track_id: str
    track_name: str
    artist_name: str
    album_art_url: str
    progress_ms: int
    duration_ms: int
    is_playing: bool


class SpotifyClient:
    def __init__(self) -> None:
        self._tokens: auth.Tokens | None = None

    def _get_tokens(self) -> auth.Tokens:
        if self._tokens is None or self._tokens.expired:
            t = auth.get_valid_tokens()
            if t is None:
                raise RuntimeError("not signed in")
            self._tokens = t
        return self._tokens

    async def currently_playing(self) -> NowPlaying | None:
        tokens = self._get_tokens()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BASE}/me/player/currently-playing",
                headers={"Authorization": f"Bearer {tokens.access_token}"},
            )
        if resp.status_code == 204:
            return None  # nothing playing
        if resp.status_code == 401:
            self._tokens = None  # force refresh on next call
            raise RuntimeError("auth expired")
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        item = body.get("item")
        if not item or item.get("type") != "track":
            return None
        images = item["album"].get("images") or []
        # images are sorted largest-first; pick the largest <=300px for speed
        chosen = next((i for i in reversed(images) if i.get("height", 0) >= 200), images[0])
        return NowPlaying(
            track_id=item["id"],
            track_name=item["name"],
            artist_name=", ".join(a["name"] for a in item["artists"]),
            album_art_url=chosen["url"],
            progress_ms=body.get("progress_ms") or 0,
            duration_ms=item["duration_ms"],
            is_playing=bool(body.get("is_playing")),
        )
