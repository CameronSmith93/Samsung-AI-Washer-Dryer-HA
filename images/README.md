# Appliance photos

`washer.png` and `dryer.png` are Samsung product photos of the washer and dryer, cut out onto a
transparent background and cropped tight to the appliance. `generator/build.py` draws them to the
left of the control panel on each card.

To use photos of your own machines, replace these two files (front-on PNGs with transparent
backgrounds work best), or point the build at other files with `--washer-image` and `--dryer-image`.
To leave the photos out and show just the panel, build with `--no-photos`.

These photos are Samsung's and aren't covered by this repository's MIT licence.
