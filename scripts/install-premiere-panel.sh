#!/bin/bash
# Installs the Open-DAM panel into Premiere Pro (macOS).
#
# CEP extensions live in ~/Library/Application Support/Adobe/CEP/extensions.
# The panel is unsigned, so PlayerDebugMode must be enabled for the CSXS
# runtime versions Premiere might use — without it, Premiere silently
# refuses to load unsigned panels.

set -euo pipefail

SRC="$(cd "$(dirname "$0")/../cep/com.opendam.panel" && pwd)"
DEST="$HOME/Library/Application Support/Adobe/CEP/extensions/com.opendam.panel"

mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
cp -R "$SRC" "$DEST"

for v in 10 11 12; do
  defaults write "com.adobe.CSXS.$v" PlayerDebugMode 1
done
# cfprefsd caches defaults; restart it so the change takes effect now.
killall cfprefsd 2>/dev/null || true

echo "Installed to: $DEST"
echo
echo "Now (re)start Premiere Pro and open:  Window > Extensions > Open-DAM"
