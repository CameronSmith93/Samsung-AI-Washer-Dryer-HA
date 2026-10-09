#!/usr/bin/env python3
"""
Build the Samsung washer / dryer display replicas for Home Assistant.

Writes a folder laid out like Home Assistant's /config folder:
  www/samsung-laundry/                    every image the cards need (rendered at 3x for sharp screens)
  packages/samsung_laundry_package.yaml   template sensors the cards read
  cards/washer-card.yaml, dryer-card.yaml picture-elements cards to paste into a dashboard

The panel icons come from assets/icons/ (Samsung's artwork, cut from their user manuals by
generator/extract_icons.py). The appliance photos default to images/washer.png and images/dryer.png.

Usage:
  python generator/build.py [--washer-entities laundry_room_washer] [--dryer-entities laundry_room_dryer]
                            [--washer-image images/washer.png] [--dryer-image images/dryer.png] [--no-photos]
                            [--www-path /local/samsung-laundry] [--out build]
"""
import argparse
import math
import sys
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / 'fonts' / 'DejaVuSansCondensed.ttf'
ICONS = ROOT / 'assets' / 'icons'
K = 3                                   # render scale: images are drawn at 3x the card's 960x400 layout

# ---------------------------------------------------------------------------------------------
# Layout (card is 960 x 400; the control strip and all overlays share one box)
# ---------------------------------------------------------------------------------------------
W, H = 960, 400
BG = (38, 38, 38, 255)
LIT = (244, 244, 246, 255)
GHOST = (33, 33, 36, 255)                      # unlit 7-segment cells
PRINT_G = (150, 150, 155, 255)                 # printed glyphs on the glass (power, start/pause)
PRINT_T = (120, 120, 125, 255)                 # printed labels (Quick Drive, Smart Control button)
DEVICE_CX, DEVICE_H, DEVICE_BOTTOM = 190, 257, 326
SX0, SY0, SX1, SY1 = 400, 125, 936, 275        # control strip = overlay canvas
WW, WH = SX1 - SX0, SY1 - SY0
DX0, DY0, DX1, DY1 = 552, 138, 898, 241        # display window; button icons sit below it on the glass
TX0, TX1 = 562, 692                            # text zone (stage, time, progress bar)
STAGE_Y, TIME_Y, BAR_Y = 184, 222, 234
DH = 22                                        # 7-segment digit height
_W, _G, _T = DH * 0.56, DH * 0.16, DH * 0.105  # digit width, gap and segment thickness (see seg_digit)
# status block to the right of the digits, as in the manuals: Wi-Fi | Smart Control over door lock | child lock
STAT_L, STAT_R = 865, 884
STAT_TOP, STAT_BOT = 184.5, 200.5
# '88' (temperature / dry level), '8' (rinse count / Wrinkle Prevent) and '1888' (spin speed, its 1 in a narrow
# cell) sit centred over their symbols, which are evenly spaced as on the real panel, the Smart Control hand included
TEMP_X = TX1 + 12 + (2 * _W + _G) / 2
SPIN_X = STAT_L - 9 - 8 - (_T + 3 * _W + 3 * _G) / 2     # ends 8 px short of the Wi-Fi symbol
STEP = (SPIN_X - TEMP_X) / 2
RINSE_X, HAND_X = TEMP_X + STEP, SPIN_X + STEP
IY = 256                                       # button icon row (below the display window)
OVERLAY_STYLE = {'left': f'{(SX0 + SX1) / 2 / W * 100:.3f}%', 'top': f'{(SY0 + SY1) / 2 / H * 100:.3f}%',
                 'width': f'{WW / W * 100:.3f}%', 'pointer-events': 'none'}

WASHER_STAGES = {'wash': ('Washing', 1), 'rinse': ('Rinsing', 1), 'spin': ('Spinning', 1), 'pre_wash': ('Pre-washing', 1),
                 'ai_wash': ('Washing', 1), 'ai_rinse': ('Rinsing', 1), 'ai_spin': ('Spinning', 1), 'air_wash': ('Air Wash', 1),
                 'weight_sensing': ('Sensing load', 1), 'delay_wash': ('Delay End', 0), 'drying': ('Drying', 1),
                 'cooling': ('Cooling', 1), 'wrinkle_prevent': ('Wrinkle Prevent', 1), 'finish': ('End', 0),
                 'freeze_protection': ('Freeze Protect', 1)}
DRYER_STAGES = {'drying': ('Drying', 1), 'ai_drying': ('Drying', 1), 'cooling': ('Cooling', 1),
                'wrinkle_prevent': ('Wrinkle Prevent', 1), 'finished': ('End', 0), 'weight_sensing': ('Sensing load', 1),
                'delay_wash': ('Delay End', 0), 'refreshing': ('Refreshing', 1), 'dehumidifying': ('Dehumidifying', 1),
                'continuous_dehumidifying': ('Dehumidifying', 1), 'sanitizing': ('Sanitising', 1),
                'internal_care': ('Internal Care', 1), 'freeze_protection': ('Freeze Protect', 1),
                'thawing_frozen_inside': ('Thawing', 1)}
# With Bubble Soak on, the wash phase shows Washing, then Bubble Soak for the 30 minutes the option adds, then
# Washing again. SmartThings reports it all as wash, so the soak is placed by the time left: it ends with about
# 52 minutes to go (Cotton, 2 rinses, 1400 rpm: soaking with 59 left, washing again with 44 left)
BUBBLE_SOAK_MIN, BUBBLE_SOAK_ENDS_LEFT = 30, 52
WASHER_TEMPS = {'cold': 'Co', '20': '20', '30': '30', '40': '40', '60': '60', '90': '90'}
WASHER_SPINS = {'rinse_hold': '  --', 'no_spin': '   0', '400': ' 400', '800': ' 800',
                '1000': '1000', '1200': '1200', '1400': '1400'}
# Delay End shows the finish time (NEXT DAY 5:59 AM) instead of the time left: the hours slot carries the
# hour, AM/PM and NEXT DAY, the minutes slot ':59'. (hour, am/pm, next day) -> (sensor state, image)
CLOCK = {(h, ap, nd): (f'{"next day " if nd else ""}{h} {ap}', f'clock-h-{h}-{ap}{"-next" if nd else ""}.png')
         for h in range(1, 13) for ap in ('am', 'pm') for nd in (False, True)}


# =============================================================================================
# Drawing helpers: everything is specified in 1x card coordinates and drawn at Kx
# =============================================================================================
def _s(v):
    if isinstance(v, (int, float)):
        return v * K
    return type(v)(_s(x) for x in v) if isinstance(v, (tuple, list)) else v


class KD:
    def __init__(self, img): self.d = ImageDraw.Draw(img)
    def line(self, xy, fill=None, width=1, joint=None): self.d.line(_s(xy), fill=fill, width=round(width * K), joint=joint)
    def polygon(self, xy, fill=None): self.d.polygon(_s(xy), fill=fill)
    def rounded_rectangle(self, xy, radius=0, fill=None, outline=None, width=1):
        self.d.rounded_rectangle(_s(xy), radius=radius * K, fill=fill, outline=outline, width=round(width * K))
    def text(self, xy, t, font=None, fill=None, anchor=None): self.d.text(_s(xy), t, font=font, fill=fill, anchor=anchor)
    def textlength(self, t, font=None): return self.d.textlength(t, font=font) / K


def font(size): return ImageFont.truetype(str(FONT), round(size * K))
def ov(): return Image.new('RGBA', (WW * K, WH * K), (0, 0, 0, 0))
def L(x, y): return (x - SX0, y - SY0)


def glow(img):
    a = img.copy().filter(ImageFilter.GaussianBlur(3 * K))
    a.putalpha(a.getchannel('A').point(lambda v: int(v * 0.45)))
    o = Image.new('RGBA', img.size, (0, 0, 0, 0)); o.alpha_composite(a); o.alpha_composite(img)
    return o


def put(img, icon, cx, cy, origin=(SX0, SY0)):
    x, y = (cx - origin[0]) * K, (cy - origin[1]) * K
    img.alpha_composite(icon, (round(x - icon.width / 2), round(y - icon.height / 2)))


def colour(alpha, rgb):
    ic = Image.new('RGBA', alpha.size, rgb[:3] + (0,)); ic.putalpha(alpha)
    return ic


# ---------------------------------------------------------------------------------------------
# Samsung icons (assets/icons: dark ink on white, as rendered from the manuals at 1200 dpi)
# ---------------------------------------------------------------------------------------------
def load_icons():
    raw = {}
    for f in sorted(ICONS.glob('*.png')):
        raw[f.stem] = Image.eval(Image.open(f).convert('L'), lambda v: 255 - v)     # ink intensity
    missing = {'power', 'start-pause', 'temperature', 'spin', 'hand', 'door-lock', 'child-lock', 'smart-control',
               'smart-control-button', 'dry-level', 'wrinkle-prevent'} - raw.keys()
    if missing:
        sys.exit(f'Missing icons in {ICONS}: {", ".join(sorted(missing))}')
    return raw


def stroke_of(a):
    runs = []
    for row in (np.array(a) > 128):
        r = np.diff(np.concatenate([[0], row.astype(int), [0]]))
        runs += list(np.nonzero(r == -1)[0] - np.nonzero(r == 1)[0])
    return float(np.median(runs))


def manual_icon(raw, name, target_h=None, target_w=None, stroke=1.5, rgb=LIT):
    """Scale Samsung's artwork to size, normalising line weight to `stroke` card pixels."""
    a = raw[name]
    s = (target_h * K / a.height) if target_h else (target_w * K / a.width)
    grow = int(round(stroke * K / s - stroke_of(a)))
    if grow >= 2:
        a = a.filter(ImageFilter.MaxFilter(grow + 1 if grow % 2 == 0 else grow))
    a = a.resize((max(1, round(a.width * s)), max(1, round(a.height * s))), Image.LANCZOS)
    return colour(a, rgb)


def vector_icon(w, h, draw, ss=8):
    k = K * ss; im = Image.new('L', (round(w * k), round(h * k)), 0)
    draw(ImageDraw.Draw(im), lambda x, y: (x * k, y * k), k)
    return colour(im.resize((round(w * K), round(h * K)), Image.LANCZOS), LIT)


def wifi_icon():
    """Three arcs and a dot, as on the washer and dryer displays."""
    def draw(d, P, k):
        cx, cy, lw = 9.0, 12.2, 1.9
        for r in (4.2, 7.9, 11.6):
            box = (*P(cx - r, cy - r), *P(cx + r, cy + r))
            d.arc(box, 228, 312, fill=255, width=round(lw * k))
            for ang in (228, 312):                                    # round the arc ends
                ex, ey = cx + r * math.cos(math.radians(ang)), cy + r * math.sin(math.radians(ang))
                d.ellipse((*P(ex - lw / 2, ey - lw / 2), *P(ex + lw / 2, ey + lw / 2)), fill=255)
        d.ellipse((*P(cx - 1.7, cy - 1.7), *P(cx + 1.7, cy + 1.7)), fill=255)
    return vector_icon(18, 14.2, draw)


def rinse_icon():
    """Tub with a wavy water line and bubbles (the manual draws dashes; the real panels show bubbles)."""
    def draw(d, P, k):
        d.line([P(1.0, 1.2), P(1.5, 2.2), P(4.2, 14.4), P(15.8, 14.4), P(18.5, 2.2), P(19.0, 1.2)],
               fill=255, width=round(1.5 * k), joint='curve')
        pts = [P(2.4 + t * 15.2 / 40, 6.4 - 1.9 * math.sin(t / 40 * 2 * math.pi) - t / 40 * 1.6) for t in range(41)]
        d.line(pts, fill=255, width=round(1.3 * k), joint='curve')
        r = 1.45
        for cx, cy in ((8.3, 9.6), (11.5, 9.1), (14.6, 8.6), (6.9, 12.2), (10.1, 12.2), (13.3, 12.2)):
            d.ellipse((*P(cx - r, cy - r), *P(cx + r, cy + r)), fill=255)
    return vector_icon(20, 16, draw)


# ---------------------------------------------------------------------------------------------
# 7-segment digits (upright, as on the real displays)
# ---------------------------------------------------------------------------------------------
SEG = {'0': 'abcdef', '1': 'bc', '2': 'abged', '3': 'abgcd', '4': 'fgbc', '5': 'afgcd', '6': 'afgedc', '7': 'abc',
       '8': 'abcdefg', '9': 'abfgcd', '-': 'g', ' ': '', 'C': 'afed', 'o': 'cdeg'}


def seg_digit(d, ch, x0, cy, h, col, w):
    t = h * 0.105; g = t * 0.28
    top, mid, bot = cy - h / 2, cy, cy + h / 2
    def hseg(y):
        xa, xb = x0 + g, x0 + w - g
        return [(xa, y), (xa + t / 2, y - t / 2), (xb - t / 2, y - t / 2), (xb, y), (xb - t / 2, y + t / 2), (xa + t / 2, y + t / 2)]
    def vseg(x, y0, y1):
        ya, yb = y0 + g, y1 - g
        return [(x, ya), (x + t / 2, ya + t / 2), (x + t / 2, yb - t / 2), (x, yb), (x - t / 2, yb - t / 2), (x - t / 2, ya + t / 2)]
    ht, hm, hb = top + t / 2, mid, bot - t / 2
    xl, xr = x0 + t / 2, x0 + w - t / 2
    segs = {'a': hseg(ht), 'g': hseg(hm), 'd': hseg(hb), 'f': vseg(xl, ht, hm), 'b': vseg(xr, ht, hm),
            'e': vseg(xl, hm, hb), 'c': vseg(xr, hm, hb)}
    for s in SEG[ch]:
        d.polygon(segs[s], fill=col)


def seg_text(img, text, cx, cy, h=DH, col=LIT, narrow_first=False):
    """Centred on cx. narrow_first: the first cell only holds a 1 (the spin speed's '1888'), so it's one segment wide."""
    d = KD(img); gap = h * 0.16
    ws = [h * 0.105 if narrow_first and i == 0 else h * 0.56 for i in range(len(text))]
    x = cx - (sum(ws) + gap * (len(text) - 1)) / 2
    for c, w in zip(text, ws):
        seg_digit(d, c, x, cy, h, col, w); x += w + gap


def next_day(d, right):
    """The stacked NEXT / DAY label, with DAY spread to the width of NEXT as on the display."""
    f = font(10); w = d.textlength('NEXT', font=f); x = right - w
    d.text((x - SX0, TIME_Y - 9 - SY0), 'NEXT', font=f, fill=LIT, anchor='ls')
    ws = [d.textlength(c, font=f) for c in 'DAY']; gap = (w - sum(ws)) / 2
    for c, cw in zip('DAY', ws):
        d.text((x - SX0, TIME_Y - SY0), c, font=f, fill=LIT, anchor='ls'); x += cw + gap


def text_img(parts, x, y_base, anchor='left'):
    o = ov(); d = KD(o)
    fonts = [font(s) for _, s in parts]
    widths = [d.textlength(t, font=f) for (t, _), f in zip(parts, fonts)]
    total = sum(widths) + 2 * (len(parts) - 1)
    cx = x - SX0 if anchor == 'left' else x - SX0 - total
    for (t, s), f, w in zip(parts, fonts, widths):
        d.text((cx, y_base - SY0), t, font=f, fill=LIT, anchor='ls'); cx += w + 2
    return o


# ---------------------------------------------------------------------------------------------
# Background: appliance photo (optional) + control strip
# ---------------------------------------------------------------------------------------------
def dial(bg, cx, cy, R):
    R = R * K; size = R * 2 + 16 * K
    yy, xx = np.mgrid[0:size, 0:size].astype(float); o = size / 2
    r = np.hypot(xx - o, yy - o); th = np.arctan2(yy - o, xx - o)
    base = np.clip(168 + 52 * np.cos(2 * (th + math.radians(35))) + 6 * np.sin(r / K * 1.7), 90, 245)
    a = np.zeros((size, size, 4), dtype=np.uint8)
    a[..., 0] = base; a[..., 1] = base; a[..., 2] = np.clip(base + 4, 0, 255)
    a[..., 3] = (np.clip(R - r, 0, 1) * 255).astype(np.uint8)
    d = Image.fromarray(a, 'RGBA')
    ImageDraw.Draw(d).ellipse((o - R, o - R, o + R, o + R), outline=(70, 70, 74, 255), width=3 * K)
    sh = Image.new('RGBA', (size + 20 * K, size + 20 * K), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse((10 * K + o - R - 2 * K, 13 * K + o - R - 2 * K, 10 * K + o + R + 2 * K, 13 * K + o + R + 2 * K), fill=(0, 0, 0, 170))
    bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4 * K)), (int(cx * K - o - 10 * K), int(cy * K - o - 10 * K)))
    bg.alpha_composite(d, (int(cx * K - o), int(cy * K - o)))


def background(photo, panel_rgb, icons):
    b = Image.new('RGBA', (W * K, H * K), BG)
    if photo:
        cut = Image.open(photo).convert('RGBA')
        cut = cut.resize((round(cut.width * DEVICE_H * K / cut.height), DEVICE_H * K), Image.LANCZOS)
        b.alpha_composite(cut, (round(DEVICE_CX * K - cut.width / 2), (DEVICE_BOTTOM - DEVICE_H + 1) * K))
    d = KD(b)
    d.rounded_rectangle((SX0, SY0, SX1, SY1), radius=16, fill=panel_rgb + (255,), outline=(52, 52, 55, 255), width=2)
    d.line([(SX0 + 16, SY0 + 3), (SX1 - 16, SY0 + 3)], fill=(40, 40, 43, 255), width=1)
    d.rounded_rectangle((DX0, DY0, DX1, DY1), radius=7, fill=(4, 4, 5, 255), outline=(26, 26, 28, 255), width=2)
    put(b, icons['power'], 424, 200, origin=(0, 0))
    dial(b, 476, 200, 36)
    put(b, icons['play'], 530, 200, origin=(0, 0))
    for i, t in enumerate(('Quick', 'Drive')):
        d.text((917, 251 + i * 11), t, font=font(10), fill=PRINT_T, anchor='mm')
    return b


# =============================================================================================
# Assets
# =============================================================================================
def build_images(out, raw, washer_photo, dryer_photo):
    def save(img, name): img.save(out / name, optimize=True)
    I = {
        'power': manual_icon(raw, 'power', target_h=21, stroke=2.2, rgb=PRINT_G),
        'play': manual_icon(raw, 'start-pause', target_h=19, stroke=2.2, rgb=PRINT_G),
        'temp': manual_icon(raw, 'temperature', target_h=19), 'spin': manual_icon(raw, 'spin', target_h=19),
        'hand': manual_icon(raw, 'hand', target_h=17.5), 'doorlock': manual_icon(raw, 'door-lock', target_h=14),
        'childlock': manual_icon(raw, 'child-lock', target_h=14), 'sc_lit': manual_icon(raw, 'smart-control', target_h=15),
        'sc_printed': manual_icon(raw, 'smart-control-button', target_h=25, stroke=1.4, rgb=PRINT_T),
        'level': manual_icon(raw, 'dry-level', target_w=22, stroke=1.8),
        'wrinkle': manual_icon(raw, 'wrinkle-prevent', target_h=19, stroke=1.8),
        'rinse': rinse_icon(), 'wifi': wifi_icon(),
    }
    save(background(washer_photo, (10, 10, 11), I), 'washer-bg.png')
    save(background(dryer_photo, (19, 20, 22), I), 'dryer-bg.png')
    save(ov(), 'blank.png')

    # stage line, "Paused", time and progress bar (shared by both machines)
    def stage(key, label, active, prefix):
        d = KD(ov()); size = 19; txt = label + (' ›››' if active else '')
        while size > 11 and d.textlength(txt, font=font(size)) > TX1 - TX0:
            size -= 1
        save(glow(text_img([(txt, size)], TX0, STAGE_Y)), f'{prefix}-stage-{key}.png')
    for k, (l, a) in WASHER_STAGES.items(): stage(k, l, a, 'washer')
    for k, (l, a) in DRYER_STAGES.items(): stage(k, l, a, 'dryer')
    for p in ('washer', 'dryer'): stage('paused', 'Paused', 0, p)
    stage('bubble_soak', 'Bubble Soak', 1, 'washer')          # shown instead of Washing while Bubble Soak is on
    d0 = KD(ov()); wmin = d0.textlength('00', font=font(30)) + 2 + d0.textlength('min', font=font(14))
    for mm in range(60):
        save(glow(text_img([(f'{mm:02d}', 30), ('min', 14)], TX1, TIME_Y, 'right')), f'time-m-{mm:02d}.png')
    for hh in range(1, 10):
        save(glow(text_img([(str(hh), 30), ('hr', 14)], TX1 - wmin - 6, TIME_Y, 'right')), f'time-h-{hh}.png')
    fd, fa = font(30), font(18)                                  # Delay End finish time
    xa = TX1 - max(d0.textlength(t, font=fa) for t in ('AM', 'PM'))
    xc = xa - 2 - d0.textlength(':00', font=fd)                # the colon; the hour ends here
    for mm in range(60):
        o = ov(); KD(o).text((xc - SX0, TIME_Y - SY0), f':{mm:02d}', font=fd, fill=LIT, anchor='ls')
        save(glow(o), f'clock-m-{mm:02d}.png')
    for (hh, ap, nd), (_, name) in CLOCK.items():
        o = ov(); d = KD(o)
        d.text((xc - SX0, TIME_Y - SY0), str(hh), font=fd, fill=LIT, anchor='rs')
        d.text((xa - SX0, TIME_Y - SY0), ap.upper(), font=fa, fill=LIT, anchor='ls')
        if nd:
            next_day(d, xc - d.textlength(str(hh), font=fd) - 3)
        save(glow(o), name)
    for n in range(21):                      # light-grey track, lit part fills from the left with elapsed time
        o = ov(); y = BAR_Y - SY0
        KD(o).line([(TX0 - SX0, y), (TX1 - SX0, y)], fill=(190, 190, 193, 255), width=2.6)
        lit = ov()
        if n:
            KD(lit).line([(TX0 - SX0, y), (TX0 - SX0 + (TX1 - TX0) * n / 20, y)], fill=LIT, width=3)
        o.alpha_composite(glow(lit)); save(o, f'bar-{n}.png')

    # washer: faint '88 8 1888' cells + button icons, then the lit digits
    o = ov()
    for txt, x in (('88', TEMP_X), ('8', RINSE_X), ('1888', SPIN_X)):
        seg_text(o, txt, *L(x, 192), col=GHOST, narrow_first=x == SPIN_X)
    lit = ov()
    put(lit, I['temp'], TEMP_X, IY - 1); put(lit, I['rinse'], RINSE_X, IY); put(lit, I['spin'], SPIN_X, IY); put(lit, I['hand'], HAND_X, IY)
    o.alpha_composite(glow(lit)); save(o, 'washer-base.png')
    for k, v in WASHER_TEMPS.items():
        o = ov(); seg_text(o, v, *L(TEMP_X, 192)); save(glow(o), f'washer-temp-{k}.png')
    for n in range(6):
        o = ov(); seg_text(o, str(n), *L(RINSE_X, 192)); save(glow(o), f'washer-rinse-{n}.png')
    for k, v in WASHER_SPINS.items():
        o = ov(); seg_text(o, v, *L(SPIN_X, 192), narrow_first=True); save(glow(o), f'washer-spin-{k}.png')
    o = ov(); put(o, I['doorlock'], STAT_L, STAT_BOT); save(glow(o), 'washer-doorlock.png')

    # dryer: same cells; the dry-level icon is separate because it only lights on cycles that have a dry level
    o = ov()
    for txt, x in (('88', TEMP_X), ('8', RINSE_X), ('1888', SPIN_X)):
        seg_text(o, txt, *L(x, 192), col=GHOST, narrow_first=x == SPIN_X)
    lit = ov(); put(lit, I['wrinkle'], RINSE_X, IY - 2); put(lit, I['hand'], HAND_X, IY)
    o.alpha_composite(glow(lit)); save(o, 'dryer-base.png')
    o = ov(); put(o, I['level'], TEMP_X, IY - 1); save(glow(o), 'dryer-level.png')
    for n in '1234':
        o = ov(); seg_text(o, ' ' + n, *L(TEMP_X, 192)); save(glow(o), f'dryer-dry-{n}.png')
    o = ov(); seg_text(o, '3', *L(RINSE_X, 192)); save(glow(o), 'dryer-wrinkle-3.png')     # Wrinkle Prevent on = 3 hours

    # status icons (fixed 2x2 grid in the top-right of the display) and the printed Smart Control button
    o = ov(); put(o, I['wifi'], STAT_L, STAT_TOP); save(glow(o), 'wifi.png')
    o = ov(); put(o, I['wifi'], STAT_L, STAT_TOP); put(o, I['sc_lit'], STAT_R, STAT_TOP); save(glow(o), 'wifi-smart-control.png')
    o = ov(); put(o, I['childlock'], STAT_R, STAT_BOT); save(glow(o), 'childlock.png')
    o = ov(); put(o, I['sc_printed'], 917, 196); save(o, 'smart-control-button.png')


# =============================================================================================
# Home Assistant YAML
# =============================================================================================
def img(path, **extra):
    e = {'type': 'image', 'image': path, 'tap_action': {'action': 'none'}, 'hold_action': {'action': 'none'},
         'style': dict(OVERLAY_STYLE)}
    e.update(extra)
    return e


def mapped(www, entity, mapping):
    return img(f'{www}/blank.png', entity=entity, state_image={k: f'{www}/{v}' for k, v in mapping.items()})


def cond(conditions, *elements):
    return {'type': 'conditional', 'conditions': conditions, 'elements': list(elements)}


def is_(entity, state): return {'entity': entity, 'state': state}
def not_(entity, state): return {'entity': entity, 'state_not': state}


def time_and_bar(www, disp):
    return [mapped(www, f'sensor.{disp}_hours', {**{str(h): f'time-h-{h}.png' for h in range(1, 10)}, **dict(CLOCK.values())}),
            mapped(www, f'sensor.{disp}_minutes', {**{f'{m:02d}': f'time-m-{m:02d}.png' for m in range(60)},
                                                   **{f':{m:02d}': f'clock-m-{m:02d}.png' for m in range(60)}}),
            mapped(www, f'sensor.{disp}_progress', {str(n): f'bar-{n}.png' for n in range(21)})]


def washer_card(www, e, disp):
    p, ms = f'binary_sensor.{e}_power', f'sensor.{e}_machine_state'
    temp =mapped(www, f'select.{e}_water_temperature', {k: f'washer-temp-{k}.png' for k in WASHER_TEMPS})
    rinse = mapped(www, f'number.{e}_rinse_cycles', {**{str(n): f'washer-rinse-{n}.png' for n in range(6)},
                                                     **{f'{n}.0': f'washer-rinse-{n}.png' for n in range(6)}})
    spin = mapped(www, f'select.{e}_spin_level', {k: f'washer-spin-{k}.png' for k in WASHER_SPINS})
    stages = {**{k: f'washer-stage-{k}.png' for k in WASHER_STAGES}, 'bubble_soak': 'washer-stage-bubble_soak.png'}
    els = [
        cond([is_(p, 'on')], img(f'{www}/washer-base.png')),
        cond([is_(p, 'on'), not_(ms, 'stop')], *time_and_bar(www, disp)),
        cond([is_(p, 'on'), is_(ms, 'run')], mapped(www, f'sensor.{disp}_stage', stages)),   # job state, or bubble_soak
        cond([is_(p, 'on'), is_(ms, 'pause')], img(f'{www}/washer-stage-paused.png')),
        cond([is_(p, 'on'), is_(ms, 'run')], img(f'{www}/washer-doorlock.png')),
        cond([is_(p, 'on')], temp, rinse, spin),          # the settings stay lit, idle or running
    ] + status(www, e)
    return {'type': 'picture-elements', 'image': f'{www}/washer-bg.png', 'elements': els, 'grid_options': {'columns': 12}}


def dryer_card(www, e, disp):
    p, ms, js = f'binary_sensor.{e}_power', f'sensor.{e}_machine_state', f'sensor.{e}_job_state'
    els = [
        cond([is_(p, 'on')], img(f'{www}/dryer-base.png')),
        cond([is_(p, 'on'), is_(f'switch.{e}_wrinkle_prevent', 'on')], img(f'{www}/dryer-wrinkle-3.png')),
        cond([is_(p, 'on'), not_(ms, 'stop')], *time_and_bar(www, disp)),
        cond([is_(p, 'on'), is_(ms, 'run')], mapped(www, js, {k: f'dryer-stage-{k}.png' for k in DRYER_STAGES})),
        cond([is_(p, 'on'), is_(ms, 'pause')], img(f'{www}/dryer-stage-paused.png')),
    ] + status(www, e)
    return {'type': 'picture-elements', 'image': f'{www}/dryer-bg.png', 'elements': els, 'grid_options': {'columns': 12}}


def status(www, e):
    p = f'binary_sensor.{e}_power'
    return [img(f'{www}/smart-control-button.png'),
            cond([is_(p, 'on'), not_(f'binary_sensor.{e}_remote_control', 'on')], img(f'{www}/wifi.png')),
            cond([is_(p, 'on'), is_(f'binary_sensor.{e}_remote_control', 'on')], img(f'{www}/wifi-smart-control.png')),
            cond([is_(p, 'on'), is_(f'binary_sensor.{e}_child_lock', 'on')], img(f'{www}/childlock.png'))]


def package(machines):
    """Template sensors the cards read. `machines`: [(label, smartthings_prefix, display_prefix, has_bubble_soak)]"""
    sensors = []
    for label, e, disp, soak in machines:
        ms, end = f"states('sensor.{e}_machine_state')", f"states('sensor.{e}_completion_time') | as_datetime(none)"
        paused_at = f"states.sensor.{e}_machine_state.last_changed if ms == 'pause' else now()"
        remaining = (f"{{%- set ms = {ms} -%}}\n{{%- set end = {end} -%}}\n"
                     f"{{%- set running = ms in ['run', 'pause'] and end is not none -%}}\n"
                     f"{{%- set m = ((end - ({paused_at})).total_seconds() / 60) | round(0, 'ceil') | int if running else 0 -%}}\n"
                     # Delay End: the finish time instead. SmartThings recalculates the completion time from the
                     # minutes left, so it drifts a few seconds either side of the minute the display shows
                     f"{{%- set delay = states('sensor.{e}_job_state') == 'delay_wash' -%}}\n"
                     "{%- set at = as_local(end + timedelta(seconds=30)) if running else none -%}\n")
        sensors += [
            {'name': f'{label} cycle start', 'unique_id': f'{disp}_cycle_start', 'icon': 'mdi:timer-play-outline',
             'state': (f"{{%- set ms = {ms} -%}}\n"
                       "{%- set prev = this.state if this is defined and this.state is defined and this.state not in ['unknown', 'unavailable', ''] else '' -%}\n"
                       "{%- if ms in ['unknown', 'unavailable'] -%}{{ prev }}\n"
                       # a delayed cycle starts when the delay ends, not when the countdown to it starts
                       f"{{%- elif ms in ['run', 'pause'] and states('sensor.{e}_job_state') != 'delay_wash' -%}}\n"
                       "{%- if prev -%}{{ prev }}\n"
                       f"{{%- elif ms == 'run' -%}}{{{{ ([states.sensor.{e}_machine_state.last_changed, states.sensor.{e}_job_state.last_changed] | max).isoformat() }}}}\n"
                       f"{{%- else -%}}{{{{ states.sensor.{e}_job_state.last_changed.isoformat() }}}}\n"
                       "{%- endif -%}\n{%- endif -%}")},
            {'name': f'{label} hours', 'unique_id': f'{disp}_hours', 'icon': 'mdi:monitor',
             'state': remaining + ("{%- if running and delay -%}\n"
                                   "{{ 'next day ' if at.date() > now().date() else '' }}{{ at.hour % 12 or 12 }} {{ 'am' if at.hour < 12 else 'pm' }}\n"
                                   "{%- elif running and m >= 60 -%}{{ m // 60 }}{%- endif -%}")},
            {'name': f'{label} minutes', 'unique_id': f'{disp}_minutes', 'icon': 'mdi:monitor',
             'state': remaining + ("{%- if running and delay -%}{{ ':%02d' | format(at.minute) }}\n"
                                   "{%- elif running and m > 0 -%}{{ '%02d' | format(m % 60) }}{%- endif -%}")},
            {'name': f'{label} progress', 'unique_id': f'{disp}_progress', 'icon': 'mdi:monitor',
             'state': (f"{{%- set ms = {ms} -%}}\n{{%- set end = {end} -%}}\n"
                       f"{{%- set start = states('sensor.{disp}_cycle_start') | as_datetime(none) -%}}\n"
                       f"{{%- set t = {paused_at} -%}}\n"
                       "{%- if ms in ['run', 'pause'] and end is not none and start is not none and end > start -%}\n"
                       "{{ [[((t - start).total_seconds() / (end - start).total_seconds() * 20) | round(0) | int, 0] | max, 20] | min }}\n"
                       "{%- else -%}0{%- endif -%}")},
        ]
        if soak:
            sensors.append(
                {'name': f'{label} stage', 'unique_id': f'{disp}_stage', 'icon': 'mdi:monitor',
                 'state': (f"{{%- set js = states('sensor.{e}_job_state') -%}}\n"
                           f"{{%- set end = {end} -%}}\n"
                           "{%- set left = (end - now()).total_seconds() / 60 if end is not none else -1 -%}\n"
                           f"{{%- if js in ['wash', 'ai_wash'] and is_state('switch.{e}_bubble_soak', 'on') and "
                           f"{BUBBLE_SOAK_ENDS_LEFT} <= left < {BUBBLE_SOAK_ENDS_LEFT + BUBBLE_SOAK_MIN} -%}}bubble_soak\n"
                           "{%- else -%}{{ js }}{%- endif -%}")})
    return {'template': [{'sensor': sensors}]}


class Literal(str):
    pass


def _literal(dumper, data): return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')


yaml.add_representer(Literal, _literal, Dumper=yaml.SafeDumper)


def dump(obj, path, header):
    def lit(o):
        if isinstance(o, dict): return {k: lit(v) for k, v in o.items()}
        if isinstance(o, list): return [lit(v) for v in o]
        return Literal(o) if isinstance(o, str) and '\n' in o else o
    path.write_text(header + yaml.safe_dump(lit(obj), sort_keys=False, allow_unicode=True, width=200))


def write_yaml(out, www, we, de):
    wd, dd = 'samsung_washer_display', 'samsung_dryer_display'
    (out / 'packages').mkdir(parents=True, exist_ok=True); (out / 'cards').mkdir(parents=True, exist_ok=True)
    dump(package([('Samsung washer display', we, wd, True), ('Samsung dryer display', de, dd, False)]),
         out / 'packages' / 'samsung_laundry_package.yaml',
         '# Home Assistant package: template sensors used by the washer and dryer cards.\n'
         '# Put this file in /config/packages/ (see README) and restart Home Assistant.\n')
    dump(washer_card(www, we, wd), out / 'cards' / 'washer-card.yaml',
         '# Washer card: Dashboard > Edit > Add card > Manual, then paste.\n')
    dump(dryer_card(www, de, dd), out / 'cards' / 'dryer-card.yaml',
         '# Dryer card: Dashboard > Edit > Add card > Manual, then paste.\n')


def image_dir(out, www):
    """Where the images go under `out`, mirroring /config: /local/x is served from /config/www/x."""
    return out / 'www' / www[len('/local/'):] if www.startswith('/local/') else out / 'www' / Path(www).name


# =============================================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=str(ROOT / 'build'), help='output folder (default: build/)')
    ap.add_argument('--washer-image', default=str(ROOT / 'images' / 'washer.png'),
                    help='front photo of the washer, PNG with a transparent background (default: images/washer.png)')
    ap.add_argument('--dryer-image', default=str(ROOT / 'images' / 'dryer.png'),
                    help='front photo of the dryer, PNG with a transparent background (default: images/dryer.png)')
    ap.add_argument('--no-photos', action='store_true', help='leave the appliance photos out and show just the panel')
    ap.add_argument('--washer-entities', default='laundry_room_washer',
                    help='SmartThings entity prefix, e.g. laundry_room_washer for sensor.laundry_room_washer_machine_state')
    ap.add_argument('--dryer-entities', default='laundry_room_dryer', help='as above, for the dryer')
    ap.add_argument('--www-path', default='/local/samsung-laundry', help='URL path the images are served from')
    ap.add_argument('--yaml-only', action='store_true', help='write the YAML files only')
    a = ap.parse_args()
    out, www = Path(a.out), a.www_path.rstrip('/')
    if not a.yaml_only:
        photos = (None, None) if a.no_photos else (a.washer_image, a.dryer_image)
        for p in photos:
            if p and not Path(p).exists():
                sys.exit(f'Image not found: {p} (use --no-photos to build without the appliance photos)')
        imgs = image_dir(out, www); imgs.mkdir(parents=True, exist_ok=True)
        build_images(imgs, load_icons(), *photos)
        print(f"Built {len(list(imgs.glob('*.png')))} images in {imgs}")
    write_yaml(out, www, a.washer_entities, a.dryer_entities)
    print(f"Wrote the cards to {out / 'cards'} and the template sensors to {out / 'packages'}")


if __name__ == '__main__':
    main()
