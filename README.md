# Digital Frame

An ultralight digital photo frame. A single-file Python server (standard library only)
turns any device with a browser into a fullscreen, auto-advancing slideshow with
crossfade + Ken Burns animations.

- **Zero required dependencies** — pure `http.server`. If [Pillow] happens to be
  installed, large originals are downscaled once and cached so a low-power frame
  device doesn't pull multi-megabyte files every cycle.
- **Fullscreen for any aspect ratio** — landscape and portrait shots are shown
  `object-fit: contain`, with a blurred, darkened backdrop filling the letterbox gaps.
- **Digital-frame animations** — slow Ken Burns zoom/pan on each photo and a soft
  crossfade between them, with a subtle clock overlay.

## Usage

```bash
python3 frame.py "/path/to/pictures"
```

Then open the printed URL (e.g. `http://<lan-ip>:8080`) on the frame device and hit
<kbd>F</kbd> for fullscreen.

### Options

| Flag                | Default   | Description                                                              |
| ------------------- | --------- | ------------------------------------------------------------------------ |
| `dir`               | —         | Directory of images to display (required).                               |
| `--interval`        | `8`       | Seconds each image is shown.                                             |
| `--transition`      | `1.5`     | Crossfade duration in seconds.                                           |
| `--port`            | `8080`    | Port to listen on.                                                       |
| `--host`            | `0.0.0.0` | Interface to bind.                                                       |
| `--sequential`      | off       | Advance in order instead of picking each next image at random.           |
| `--shuffle`         | off       | Randomize the initial scan order (mostly relevant with `--sequential`).  |
| `--recursive`, `-r` | off       | Scan subdirectories too.                                                 |
| `--no-kenburns`     | off       | Disable the slow zoom/pan animation.                                     |
| `--max-width`       | `2560`    | Downscale originals to this width (needs Pillow; `0` = serve originals). |
| `--quality`         | `85`      | JPEG quality for downscaled images.                                      |

By default the next photo is picked at random (the back arrow still revisits what you
just saw). Pass `--sequential` for straight in-order playback.

Example — a recursive slideshow with a 5s interval:

```bash
python3 frame.py ~/Pictures -r --interval 5
```

## Controls

| Input                        | Action            |
| ---------------------------- | ----------------- |
| <kbd>Space</kbd>             | Pause / resume    |
| <kbd>←</kbd> / <kbd>→</kbd>  | Previous / next   |
| <kbd>F</kbd> or double-click | Toggle fullscreen |
| Click left / right           | Previous / next   |

## How it works

- The server scans the target directory for images (`.jpg .jpeg .png .gif .webp .bmp .avif`),
  rescanning at most every 30s so newly added photos appear without a restart.
- Images are addressed by index (`/img/0`, `/img/1`, …), so unicode filenames and path
  traversal are non-issues.
- Responses carry `ETag` / `Cache-Control`, and downscaled variants are cached under the
  system temp dir keyed by `(path, mtime, width)`.
- The frontend picks the next photo at random (or in order with `--sequential`), keeping a
  bounded trail so the back arrow can revisit; it preloads each image and skips unreadable files.
- Entering fullscreen hides the keyboard-hint bar for a clean kiosk display.

## Kiosk on Arch Linux + Hyprland

`deploy/` turns a Hyprland machine into a dedicated frame: the server, a
fullscreen kiosk browser, and a monitor-power watcher, all as systemd `--user`
units. Turning the monitor off freezes the browser (CPU/GPU go idle); turning it
back on thaws it and the slideshow resumes where it paused — driven natively by
Hyprland's `monitoradded` / `monitorremoved` hotplug events.

```bash
deploy/install.sh                      # symlink + enable the user units
$EDITOR ~/.config/digital-frame/frame.env   # set FRAME_DIR and FRAME_MONITOR
# add to ~/.config/hypr/hyprland.conf:
#   source = /path/to/digital-frame/deploy/hyprland-frame.conf
```

Then reload Hyprland (or `systemctl --user start digital-frame.target`).

**Find your monitor name** with `hyprctl monitors` and put it in `FRAME_MONITOR`.

**Verify power-off is detected** (HDMI is less reliable than DisplayPort — some
panels keep the link alive when off). Watch the events while you toggle the
monitor:

```bash
python3 - <<'PY'
import os, socket
sig = os.environ["HYPRLAND_INSTANCE_SIGNATURE"]
path = f"{os.environ['XDG_RUNTIME_DIR']}/hypr/{sig}/.socket2.sock"
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(path)
print("watching — toggle the monitor, Ctrl-C to stop")
while (data := s.recv(4096)):
    for line in data.decode(errors="replace").splitlines():
        if "monitor" in line:
            print(line)
PY
```

If `monitorremoved>>…` / `monitoradded>>…` appear when you power the monitor off
and on, the freeze/thaw flow works. If nothing appears, the monitor never
disconnects — full system suspend won't wake on monitor power either, so a frame
that idles the display (the default here) is the right call.

Notes:

- `systemctl --user freeze` uses the cgroup freezer, so the browser and every
  child process stop together and resume instantly on `thaw`.
- The kiosk window keeps the screen awake via a Hyprland `idleinhibit` rule, so
  `hypridle` won't blank the frame mid-view.
- Full-PC suspend on monitor-off is intentionally not used: HDMI/DP hotplug is
  not a wake source, so the PC could not reliably wake on monitor power-on.

## Tests

```bash
python3 test_frame.py
```

[Pillow]: https://python-pillow.org/
