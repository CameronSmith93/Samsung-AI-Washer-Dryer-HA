# Samsung panel symbols

These are Samsung's own symbols, cut from the control-panel diagrams in Samsung's user manuals. The
diagrams are vector artwork, so each symbol was rendered from the page at 1200 dpi and saved as dark
ink on white, as it appears in the manual. `generator/build.py` scales them to size, evens out the
line weight and lights them in the display colour.

| Symbol | File | Manual | Where it appears on the card |
|:---:|---|---|---|
| <img src="power.png" height="36"> | `power.png` | Washer, p. 34 | Printed power button, left of the dial (both cards) |
| <img src="start-pause.png" height="36"> | `start-pause.png` | Washer, p. 34 | Printed Start/Pause button, right of the dial (both cards) |
| <img src="temperature.png" height="36"> | `temperature.png` | Washer, p. 34 | Below the display, under the temperature digits (washer) |
| <img src="spin.png" height="36"> | `spin.png` | Washer, p. 34 | Below the display, under the spin speed digits (washer) |
| <img src="hand.png" height="36"> | `hand.png` | Washer, p. 34 | Below the display, far right (both cards) |
| <img src="smart-control.png" height="36"> | `smart-control.png` | Washer, p. 34 | Status block, lit when Smart Control is on (both cards) |
| <img src="door-lock.png" height="36"> | `door-lock.png` | Washer, p. 34 | Status block, lit while a cycle is running (washer) |
| <img src="child-lock.png" height="36"> | `child-lock.png` | Washer, p. 34 | Status block, lit when Child Lock is on (both cards) |
| <img src="smart-control-button.png" height="36"> | `smart-control-button.png` | Washer, p. 34 | Printed Smart Control button, right of the display (both cards) |
| <img src="wrinkle-prevent.png" height="36"> | `wrinkle-prevent.png` | Dryer, p. 29 | Below the display, under the Wrinkle Prevent digit (dryer) |
| <img src="dry-level.png" height="36"> | `dry-level.png` | Dryer, p. 29 | Built as `dryer-level.png` but not used yet (see Known limitations in the main README) |

The manuals:

- Washer: [Web_IB_D-PJT_WASHER-MD_SimpleUX_EN_v1.pdf](https://downloadcenter.samsung.com/content/UM/202604/20260408143907954/Web_IB_D-PJT_WASHER-MD_SimpleUX_EN_v1.pdf), page 34
- Dryer (DV9400B series): [DC68-04400M-00_IB_B-PJT_DV9400B_SimpleUX_EN_pdf.pdf](https://downloadcenter.samsung.com/content/UM/202304/20230425115323308/DC68-04400M-00_IB_B-PJT_DV9400B_SimpleUX_EN_pdf.pdf), page 29

The Wi-Fi and rinse symbols aren't here: the manuals don't draw them the way the real displays show
them, so `build.py` draws those two itself (`wifi_icon` and `rinse_icon`).

To cut the symbols again from the manuals, for example at a different resolution:

```sh
pip install -r generator/requirements-extract.txt
python generator/extract_icons.py
```

It downloads both manuals into `manuals/` (ignored by git), checks them against pinned SHA-256
hashes, because the crop positions only fit those exact files, and rewrites this folder.

These symbols are Samsung's artwork and aren't covered by this repository's MIT licence.
