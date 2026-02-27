# simple-slideshow

A fullscreen photo slideshow that displays images from a directory, automatically advancing on a timer with smooth crossfade transitions.

## Installation

```bash
uv sync
```

## Usage

Place images in the `photos/` directory, then run:

```bash
python simple-slideshow.py
```

## Captions

A caption badge is shown at the bottom of an image when its filename begins with `$`. The `$` is stripped from the displayed text.

| Filename           | Caption shown  |
| ------------------ | -------------- |
| `$golden_gate.jpg` | `golden gate`  |
| `sunset.jpg`       | _(no caption)_ |

## Controls

| Key           | Action            |
| ------------- | ----------------- |
| `→` / `Space` | Next slide        |
| `←`           | Previous slide    |
| `P`           | Pause / resume    |
| `F`           | Toggle fullscreen |
| `Esc` / `Q`   | Quit              |

## Configuration

Settings can be changed by editing the `Config` dataclass at the top of `simple-slideshow.py`:

## Fonts

IBM Plex Sans by IBM — licensed under the SIL Open Font License 1.1.
https://github.com/IBM/plex
