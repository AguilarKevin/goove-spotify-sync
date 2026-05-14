#!/bin/bash
# Run aa2g CLI subcommands through the dev .app bundle so macOS TCC
# recognises the bundle's NSBluetoothAlwaysUsageDescription / NSMicrophoneUsageDescription.
#
# Invoking the bundle's launcher script directly from a shell does NOT
# inherit the bundle's TCC identity — only `open` does. This wrapper handles
# that and pipes stdout/stderr back so the CLI feels normal.
#
# Usage:
#   tools/aa2g-cli.sh govee.ble discover
#   tools/aa2g-cli.sh govee.ble color <addr-or-uuid> <r> <g> <b>
#   tools/aa2g-cli.sh color.extract <image-url>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$SCRIPT_DIR/../build/Album-Art-to-Goove.app"
APP="$(cd "$(dirname "$APP")" && pwd)/$(basename "$APP")"

if [[ ! -d "$APP" ]]; then
  echo "no dev .app at $APP — run tools/build-dev-app.sh first" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  echo "usage: $0 <aa2g-submodule> [args...]" >&2
  echo "example: $0 govee.ble discover" >&2
  exit 2
fi

OUT="$(mktemp)"
ERR="$(mktemp)"
trap 'rm -f "$OUT" "$ERR"' EXIT

open -W -a "$APP" --stdout "$OUT" --stderr "$ERR" --args "aa2g.$@"
status=$?

/bin/cat "$OUT"
/bin/cat "$ERR" >&2
exit $status
