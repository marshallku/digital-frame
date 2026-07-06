#!/usr/bin/env python3
"""Freeze/thaw the kiosk browser on Hyprland monitor hotplug events.

The frame monitor is turned on and off physically. Hyprland reports each
power transition as a `monitoradded` / `monitorremoved` event on its socket2
event stream. When the frame monitor disconnects we freeze the kiosk browser's
entire cgroup via `systemctl --user freeze`, so the slideshow stops burning
CPU/GPU while nothing is on screen. When it reconnects we thaw it and the
slideshow resumes exactly where it paused.

Configuration comes from the environment (see deploy/frame.env.example):
    FRAME_MONITOR      Hyprland output name to watch (e.g. HDMI-A-1)
    FRAME_KIOSK_UNIT   systemd --user unit to freeze/thaw
"""
import json
import os
import socket
import subprocess
import time

FRAME_MONITOR = os.environ.get("FRAME_MONITOR", "HDMI-A-1")
KIOSK_UNIT = os.environ.get("FRAME_KIOSK_UNIT", "frame-kiosk.service")


def log(msg):
    print(f"[frame-monitor-watch] {msg}", flush=True)


def systemctl(action):
    result = subprocess.run(
        ["systemctl", "--user", action, KIOSK_UNIT],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log(f"systemctl {action} {KIOSK_UNIT} failed: {result.stderr.strip()}")


def monitor_connected():
    """Whether FRAME_MONITOR is currently attached. Assume yes if hyprctl fails,
    so an unknown state shows photos rather than freezing a live screen."""
    try:
        out = subprocess.run(
            ["hyprctl", "-j", "monitors"], capture_output=True, text=True, check=True
        ).stdout
        return any(m.get("name") == FRAME_MONITOR for m in json.loads(out))
    except (OSError, ValueError, subprocess.CalledProcessError):
        return True


def reconcile():
    """Match the browser's frozen state to the monitor's current power state, so
    a watcher (re)start with the monitor already off keeps the kiosk paused."""
    if monitor_connected():
        systemctl("thaw")
    else:
        systemctl("freeze")


def resolve_socket():
    """Return the newest Hyprland `.socket2.sock` path, or None if unavailable."""
    base = f"{os.environ['XDG_RUNTIME_DIR']}/hypr"
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig:
        candidate = f"{base}/{sig}/.socket2.sock"
        if os.path.exists(candidate):
            return candidate
    try:
        dirs = [os.path.join(base, d) for d in os.listdir(base)]
    except FileNotFoundError:
        return None
    dirs = [d for d in dirs if os.path.exists(os.path.join(d, ".socket2.sock"))]
    if not dirs:
        return None
    return os.path.join(max(dirs, key=os.path.getmtime), ".socket2.sock")


def handle(event):
    name, _, arg = event.partition(">>")
    if arg != FRAME_MONITOR:
        return
    if name == "monitorremoved":
        log(f"{FRAME_MONITOR} disconnected -> freeze {KIOSK_UNIT}")
        systemctl("freeze")
    elif name == "monitoradded":
        log(f"{FRAME_MONITOR} connected -> thaw {KIOSK_UNIT}")
        systemctl("thaw")


def run():
    path = resolve_socket()
    if not path:
        log("no Hyprland socket found; retrying")
        return
    log(f"listening on {path} for monitor '{FRAME_MONITOR}'")
    # Sync to the monitor's actual state; a restart mustn't wake a paused frame.
    reconcile()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)
    with sock:
        buf = b""
        while True:
            data = sock.recv(4096)
            if not data:
                log("socket closed; reconnecting")
                return
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                handle(line.decode(errors="replace"))


def main():
    while True:
        try:
            run()
        except OSError as err:
            log(f"error: {err}")
        time.sleep(2)


if __name__ == "__main__":
    main()
