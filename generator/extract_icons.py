#!/usr/bin/env python3
"""
Re-extract the Samsung panel icons in assets/icons/ from Samsung's user manuals.

You don't need this to build the cards: the icons are already in the repository. It's here to show
where they came from, and to redo them (for example at a different resolution).

The control-panel diagrams in the two manuals are vector artwork. Each icon is rendered from its
page at 1200 dpi, anything touching the crop window's edge (neighbouring labels and leader lines)
is dropped, and the result is saved as dark ink on white, as it appears in the manual.

Usage:
  pip install -r generator/requirements-extract.txt
  python generator/extract_icons.py            # downloads the manuals into manuals/ if missing
"""
import argparse
import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
DPI = 1200

# Crop positions are specific to these exact files, so they are pinned by SHA-256.
# clip_px is the control-panel diagram on the page, in 1200 dpi pixels (x, y, w, h).
# Icon windows are in 1/6-scale pixels relative to the clip (x0, y0, x1, y1).
MANUALS = {
    'washer': dict(
        file='washer-manual.pdf',
        url='https://downloadcenter.samsung.com/content/UM/202604/20260408143907954/Web_IB_D-PJT_WASHER-MD_SimpleUX_EN_v1.pdf',
        sha256='0f60add258fa3da0c8250cddaddd435dd0f7d5b8c89b64add912f25f53a52b27',
        page=34, clip_px=(1090, 2050, 6040, 1780),
        icons={'power': (20, 125, 62, 170), 'start-pause': (330, 125, 375, 170),
               'smart-control': (900, 114, 924, 148), 'door-lock': (866, 146, 894, 174),
               'child-lock': (899, 146, 926, 174), 'temperature': (640, 194, 668, 226),
               'spin': (798, 194, 832, 226), 'hand': (878, 192, 912, 226),
               'smart-control-button': (954, 126, 988, 166)}),
    'dryer': dict(
        file='dryer-manual.pdf',
        url='https://downloadcenter.samsung.com/content/UM/202304/20230425115323308/DC68-04400M-00_IB_B-PJT_DV9400B_SimpleUX_EN_pdf.pdf',
        sha256='d5682f81974da77f17d2db44b6192ec3b897c9f889a7ac7ef0baa18747c23741',
        page=29, clip_px=(820, 1780, 6050, 1990),
        icons={'dry-level': (622, 210, 662, 240), 'wrinkle-prevent': (704, 208, 744, 240)}),
}


def fetch(manual_dir):
    manual_dir.mkdir(parents=True, exist_ok=True)
    for dev, m in MANUALS.items():
        dest = manual_dir / m['file']
        if not dest.exists():
            print(f'Downloading the {dev} manual from Samsung...')
            req = urllib.request.Request(m['url'], headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, 'wb') as f:
                shutil.copyfileobj(r, f)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if digest != m['sha256']:
            sys.exit(f'{dest.name} is not the expected version (sha256 {digest[:12]}...). '
                     'Delete it and run again.')


def extract(manual_dir):
    """Returns {name: 'L' image of ink intensity (0 = paper, 255 = full ink)}."""
    icons = {}
    for dev, m in MANUALS.items():
        page = pymupdf.open(manual_dir / m['file'])[m['page'] - 1]
        x, y, w, h = m['clip_px']; pt = 72 / DPI
        clip = pymupdf.Rect(x * pt, y * pt, (x + w) * pt, (y + h) * pt)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(DPI / 72, DPI / 72), clip=clip,
                              colorspace=pymupdf.csGRAY, alpha=False)
        ink = 255 - np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).astype(np.int32)
        for name, (x0, y0, x1, y1) in m['icons'].items():
            a = ink[y0 * 6:y1 * 6, x0 * 6:x1 * 6]
            lab, n = ndimage.label(a > 100)
            keep = np.zeros_like(a, bool)
            for i in range(1, n + 1):                       # drop anything touching the window edge
                ys, xs = np.nonzero(lab == i)
                if ys.min() == 0 or xs.min() == 0 or ys.max() == a.shape[0] - 1 or xs.max() == a.shape[1] - 1:
                    continue
                keep |= lab == i
            if not keep.any():
                sys.exit(f'Could not find the {dev} "{name}" icon in the manual.')
            keep = ndimage.binary_dilation(keep, iterations=4)
            b = np.where(keep, a, 0); ys, xs = np.nonzero(b > 100)
            b = b[ys.min() - 4:ys.max() + 5, xs.min() - 4:xs.max() + 5]
            icons[name] = Image.fromarray(np.clip(b, 0, 255).astype('uint8'))
    return icons


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--manuals', default=str(ROOT / 'manuals'), help='folder for the downloaded manuals')
    ap.add_argument('--out', default=str(ROOT / 'assets' / 'icons'), help='where to write the icons')
    a = ap.parse_args()
    manual_dir, out = Path(a.manuals), Path(a.out)
    fetch(manual_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, ink in extract(manual_dir).items():
        Image.eval(ink, lambda v: 255 - v).save(out / f'{name}.png', optimize=True)   # dark ink on white
    print(f'Wrote {sum(len(m["icons"]) for m in MANUALS.values())} icons to {out}')


if __name__ == '__main__':
    main()
