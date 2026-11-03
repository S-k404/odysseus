#!/bin/bash
# Build a native macOS app + .dmg for Odysseus.
#
#   ./build-macos-app.sh
#
# Produces:
#   dist/Odysseus.app   — Native macOS desktop application (Swift WKWebView + backend launcher)
#   dist/Odysseus.dmg   — Drag-to-Applications disk image
#   /Applications/Odysseus.app — Installed directly to Applications folder
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Odysseus"
INSTALL_DIR="$REPO_DIR"
PORT="${ODYSSEUS_PORT:-7860}"
DIST="$REPO_DIR/dist"
APP="$DIST/$APP_NAME.app"

echo "Building $APP_NAME.app for macOS"
echo "  install dir: $INSTALL_DIR"
echo "  port:        $PORT"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# ── Icon (best effort) — center-crop the branding image to a square .icns ──
if [ -f "$REPO_DIR/assets/branding/odysseus.jpg" ] && command -v sips >/dev/null 2>&1; then
  TMPIMG="$(mktemp -d)"
  sips -c 720 720 "$REPO_DIR/assets/branding/odysseus.jpg" --out "$TMPIMG/sq.png" >/dev/null 2>&1 || cp "$REPO_DIR/assets/branding/odysseus.jpg" "$TMPIMG/sq.png"
  sips -z 512 512 "$TMPIMG/sq.png" --out "$TMPIMG/icon.png" >/dev/null 2>&1
  if sips -s format icns "$TMPIMG/icon.png" --out "$APP/Contents/Resources/odysseus.icns" >/dev/null 2>&1; then
    echo "  icon:        odysseus.icns"
  else
    echo "  icon:        (skipped — conversion failed)"
  fi
  rm -rf "$TMPIMG"
else
  echo "  icon:        (skipped — no assets/branding/odysseus.jpg)"
fi

# ── Info.plist ──
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>            <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>     <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>      <string>com.odysseus.desktop</string>
    <key>CFBundleVersion</key>         <string>1.0</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundlePackageType</key>     <string>APPL</string>
    <key>CFBundleExecutable</key>      <string>$APP_NAME</string>
    <key>CFBundleIconFile</key>        <string>odysseus</string>
    <key>LSMinimumSystemVersion</key>  <string>11.0</string>
    <key>NSHighResolutionCapable</key> <true/>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsArbitraryLoads</key>
        <true/>
        <key>NSAllowsLocalNetworking</key>
        <true/>
    </dict>
    <key>LSUIElement</key>             <false/>
</dict>
</plist>
PLIST

# ── Native Swift App or Shell Launcher ──
SWIFT_SRC="$REPO_DIR/swift/OdysseusApp.swift"
if command -v swiftc >/dev/null 2>&1 && [ -f "$SWIFT_SRC" ]; then
  echo "  compiling native macOS desktop binary (Swift + WKWebView + menu bar stats)..."
  swiftc -O -framework Cocoa -framework WebKit -framework SwiftUI \
    "$REPO_DIR/swift/OdysseusApp.swift" "$REPO_DIR/swift/MenuBarStats.swift" "$REPO_DIR/swift/MenuBarView.swift" "$REPO_DIR/swift/main.swift" \
    -o "$APP/Contents/MacOS/$APP_NAME"
else
  # No Swift toolchain: fall back to a shell launcher that opens the UI in a
  # browser app window (placeholders filled in after the heredoc).
  echo "  fallback: generating shell app launcher..."
cat > "$APP/Contents/MacOS/$APP_NAME.tmpl" <<'LAUNCHER'
#!/bin/bash
# Odysseus.app — start the local server and open the UI in an app window.
INSTALL_DIR="__INSTALL_DIR__"
PORT="__PORT__"
URL="http://127.0.0.1:${PORT}"
# uvicorn is started with --port below, but APP_PORT is what the app itself
# reads when it needs to build a URL for this instance (internal_api_base(),
# companion pairing, the MCP OAuth callback), so export it as well.
export APP_PORT="$PORT"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

UVICORN="$INSTALL_DIR/.venv/bin/uvicorn"
[ -x "$UVICORN" ] || UVICORN="$INSTALL_DIR/venv/bin/uvicorn"
LOG="$INSTALL_DIR/logs/odysseus-app.log"

notify() { /usr/bin/osascript -e "display notification \"$1\" with title \"Odysseus\"" >/dev/null 2>&1; }
die_gui() {
  /usr/bin/osascript -e "display dialog \"$1\" with title \"Odysseus\" buttons {\"OK\"} default button 1 with icon stop" >/dev/null 2>&1
  exit 1
}

[ -x "$UVICORN" ] || die_gui "Odysseus isn't set up yet. Open Terminal and run:

cd $INSTALL_DIR
python3.11 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python setup.py"

# Open the UI in a chrome-less app window (Chromium browsers), else default browser.
open_ui() {
  local b base exe bin
  for b in "Google Chrome" "Microsoft Edge" "Brave Browser" "Chromium"; do
    for base in "/Applications" "$HOME/Applications"; do
      if [ -d "$base/$b.app" ]; then
        exe="$(/usr/bin/defaults read "$base/$b.app/Contents/Info" CFBundleExecutable 2>/dev/null)"
        bin="$base/$b.app/Contents/MacOS/$exe"
        if [ -x "$bin" ]; then
          "$bin" --app="$URL" --new-window >/dev/null 2>&1 &
          return 0
        fi
      fi
    done
  done
  /usr/bin/open "$URL"
}

mkdir -p "$INSTALL_DIR/logs"

# Already running? Just open the UI.
if /usr/bin/curl -s -o /dev/null --max-time 2 "$URL"; then
  open_ui
  exit 0
fi

notify "Starting…"
cd "$INSTALL_DIR" || die_gui "Install folder not found: $INSTALL_DIR"
if [ "$(uname -m)" = "arm64" ]; then
  arch -arm64 "$UVICORN" app:app --host 127.0.0.1 --port "$PORT" >>"$LOG" 2>&1 &
else
  "$UVICORN" app:app --host 127.0.0.1 --port "$PORT" >>"$LOG" 2>&1 &
fi
SERVER_PID=$!

# Quitting the app stops the server it started.
trap 'kill $SERVER_PID 2>/dev/null; exit 0' TERM INT

# Wait for readiness (first run downloads an embedding model — allow ~2 min).
READY=0
for i in $(seq 1 120); do
  /usr/bin/curl -s -o /dev/null --max-time 2 "$URL" && { READY=1; break; }
  kill -0 "$SERVER_PID" 2>/dev/null || die_gui "Odysseus failed to start. Log:
$LOG"
  sleep 1
done

if [ "$READY" = "1" ]; then
  open_ui
else
  notify "Odysseus is taking a while — open $URL once it finishes starting."
fi
wait "$SERVER_PID"
LAUNCHER

sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" -e "s|__PORT__|$PORT|g" \
    "$APP/Contents/MacOS/$APP_NAME.tmpl" > "$APP/Contents/MacOS/$APP_NAME"
rm -f "$APP/Contents/MacOS/$APP_NAME.tmpl"
chmod +x "$APP/Contents/MacOS/$APP_NAME"
fi

touch "$APP"

# ── Code Signing ──
if command -v codesign >/dev/null 2>&1; then
  echo "  signing application bundle with local ad-hoc identity..."
  codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
fi

# ── Install to /Applications ──
echo "Installing to /Applications/$APP_NAME.app"
rm -rf "/Applications/$APP_NAME.app"
cp -R "$APP" "/Applications/$APP_NAME.app"
if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep -s - "/Applications/$APP_NAME.app" >/dev/null 2>&1 || true
fi

# ── .dmg (drag-to-Applications) ──
echo "Packaging dist/$APP_NAME.dmg"
STAGE="$(mktemp -d)/dmg"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DIST/$APP_NAME.dmg"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DIST/$APP_NAME.dmg" >/dev/null
rm -rf "$STAGE"

echo ""
echo "✔ Odysseus for macOS is built and installed!"
echo "  Installed App: /Applications/$APP_NAME.app"
echo "  Dist App:      $APP"
echo "  Dist DMG:      $DIST/$APP_NAME.dmg"
echo ""
echo "Launch Odysseus: open '/Applications/$APP_NAME.app'"
