# album-art-to-goove

macOS menu bar app that drives a **Govee H617A** LED strip from Spotify's
currently-playing track:

- Extracts a color palette from album art (k-means in RGB; vibrant / muted / dark-vibrant / dominant)
- Captures your Mac's system audio via [BlackHole](https://existential.audio/blackhole/)
  and detects beats locally using spectral-flux onset detection
- Pushes color to the strip over BLE (reverse-engineered Govee protocol — the
  H617A is not on Govee's official cloud-API supported list)

Three modes: **Solid** (smooth fade between tracks), **Pulse** (dim baseline,
flash to full color on beats), **Strobe** (alternate two palette colors on beats).

## Why local audio instead of Spotify audio-analysis?

Spotify deprecated `GET /audio-analysis`, `GET /audio-features`, and friends on
2024-11-27 for apps registered after that date. Any new Spotify app you
create today gets `403` on those endpoints, so beat data has to come from
somewhere else. BlackHole + a multi-output device captures your system audio
losslessly and works for any audio source (Apple Music, YouTube, etc.).

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## One-time setup

### 1. Install BlackHole

```bash
brew install blackhole-2ch
```

Then in **Audio MIDI Setup** (⌘Space → "Audio MIDI Setup"):

1. Click **+** → **Create Multi-Output Device**
2. Check both your speakers/headphones **and** BlackHole 2ch
3. Right-click → **Use This Device For Sound Output**

Now Spotify plays through your speakers *and* BlackHole at the same time.

### 2. Register a Spotify app

1. Go to <https://developer.spotify.com/dashboard> and create an app.
2. Add `http://127.0.0.1:8888/callback` as a Redirect URI.
3. Copy the **Client ID**.
4. Create `~/.config/aa2g/config.toml`:

   ```toml
   [spotify]
   client_id = "YOUR_CLIENT_ID_HERE"
   ```

   No client secret is needed — auth uses PKCE.

### 3. Discover your strip's BLE address

```bash
python -m aa2g.govee.ble discover
# → 1A:2B:3C:4D:5E:6F  ihoment_H617A_XXXX
```

Confirm with a write test:
```bash
python -m aa2g.govee.ble color 1A:2B:3C:4D:5E:6F 255 0 0   # red
```

If macOS prompts for Bluetooth permission, allow it in System Settings →
Privacy & Security → Bluetooth.

### 4. Grant microphone permission

The first time the app runs, macOS will prompt for microphone access (this is
how it captures BlackHole's audio). Allow it.

## Run

You can't run the app as plain `python -m aa2g` and expect Bluetooth to work —
macOS TCC will crash the process the moment it touches `BleakScanner` because
the Python interpreter has no `Info.plist` declaring why it wants Bluetooth.
Build a tiny dev `.app` bundle once and `open` that instead:

```bash
tools/build-dev-app.sh
open build/Album-Art-to-Goove.app
```

The bundle is just a launcher script + an `Info.plist` declaring
`NSBluetoothAlwaysUsageDescription` and `NSMicrophoneUsageDescription`. macOS
will prompt for each permission the first time it's needed.

The 🎵 icon appears in the menu bar. First run:

1. Click **Sign in to Spotify…** → browser → grant → returns automatically.
2. Click **Re-pair light strip…** → scans and lets you pick the H617A.
3. Play music. The menu updates with the track + color swatch, the strip
   follows the palette, and beat modes pulse with the audio.

Settings (mode, palette strategy, BLE address, BlackHole device) persist to
`~/.config/aa2g/state.json`. Spotify tokens live in macOS Keychain
(`security find-generic-password -s aa2g -a spotify_refresh_token`).

## Standalone CLI utilities

Each subsystem has a runnable entry point for debugging without the menu bar:

| Command | What it does |
|---|---|
| `python -m aa2g.govee.ble discover` | Scan for Govee H617A devices |
| `python -m aa2g.govee.ble color ADDR R G B` | Set the strip to an RGB color |
| `python -m aa2g.spotify.auth` | Run the PKCE flow and store tokens |
| `python -m aa2g.color.extract URL` | Print the palette for an image URL |

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Tests cover the BLE frame builders and XOR checksum (no hardware needed).

## File layout

```
src/aa2g/
├── __main__.py     entry: starts worker thread + menu bar
├── menu.py         rumps.App — the visible UI
├── worker.py       asyncio orchestrator on a background thread
├── state.py        shared AppState + persisted settings
├── govee/
│   ├── protocol.py 20-byte BLE frame builders (pure functions)
│   └── ble.py      bleak client with auto-reconnect + keep-alive
├── spotify/
│   ├── auth.py     PKCE OAuth + Keychain storage
│   ├── client.py   Spotify Web API client (currently-playing)
│   └── poller.py   2s polling loop, triggers palette refresh
├── color/
│   └── extract.py  album art → palette via k-means
├── audio/
│   ├── capture.py  sounddevice InputStream → asyncio queue
│   └── beats.py    spectral-flux onset detector → BeatEvent queue
└── modes/
    ├── solid.py    fade between palette colors
    ├── pulse.py    flash on beats
    └── strobe.py   alternate two colors per beat
```

## Security notes

- No Spotify client secret — PKCE only needs the Client ID.
- Refresh tokens stored in macOS Keychain via `keyring`, never on disk in plaintext.
- Scope is read-only: `user-read-currently-playing` only.
- The OAuth callback server binds to `127.0.0.1:8888` and is torn down once
  the code is captured.

## Known limitations / not implemented

- Multi-color RGBIC segments — the H617A supports per-segment color but the
  segment frame format needs more reverse-engineering. v1 sets a single color
  across the whole strip.
- `py2app` packaging — the project is installable via pip and runs from your
  venv. A signed `.app` bundle is a future step.
- Reconnect on Mac wake — handled by `connect_forever`, but you may need to
  re-toggle Bluetooth occasionally after long sleeps.
