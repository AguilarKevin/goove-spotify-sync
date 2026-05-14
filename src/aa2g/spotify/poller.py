"""Spotify polling loop. Updates AppState.now_playing and recomputes palette
when the track changes. Designed to run as an asyncio task on the worker thread.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from ..color.extract import palette_from_url
from ..state import AppState
from .client import SpotifyClient, NowPlaying

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 2.0
ERROR_BACKOFF_S = 5.0


async def run_poller(
    state: AppState,
    on_track_change: Callable[[NowPlaying], Awaitable[None]] | None = None,
) -> None:
    client = SpotifyClient()
    last_track_id: str | None = None
    while True:
        try:
            playing = await client.currently_playing()
            state.now_playing = playing
            state.spotify_signed_in = True
            state.last_error = None
            if playing is not None and playing.track_id != last_track_id:
                last_track_id = playing.track_id
                log.info("track change → %s — %s", playing.artist_name, playing.track_name)
                try:
                    state.palette = await asyncio.to_thread(
                        palette_from_url, playing.album_art_url
                    )
                except Exception as e:
                    log.warning("palette extraction failed: %s", e)
                if on_track_change:
                    await on_track_change(playing)
            await asyncio.sleep(POLL_INTERVAL_S)
        except asyncio.CancelledError:
            raise
        except RuntimeError as e:
            state.last_error = str(e)
            if "not signed in" in str(e):
                state.spotify_signed_in = False
            log.warning("spotify error: %s", e)
            await asyncio.sleep(ERROR_BACKOFF_S)
        except Exception as e:
            state.last_error = str(e)
            log.exception("unexpected poller error")
            await asyncio.sleep(ERROR_BACKOFF_S)
