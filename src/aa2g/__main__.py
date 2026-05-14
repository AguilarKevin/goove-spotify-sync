"""Entry point: bootstraps the worker, starts the menu bar app."""

from __future__ import annotations

import logging

from .menu import AlbumArtToGooveApp
from .state import AppState
from .worker import Worker


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    state = AppState()
    worker = Worker(state)
    worker.start()
    worker.start_all()
    app = AlbumArtToGooveApp(worker)
    try:
        app.run()
    finally:
        worker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
