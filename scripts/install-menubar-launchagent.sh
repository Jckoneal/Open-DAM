#!/bin/bash
# Installs a LaunchAgent so the Open-DAM menu bar app starts automatically
# when you log in (macOS only). Run it once per machine.

set -euo pipefail

DAM_PATH="${1:-$(command -v dam || true)}"

if [ -z "$DAM_PATH" ]; then
  echo "Could not find the 'dam' command on your PATH." >&2
  echo "Run: $0 /full/path/to/dam" >&2
  exit 1
fi
if [ ! -x "$DAM_PATH" ]; then
  echo "'$DAM_PATH' is not an executable file." >&2
  exit 1
fi

LABEL="com.opendam.menubar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$DAM_PATH</string>
        <string>menubar</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/open-dam-menubar.log</string>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/open-dam-menubar.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "Installed: $PLIST"
echo "The menu bar app will now start automatically at login, and has started now."
echo "Logs: ~/Library/Logs/open-dam-menubar.log"
echo
echo "To remove: launchctl unload $PLIST && rm $PLIST"
