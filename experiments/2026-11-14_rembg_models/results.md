# Experiment: which background-removal model? (2026-11-14)

## Why
The first real uploads showed `u2net` (our default) failing on a coiled USB cable:
wood floor left inside the loop, and the cable's tail faded/smeared. The people photo
also came out "ghostly" (half-transparent person). Thin objects with holes (straps,
lace, chains) are common in clothing, so this matters.

## Setup
- **Script:** `compare_models.py` (run from the project root with `PYTHONPATH=.`)
- **Pipeline:** our real `make_clean_image()`; only the remover changes
- **Photos:** 4 real uploads (`storage/originals/`):
  - pencil box: solid shape
  - bottle: solid shape, with a carry loop
  - cable: thin, with holes
  - people: a hard, cluttered scene
- **Machine:** his MacBook, local CPU (onnxruntime)
- **Outputs:** `outputs/<model>/<photo>.jpg`, plus `grid.jpg` (all results side by side) and `timings.json`
- Note: the grid's "original" row shows the people photo sideways, because the grid builder skips the EXIF rotation. The pipeline outputs themselves are upright.

## Results

### Speed (seconds per photo, model already loaded)
| Model | Pencil | Bottle | Cable | People | ~50-photo batch | Model size |
|---|---|---|---|---|---|---|
| `u2net` (current) | 1.27* | 0.41 | 0.39 | 0.62 | ~25 s | 176 MB |
| `isnet-general-use` | 2.16* | 1.00 | 0.78 | 0.99 | ~50 s | 179 MB |
| `birefnet-general-lite` | 7.14 | 6.36 | 6.43 | 6.94 | ~5.5 min | 224 MB |

\* The first photo per model includes warm-up. Load times (21–22 s for the new models) included the one-time download, so they're not comparable.

### Quality (visual check of every output)
| Model | Pencil box | Bottle | Cable (the hard one) | People |
|---|---|---|---|---|
| `u2net` | ✅ clean | ✅ clean (tiny wood inside the loop) | ❌ wood inside the coil, tail faded and smeared | ❌ left person ghostly and hazy |
| `isnet-general-use` | ✅ clean | ✅ clean | ✅ hole cleared, tail solid; faint grey shadow under the coil | ⚠️ left person still ghostly |
| `birefnet-general-lite` | ✅ clean | ✅ clean | ✅✅ cleanest: hole cleared, crisp edges | ✅ all people solid, no haze |

## Conclusion
- **Solid products:** all three are equally good.
- **Thin products with holes:** `u2net` fails. Both newer models fix it, and `birefnet` is the cleanest.
- **Cost:** `isnet` is about **2× slower** than `u2net`; `birefnet` is about **8× slower than `isnet`**. A 50-photo batch would take ~5.5 min of background removal alone, before any Claude calls. It also needs more memory, which is a risk on a small cloud server.

## Recommendation (pending his decision)
1. **Default: `isnet-general-use`.** It fixes the real failure (the cable) for ~0.5 s extra per photo.
2. **Make the model a setting** (`REMBG_MODEL` in `.env`), so `birefnet-general-lite` can be switched on where quality matters more than speed, without changing code.
3. Re-check on **clothing photos** (lace, straps, see-through fabric) during the evaluation step.

## Decision (2026-11-14, his choice)
**`isnet-general-use` as the default, with the model as a setting** (`REMBG_MODEL`).
- `birefnet-general-lite` stays available by changing `.env`.
- `u2net` is dropped because it fails on thin objects with holes.
