#!/bin/bash
# Build a minimal .app bundle around the venv interpreter so macOS TCC will
# prompt for (rather than crash on) Bluetooth and Microphone access.
# Not a redistributable bundle — py2app is the path for that. This is only
# enough to get past the privacy gate during development.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PY="$ROOT/.venv/bin/python"
APP_DIR="$ROOT/build/Album-Art-to-Goove.app"
BUNDLE_ID="dev.aa2g.menubar"

if [[ ! -x "$VENV_PY" ]]; then
  echo "no venv at $VENV_PY — run: python3 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

cat > "$APP_DIR/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Album-Art-to-Goove</string>
  <key>CFBundleDisplayName</key><string>Album-Art-to-Goove</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>aa2g-launcher</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>
  <key>NSBluetoothAlwaysUsageDescription</key>
  <string>Album-Art-to-Goove needs Bluetooth to control your Govee H617A LED strip.</string>
  <key>NSBluetoothPeripheralUsageDescription</key>
  <string>Album-Art-to-Goove needs Bluetooth to control your Govee H617A LED strip.</string>
  <key>NSMicrophoneUsageDescription</key>
  <string>Album-Art-to-Goove reads system audio through BlackHole to detect beats.</string>
</dict>
</plist>
EOF

cat > "$APP_DIR/Contents/MacOS/aa2g-launcher" <<EOF
#!/bin/bash
# No args   → launch the menu bar app
# Has args  → pass them through to python -m, so CLI subcommands inherit
#              the bundle's TCC identity (required for any Bluetooth access).
if [ \$# -eq 0 ]; then
  exec "$VENV_PY" -m aa2g
else
  exec "$VENV_PY" -m "\$@"
fi
EOF
chmod +x "$APP_DIR/Contents/MacOS/aa2g-launcher"

# Ad-hoc sign so TCC tracks this bundle as a stable identity.
codesign --force --deep --sign - "$APP_DIR"

echo "built: $APP_DIR"
echo "run:   open '$APP_DIR'"
