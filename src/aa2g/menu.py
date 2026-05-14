"""rumps-based menu bar app. Runs on the main thread (AppKit requirement).
All Bluetooth / Spotify / audio I/O is dispatched to the Worker thread."""

from __future__ import annotations

import logging
import threading
from importlib.resources import files

import rumps

from .govee import ble as ble_mod
from .spotify import auth as spotify_auth
from .state import AppState, VALID_MODES, VALID_STRATEGIES
from .worker import Worker

MENUBAR_ICON = str(files("aa2g.assets").joinpath("menubar.png"))

log = logging.getLogger(__name__)


def _swatch(rgb: tuple[int, int, int] | None) -> str:
    if rgb is None:
        return "—"
    # Map 256-color RGB to one of seven colored circle emojis. Good enough for a menu glyph.
    r, g, b = rgb
    if max(r, g, b) < 60:
        return "⚫"
    if r > g and r > b:
        return "🔴" if r > 200 else "🟤"
    if g > r and g > b:
        return "🟢"
    if b > r and b > g:
        return "🔵" if b > 200 else "🟣"
    if r > 200 and g > 200 and b < 100:
        return "🟡"
    if r > 200 and g > 100 and b < 100:
        return "🟠"
    return "⚪"


class AlbumArtToGooveApp(rumps.App):
    def __init__(self, worker: Worker) -> None:
        super().__init__(
            name="aa2g",
            icon=MENUBAR_ICON,
            template=True,  # let macOS recolor for light/dark menu bar
            quit_button=None,
        )
        self.worker = worker
        self.state: AppState = worker.state
        self._build_menu()
        self.refresh_timer = rumps.Timer(self._refresh, 1.0)
        self.refresh_timer.start()

    # ── menu construction ───────────────────────────────────────────────

    def _build_menu(self) -> None:
        self.now_playing_item = rumps.MenuItem("(nothing playing)")
        self.now_playing_item.set_callback(None)
        self.swatch_item = rumps.MenuItem("— color")
        self.swatch_item.set_callback(None)
        self.strip_status_item = rumps.MenuItem("Strip: disconnected")
        self.strip_status_item.set_callback(None)
        self.spotify_status_item = rumps.MenuItem("Spotify: signed out")
        self.spotify_status_item.set_callback(None)

        self.sync_item = rumps.MenuItem("Sync enabled", callback=self._toggle_sync)
        self.sync_item.state = 1 if self.state.settings.sync_enabled else 0

        mode_submenu = self._build_radio_submenu(
            "Mode", VALID_MODES, self.state.settings.mode, self._on_mode_change
        )
        palette_submenu = self._build_radio_submenu(
            "Palette", VALID_STRATEGIES, self.state.settings.palette_strategy,
            self._on_strategy_change,
        )

        self.menu = [
            self.now_playing_item,
            self.swatch_item,
            None,
            self.spotify_status_item,
            self.strip_status_item,
            None,
            self.sync_item,
            mode_submenu,
            palette_submenu,
            None,
            rumps.MenuItem("Re-pair light strip…", callback=self._repair_strip),
            rumps.MenuItem("Sign in to Spotify…", callback=self._sign_in_spotify),
            rumps.MenuItem("Sign out of Spotify", callback=self._sign_out_spotify),
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ]

    def _build_radio_submenu(
        self,
        title: str,
        options: tuple[str, ...],
        current: str,
        callback,
    ):
        items = []
        for opt in options:
            item = rumps.MenuItem(
                opt.replace("_", " ").title(),
                callback=callback,
            )
            item.state = 1 if opt == current else 0
            item._aa2g_key = opt  # store the underlying key
            items.append(item)
        return {title: items}

    # ── callbacks ───────────────────────────────────────────────────────

    def _toggle_sync(self, sender: rumps.MenuItem) -> None:
        new = not bool(sender.state)
        sender.state = 1 if new else 0
        self.state.settings.sync_enabled = new
        self.state.settings.save()
        self.worker.restart_mode()

    def _on_mode_change(self, sender: rumps.MenuItem) -> None:
        self._set_radio(self.menu["Mode"], sender)
        self.state.settings.mode = sender._aa2g_key
        self.state.settings.save()
        self.worker.restart_mode()

    def _on_strategy_change(self, sender: rumps.MenuItem) -> None:
        self._set_radio(self.menu["Palette"], sender)
        self.state.settings.palette_strategy = sender._aa2g_key
        self.state.settings.save()
        # No mode restart — modes read strategy on each tick

    @staticmethod
    def _set_radio(submenu, chosen: rumps.MenuItem) -> None:
        for item in submenu.values():
            item.state = 0
        chosen.state = 1

    def _repair_strip(self, _sender) -> None:
        rumps.alert(
            "Scanning for Govee strips",
            "Scanning for 6 seconds. Make sure the strip is powered on.",
        )

        def scan_done(fut) -> None:
            try:
                devices = fut.result()
            except Exception as e:
                rumps.alert("Scan failed", str(e))
                return
            if not devices:
                rumps.alert("No strips found", "Check that the H617A is powered and in range.")
                return
            choices = [f"{d.address} — {d.name}" for d in devices]
            window = rumps.Window(
                title="Pair with strip",
                message="Type the address of the strip you want to use:\n\n" + "\n".join(choices),
                default_text=devices[0].address,
                dimensions=(280, 40),
            )
            resp = window.run()
            if resp.clicked and resp.text:
                self.state.settings.ble_address = resp.text.strip()
                self.state.settings.save()
                self.worker.start_all()

        future = self.worker.submit(ble_mod.discover)
        if future is not None:
            future.add_done_callback(scan_done)

    def _sign_in_spotify(self, _sender) -> None:
        def go() -> None:
            try:
                spotify_auth.sign_in()
                self.state.spotify_signed_in = True
                self.worker.start_all()
            except Exception as e:
                rumps.alert("Sign-in failed", str(e))

        threading.Thread(target=go, daemon=True).start()

    def _sign_out_spotify(self, _sender) -> None:
        spotify_auth.clear()
        self.state.spotify_signed_in = False
        rumps.alert("Signed out", "Spotify tokens cleared from Keychain.")

    def _quit(self, _sender) -> None:
        self.worker.stop()
        rumps.quit_application()

    # ── 1Hz refresh ─────────────────────────────────────────────────────

    def _refresh(self, _timer) -> None:
        s = self.state
        if s.now_playing is not None:
            self.now_playing_item.title = f"♪ {s.now_playing.artist_name} — {s.now_playing.track_name}"
        else:
            self.now_playing_item.title = "(nothing playing)"

        rgb = None
        if s.palette is not None:
            rgb = s.palette.pick(s.settings.palette_strategy)
        self.swatch_item.title = f"{_swatch(rgb)}  {rgb if rgb else 'no color'}"

        self.strip_status_item.title = "Strip: connected" if s.strip_connected else "Strip: disconnected"
        self.spotify_status_item.title = (
            "Spotify: signed in" if s.spotify_signed_in else "Spotify: signed out"
        )
