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
| `--shuffle`         | off       | Randomize image order.                                                   |
| `--recursive`, `-r` | off       | Scan subdirectories too.                                                 |
| `--no-kenburns`     | off       | Disable the slow zoom/pan animation.                                     |
| `--max-width`       | `2560`    | Downscale originals to this width (needs Pillow; `0` = serve originals). |
| `--quality`         | `85`      | JPEG quality for downscaled images.                                      |

Example — a shuffled, recursive slideshow with a 5s interval:

```bash
python3 frame.py ~/Pictures -r --shuffle --interval 5
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
- The frontend preloads the next image before every crossfade and skips unreadable files.

## Tests

```bash
python3 test_frame.py
```

[Pillow]: https://python-pillow.org/
