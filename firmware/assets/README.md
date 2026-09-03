# Camera scene source imagery

Source images for the stored camera scenes (`tools/gen_scenes.py` converts
these to raw grayscale in `app/scenes.c`).

| File | Subject | Credit |
|---|---|---|
| `pluto.png` | Pluto, Tombaugh Regio | NASA/JHUAPL/SwRI (New Horizons) — public domain |
| `nix.png` | Nix, a small moon of Pluto | NASA/JHUAPL/SwRI (New Horizons) — public domain |
| `arrokoth.png` | Arrokoth (486958 Arrokoth, 2014 MU69), Kuiper Belt contact binary | NASA/JHUAPL/SwRI (New Horizons) — public domain |
| `mimas.png` | Mimas, showing the Herschel crater — the easter-egg scene | NASA/JPL-Caltech/Space Science Institute (Cassini) — public domain |

Only the survey star field is generated procedurally by `gen_scenes.py`;
the rest are imported from the images above.

**Alternates**, kept for future scenarios but not in the current scene set
(they show inner-solar-system bodies, inconsistent with a Kuiper Belt
mission): `ceres.png` (NASA/JPL-Caltech/UCLA/MPS/DLR/IDA, Dawn) and
`saturn_hexagon.png` (NASA/JPL-Caltech/SSI, Cassini).

NASA imagery is generally not copyrighted and may be used for educational
purposes; see https://www.nasa.gov/nasa-brand-center/images-and-media/
