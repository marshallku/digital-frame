#!/usr/bin/env bash
# Launch a browser in kiosk mode pointing at the digital-frame server.
# Prefers a Chromium-family browser (best kiosk flags + settable window class),
# falls back to Firefox.
set -euo pipefail

URL="${FRAME_URL:-http://localhost:8080}"
CLASS="${FRAME_CLASS:-digital-frame}"
PROFILE="${XDG_RUNTIME_DIR:-/tmp}/frame-kiosk-profile"

# Wait until the server actually answers before opening the browser, so the
# kiosk never lands on a connection-refused error page during boot. On timeout
# we exit non-zero (set -e aborts before launch) and systemd restarts us, rather
# than parking an unattended frame on an error page.
python3 - "$URL" <<'PY'
import sys, time, urllib.request
url = sys.argv[1]
for _ in range(240):
    try:
        urllib.request.urlopen(url, timeout=1)
        sys.exit(0)
    except Exception:
        time.sleep(0.5)
sys.exit(1)
PY

find_chromium() {
    for bin in brave brave-browser chromium chromium-browser google-chrome-stable google-chrome; do
        if command -v "$bin" >/dev/null 2>&1; then
            echo "$bin"
            return 0
        fi
    done
    return 1
}

if chromium=$(find_chromium); then
    exec "$chromium" \
        --kiosk \
        --app="$URL" \
        --class="$CLASS" \
        --user-data-dir="$PROFILE" \
        --ozone-platform-hint=auto \
        --start-fullscreen \
        --noerrdialogs \
        --disable-infobars \
        --disable-session-crashed-bubble \
        --disable-features=Translate \
        --disable-pinch \
        --overscroll-history-navigation=0 \
        --check-for-update-interval=31536000
elif command -v firefox >/dev/null 2>&1; then
    # Firefox can't set an X11/wayland class from the CLI; adjust the Hyprland
    # window rule to match `class:^(firefox)$` if you go this route.
    exec firefox --kiosk "$URL"
else
    echo "No supported browser found (brave / chromium / chrome / firefox)." >&2
    exit 1
fi
