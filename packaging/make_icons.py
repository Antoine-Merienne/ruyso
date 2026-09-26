"""
One master image in, every icon format the installers need out.

Run it by hand after changing the artwork, and commit what it writes::

    .venv/bin/python packaging/make_icons.py

The outputs are committed rather than built in CI because ``iconutil``
is macOS-only: generating them on the runners would mean either an
artifact hop between jobs for 200 KB of static files, or a second
icon library on the Windows and Linux runners. The artwork changes
approximately never.

Master: ``packaging/icons/icon.png`` -- 1024x1024, square, transparent.
macOS convention wants the artwork inside roughly 80% of the canvas
with transparent margin; a full-bleed square reads as oversized next
to every other icon in the dock.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ICONS = HERE / "icons"
MASTER = ICONS / "icon.png"

#: Also shipped inside the package, for ``QApplication.setWindowIcon``:
#: the PyPI install has no bundle to take an icon from.
IN_APP_ICON = HERE.parent / "src" / "ruyso_app" / "ui" / "assets" / "app-icon.png"

#: Windows wants every size inside the one .ico; these are the ones
#: Explorer actually picks from.
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

#: What ``iconutil`` expects to find in an .iconset directory.
ICNS_SIZES = [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
]


def _load_master() -> Image.Image:
    """
    The master, at whatever size it was drawn.

    Deliberately *not* normalised to 1024 first: every output is then
    resampled from the original pixels rather than from an upscale, so a
    master smaller than 1024 only costs sharpness in the one slot that
    genuinely needs 1024 (macOS ``icon_512x512@2x``).
    """
    if not MASTER.exists():
        sys.exit(f"no master icon at {MASTER} -- put a square PNG there first")
    image = Image.open(MASTER).convert("RGBA")
    if image.width != image.height:
        sys.exit(f"master must be square; this one is {image.size}")
    if image.width < 1024:
        print(
            f"note: master is {image.width}px. macOS asks for 1024 -- the "
            f"largest icon will be upscaled {1024 / image.width:.2f}x and "
            "look slightly soft on a Retina display."
        )
    return image


def _resized(image: Image.Image, size: int) -> Image.Image:
    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    image = _load_master()
    ICONS.mkdir(parents=True, exist_ok=True)

    # Windows
    image.save(ICONS / "icon.ico", sizes=ICO_SIZES)

    # Linux / the .desktop entry / the AppImage
    for size in (256, 512):
        _resized(image, size).save(ICONS / f"icon-{size}.png")

    # In-app, so the PyPI install has a window icon too
    IN_APP_ICON.parent.mkdir(parents=True, exist_ok=True)
    _resized(image, 512).save(IN_APP_ICON)

    # macOS: build an .iconset, then let iconutil turn it into .icns
    iconset = ICONS / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    for name, size in ICNS_SIZES:
        _resized(image, size).save(iconset / name)
    if sys.platform == "darwin":
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(ICONS / "icon.icns")],
            check=True,
        )
        for leftover in iconset.iterdir():
            leftover.unlink()
        iconset.rmdir()
    else:
        print(f"not macOS: left {iconset} in place, run iconutil there to get .icns")

    written = sorted(p.name for p in ICONS.iterdir())
    print(f"wrote {', '.join(written)} and {IN_APP_ICON.relative_to(HERE.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
