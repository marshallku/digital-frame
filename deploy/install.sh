#!/usr/bin/env bash
# Install the Digital Frame systemd --user units on this device.
# Safe to run on the target frame device; it installs + enables but does not
# start anything (no browser is launched here). Run the printed start command,
# or just reboot after adding the Hyprland snippet.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/digital-frame"

mkdir -p "$UNIT_DIR" "$CFG_DIR"

for unit in digital-frame.service frame-kiosk.service frame-monitor-watch.service digital-frame.target; do
    ln -sf "$REPO/deploy/$unit" "$UNIT_DIR/$unit"
done

if [ ! -e "$CFG_DIR/frame.env" ]; then
    sed "s#@REPO@#$REPO#g" "$REPO/deploy/frame.env.example" > "$CFG_DIR/frame.env"
    echo "Wrote default config: $CFG_DIR/frame.env"
    echo "  -> edit FRAME_DIR (photo folder) and FRAME_MONITOR (see: hyprctl monitors)"
else
    echo "Kept existing config: $CFG_DIR/frame.env"
fi

systemctl --user daemon-reload
systemctl --user enable digital-frame.service frame-kiosk.service frame-monitor-watch.service

cat <<EOF

Installed. Next:
  1. Edit $CFG_DIR/frame.env  (FRAME_DIR, FRAME_MONITOR).
  2. Add the Hyprland snippet:  source = $REPO/deploy/hyprland-frame.conf
     to ~/.config/hypr/hyprland.conf, then reload Hyprland.
  3. Start now without rebooting:
       systemctl --user import-environment WAYLAND_DISPLAY HYPRLAND_INSTANCE_SIGNATURE XDG_CURRENT_DESKTOP PATH
       systemctl --user start digital-frame.target
EOF
