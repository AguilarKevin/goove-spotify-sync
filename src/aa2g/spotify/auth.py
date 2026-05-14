"""Spotify OAuth via PKCE. Tokens are stored in the macOS Keychain.

Scope is read-only (`user-read-currently-playing`). No client secret is
required — PKCE replaces it with a per-request code challenge.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import httpx
import keyring

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "user-read-currently-playing"

KEYRING_SERVICE = "aa2g"
REFRESH_KEY = "spotify_refresh_token"
ACCESS_KEY = "spotify_access_token"
EXPIRY_KEY = "spotify_access_expiry"

CONFIG_DIR = Path.home() / ".config" / "aa2g"
CONFIG_PATH = CONFIG_DIR / "config.toml"


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: float

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - 30  # 30s safety margin


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def read_client_id() -> str:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"missing {CONFIG_PATH}. Create it with:\n\n"
            f"  [spotify]\n  client_id = \"YOUR_CLIENT_ID\"\n\n"
            f"Register an app at https://developer.spotify.com/dashboard and add\n"
            f"  {REDIRECT_URI}\nas a Redirect URI."
        )
    # Minimal TOML reader: only one line of interest, avoid bringing in tomli on <3.11.
    import tomllib
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)["spotify"]["client_id"]


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    captured: dict[str, str] = {}

    def do_GET(self) -> None:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.captured = {k: v[0] for k, v in params.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if "code" in _CallbackHandler.captured:
            self.wfile.write(b"<h1>Signed in.</h1><p>You can close this tab.</p>")
        else:
            self.wfile.write(b"<h1>Auth failed.</h1>")

    def log_message(self, *args) -> None:
        pass  # silence


def _run_callback_server(state: str, timeout: float = 120.0) -> dict[str, str]:
    server = http.server.HTTPServer(("127.0.0.1", 8888), _CallbackHandler)
    server.timeout = 1.0
    deadline = time.time() + timeout
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        while time.time() < deadline:
            if _CallbackHandler.captured.get("state") == state:
                return _CallbackHandler.captured
            time.sleep(0.2)
        raise TimeoutError("OAuth callback timed out")
    finally:
        server.shutdown()
        server.server_close()


def _store(tokens: Tokens) -> None:
    keyring.set_password(KEYRING_SERVICE, REFRESH_KEY, tokens.refresh_token)
    keyring.set_password(KEYRING_SERVICE, ACCESS_KEY, tokens.access_token)
    keyring.set_password(KEYRING_SERVICE, EXPIRY_KEY, str(tokens.expires_at))


def _load() -> Tokens | None:
    refresh = keyring.get_password(KEYRING_SERVICE, REFRESH_KEY)
    access = keyring.get_password(KEYRING_SERVICE, ACCESS_KEY)
    expiry_s = keyring.get_password(KEYRING_SERVICE, EXPIRY_KEY)
    if not (refresh and access and expiry_s):
        return None
    return Tokens(access_token=access, refresh_token=refresh, expires_at=float(expiry_s))


def clear() -> None:
    for key in (REFRESH_KEY, ACCESS_KEY, EXPIRY_KEY):
        try:
            keyring.delete_password(KEYRING_SERVICE, key)
        except keyring.errors.PasswordDeleteError:
            pass


def sign_in() -> Tokens:
    """Run the PKCE flow. Opens a browser and blocks until callback returns."""
    client_id = read_client_id()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    log.info("opening browser for Spotify sign-in…")
    webbrowser.open(url)
    captured = _run_callback_server(state)
    if "code" not in captured:
        raise RuntimeError(f"sign-in failed: {captured}")
    with httpx.Client(timeout=10) as http_client:
        resp = http_client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": captured["code"],
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        resp.raise_for_status()
        body = resp.json()
    tokens = Tokens(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=time.time() + body["expires_in"],
    )
    _store(tokens)
    return tokens


def refresh(tokens: Tokens) -> Tokens:
    client_id = read_client_id()
    with httpx.Client(timeout=10) as http_client:
        resp = http_client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
                "client_id": client_id,
            },
        )
        resp.raise_for_status()
        body = resp.json()
    new_tokens = Tokens(
        access_token=body["access_token"],
        # Spotify may or may not rotate the refresh token; keep the old one if absent.
        refresh_token=body.get("refresh_token", tokens.refresh_token),
        expires_at=time.time() + body["expires_in"],
    )
    _store(new_tokens)
    return new_tokens


def get_valid_tokens() -> Tokens | None:
    """Return tokens that are guaranteed-fresh, or None if not signed in."""
    tokens = _load()
    if tokens is None:
        return None
    if tokens.expired:
        return refresh(tokens)
    return tokens


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    tokens = sign_in()
    print(json.dumps({
        "stored": True,
        "expires_in_s": int(tokens.expires_at - time.time()),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
