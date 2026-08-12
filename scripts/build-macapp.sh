#!/bin/bash
# Builds Collaborate.app — a real, double-clickable macOS app bundle with
# its own embedded Python runtime, so people running it need neither
# Python nor pip installed. Unsigned: there's no Apple Developer ID here
# to sign/notarize with, so the first launch shows Gatekeeper's "can't
# verify developer" warning — right-click > Open (once) clears it.

set -euo pipefail
cd "$(dirname "$0")/.."

BUILD_VENV=".macapp-build-venv"
rm -rf "$BUILD_VENV" macapp/build macapp/dist
python3 -m venv "$BUILD_VENV"
"$BUILD_VENV/bin/pip" install -q --upgrade pip

# A REGULAR install, not `pip install -e .` — py2app's modulegraph needs
# real files sitting in site-packages to freeze into the bundle; an
# editable install's import-hook indirection isn't something it resolves.
"$BUILD_VENV/bin/pip" install -q ".[menubar]" py2app

(cd macapp && "../$BUILD_VENV/bin/python" setup.py py2app)

rm -rf "$BUILD_VENV"

echo
echo "Built: macapp/dist/Collaborate.app"
echo "Drag it to /Applications, then double-click it."
echo "First launch: right-click > Open (unsigned build) instead of double-clicking."
