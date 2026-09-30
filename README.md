AI use disclosure: Primarily created with the use of AI. Fully reviewed by a human.

# ithmb_decode.py — macOS Photos `.ithmb` thumbnail decoder

Decodes the modern (thumbnailConfiguration v31) `.ithmb` slot files produced by
macOS Photos (macOS 26.x / Photos 11). Payloads are BC7 (DXGI_FORMAT_BC7_UNORM,
BGRA, premultiplied); see `FORMAT.md` for the container layout.

## Requirements

Python 3.9+ with the packages in `requirements.txt`:

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

(`texture2ddecoder` + `numpy` are required; `Pillow` is used for PNG output.)

## Usage

All commands assume `./thumbs` is a photo library's
`resources/derivatives/thumbs` directory (or any directory containing
`<fmt>.ithmb` files), or a direct path to a single `.ithmb` file.

### Decode one slot by index

```
.venv/bin/python3 ithmb_decode.py thumbs/4532.ithmb 0 out.png
.venv/bin/python3 ithmb_decode.py thumbs/4532.ithmb 123 thumb_123.png
```

Output:

```
index 0: da5c236c-00b9-45b7-b0fa-dd2cda4e55ea content 90x120 canvas (92, 120) -> out.png
```

### Decode one slot by asset UUID

Looks up the slot whose 16-byte trailer UUID matches (case-insensitive):

```
.venv/bin/python3 ithmb_decode.py --uuid thumbs/4532.ithmb DA5C236C-00B9-45B7-B0FA-DD2CDA4E55EA out.png
```

### Decode every non-empty slot

```
.venv/bin/python3 ithmb_decode.py --all thumbs 3356 out3356
.venv/bin/python3 ithmb_decode.py --all thumbs 4133 out4133
.venv/bin/python3 ithmb_decode.py --all thumbs 4532 out4532
```

Output (one PNG per non-empty slot, named `<index:05d>.png`; empty slots are skipped):

```
fmt 4532: 16003 decoded, 7816 empty, 0 bad, of 23819 slots -> out4532
```

### Exit codes / errors

- `--uuid` with no matching UUID: prints `UUID not found`, exits 1.
- Empty (all-zero) slot in single-slot mode: prints `slot N: empty`, exits 1.
- Corrupt trailer (zero width/height or non-zero reserved field): raises
  `ValueError`; counted as `bad` in `--all` mode.

## What you get

- **PNGs ready to view**: orientation is already applied by Photos, and the slot
  trailer dims are the *displayed* (upright) dims. You only need to rotate if you
  want to recover the original *sensor* orientation from `ZASSET.ZORIENTATION` in
  `database/Photos.sqlite`. PIL's `rotate()` is CCW-positive, and EXIF 6 means
  "rotate 90° CW to display", so undoing it is a 90° CCW rotation:

  | ZORIENTATION | EXIF | To recover sensor orientation |
  |--------------|------|-------------------------------|
  | 1            | up   | none |
  | 3            | 180  | `Image.rotate(180, expand=True)` |
  | 6            | 90 CW | `Image.rotate(90, expand=True)` |
  | 8            | 90 CCW | `Image.rotate(-90, expand=True)` |

- Mapping index → asset: `ZASSET.ZTHUMBNAILINDEX` ↔ slot index; the slot trailer also
  embeds the UUID as a cross-check. Original file path if you have `originals/`:
  `originals/<ZDIRECTORY>/<ZFILENAME>`.

## Library use

```python
from ithmb_decode import decode_slot, to_rgb

r = decode_slot("thumbs/4532.ithmb", 4532, 0)
if r is not None:            # None = empty slot
    rgb = to_rgb(r["bgra"])  # upright RGB, orientation applied
    # r["uuid"], r["w"], r["h"], r["canvas"] also available
```

## Implementation notes

- One BC7 block = 4×4 texels = 16 bytes; slots are `[payload][zero pad][28-byte trailer]`.
- Canvas = content dims rounded up to multiples of 4 (e.g. 90×120 → 92×120); pad blocks
  replicate edge texels, so trimming to the content rect is optional.
- Channel order in blocks is BGRA (premultiplied); `to_rgb` swaps to RGB.
- Format is inferred from the filename (e.g. `4532.ithmb` → fmt 4532); supported
  formats: 3356 (slot 1052 B), 4133 (4124 B), 4532 (14428 B).

## Verified against

- 48,009 slots across all three formats: 16,003 decoded / 7,816 empty / **0 bad** each,
  matching database statistics exactly.
- Ground-truth probes (solid colors, ramps, single-pixel impulses, checkerboards)
  imported into a scratch Photos library: all decode to the known source pixels
  (BC7's lossy quantization accounts for ±1-level noise).
- Cross-format consistency: the same asset decoded from 3356/4133/4532 yields the
  same image content.
