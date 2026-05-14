"""Entry point: bootstraps the worker, starts the menu bar app."""

from __future__ import annotations

import logging


def _set_accessory_activation_policy() -> None:
    """Tell AppKit this is a status-bar-only app.

    Launching our bundle's script exec's the Homebrew Python binary, which
    macOS treats as a foreground GUI app (Python.app has its own
    NSApplication identity). That activation messes up the status-bar item
    layout: rumps creates the item but macOS lays it out with zero height,
    so it never renders. Setting Accessory before rumps initializes
    suppresses the foreground activation and the item paints normally.
    """
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyAccessory
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _set_accessory_activation_policy()
    from .menu import AlbumArtToGooveApp
    from .state import AppState
    from .worker import Worker
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
