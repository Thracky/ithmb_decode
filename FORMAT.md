# macOS Photos `.ithmb` — Modern Thumbnail Table Format (v31)

Reverse-engineered format specification for the `.ithmb` files found in macOS photo
libraries under `resources/derivatives/thumbs/` (macOS 26.x / Photos 11, PhotoLibrary
thumbnail configuration version 31). This is **not** the classic iPod RGB565 `.ithmb`
format; no public decoder existed for this variant before this work.

Companion tool: `ithmb_decode.py` (this directory).

## Overview

A photo library's thumbnail store is a set of *slot files*:

```
resources/derivatives/thumbs/
├── 3356.ithmb   # 32×32 grid-index thumbnails (small)
├── 4133.ithmb   # 64×48 (aspect-fit, medium)
├── 4532.ithmb   # 120×92 (aspect-fit, large)
└── thumbnailConfiguration
```

`thumbnailConfiguration` (plist):

```
PLThumbnailManagerThumbnailFormatKey     = 5005
PLThumbnailManagerThumbnailFormatsKey   = [5005, 4532, 4133, 3356]
PLThumbnailManagerVersionKey            = 31
```

Format 5005 is not table-backed (dynamically sized / baked) and has no `.ithmb` here.

## Slot file structure

Each `<fmt>.ithmb` is an array of **fixed-size slots** with no file header. File size
is always an exact multiple of the slot size.

| Format | Slot size | Payload (used) bytes | Pad bytes |
|--------|-----------|----------------------|-----------|
| 3356   | 1052      | 1024                 | 0         |
| 4133   | 4124      | 3072                 | 1024      |
| 4532   | 14428     | 11040                | 3360      |

The example below uses format 4532; others are identical in structure.

```
slot = [ BC7 payload ][ zero padding ][ 28-byte trailer ]
       └ payloadLen ─┘               └── slotSize-28 .. slotSize
```

### Trailer (28 bytes, little-endian)

| Offset | Size | Field |
|--------|------|-------|
| 0      | 16   | Asset UUID, raw 16 bytes (matches `ZASSET.ZUUID`; `ZFILENAME` is `<UUID>.<ext>`) |
| 16     | 4    | Content width  (u32) |
| 20     | 4    | Content height (u32) |
| 24     | 4    | Zero (reserved) |

Slot index into the file equals `ZASSET.ZTHUMBNAILINDEX` in `database/Photos.sqlite`:

```
slot file offset = ZTHUMBNAILINDEX × slotSize
```

(As a cross-check, `ZTHUMBNAILINDEX × 64` appears at byte offset 3 of the
`ZASSET.ZIMAGEREQUESTHINTS` blob.)

Deleted/free slots are all-zero; presence of a non-zero trailer is the validity check.

## Payload: BC7

The payload is **DXGI_FORMAT_BC7_UNORM** ("BC7"), 4×4 texel blocks of 16 bytes each:

- Block grid: `ceil(w/4) × ceil(h/4)` blocks, **raster order** (row-major), no padding
  between block rows.
- Channels: **BGRA**, **premultiplied alpha**. Thumbnails are opaque (alpha = 255), so
  decoding is simply R↔B swap. (Byte order matches what
  `at_encoder_create(at_texel_format_bgra8_unorm, at_alpha_premultiplied,
  at_block_format_bc7, at_alpha_premultiplied, …)` from `/usr/lib/libate.dylib`
  (AppleTextureEncoder) produces.)
- Canvas: content is stored **upright** — canvas dims = trailer dims with each side
  rounded up to a multiple of 4. EXIF orientation is already applied by Photos; rotate
  the canvas per `ZASSET.ZORIENTATION` (6 = 90° CW, 8 = 90° CCW, 3 = 180°) to recover the
  original aspect.
- Edge blocks beyond the content rect replicate edge texels (e.g. a 90×120 image stored
  on a 92×120 canvas has 2 pad columns that copy column 89's content).

Payload byte length: `blocks × 16`.

| Format | Content (example) | Canvas | Blocks |
|--------|-------------------|--------|--------|
| 3356   | 32×32             | 32×32  | 8×8 = 64 |
| 4133   | 64×48 (or 48×64)  | 64×48 / 48×64 | 16×12 = 192 |
| 4532   | 120×90 (or 90×120)| 120×92 / 92×120 | 30×23 = 690 |

Everything between payload end and the trailer is zero padding.

## How Photos encodes these (implementation notes)

From disassembly of PhotoLibraryServices / PhotoLibraryServicesCore (macOS 26.6
dyld cache, version 860.0.170) and ImageIO:

1. `PLTableThumbnailEncoder.encodeThumbnailImage:toFormat:withUUID:error:` downscales
   the source (aspect-fit via `PLCGSizeScaledToFitSize`, 8bpc RGBA,
   `kCGImageAlphaPremultipliedLast`) then hands it to ImageIO.
2. ImageIO `CGImageDestination` with MIME type `org.khronos.ktx` and properties
   `{kCGImagePropertyEncoder: kCGImagePropertyBCEncoder}` compresses via
   `at_encoder_compress_texels` (AppleTextureEncoder) and wraps the BC7 blocks in a
   **KTX1** container.
3. `PLTableThumbnailEncoderResult.entryDataForEntryLength:` strips the 64-byte KTX1
   header and returns just the (block) data.
4. `PLPositionalTable writeEntryData:toIndex:` pwrite's payload+footer into the slot
   (class used per format: `PLPositionalBC7ImageTable`, `metalPixelFormat = 0x98`).

Reading (`PLPositionalImageTable readImageDataAtIndex:…` /
`PLPositionalBC7ImageTable createImageWithIdentifier:orIndex:`) reverses this: the slot
payload is re-wrapped in a KTX1 header (glInternalFormat 0x98 = BC7 / MTLPixelFormat 0x98)
and decoded via CGImageSource.

## Example: manual decode of slot 0 of 4532.ithmb

```python
import struct, texture2ddecoder, numpy as np
from PIL import Image

slot_size, fmt = 14428, 4532
data = open("thumbs/4532.ithmb", "rb").read()
slot = data[0:slot_size]                    # ZTHUMBNAILINDEX = 0
w, h, zero = struct.unpack("<III", slot[-28+16:-28+28])
uuid = slot[:16]
cw, ch = (w+3)//4*4, (h+3)//4*4             # upright canvas, rounded up to 4
blocks = (cw//4) * (ch//4)
payload = slot[:blocks*16]
bgra = texture2ddecoder.decode_bc7(payload, cw, ch)
a = np.frombuffer(bgra, dtype=np.uint8).reshape(ch, cw, 4)
rgb = a[:, :, [2, 1, 0, 3]]                # BGRA -> RGBA
Image.fromarray(rgb[:, :, :3], "RGB").save("slot0.png")
```

## Dataset statistics (verification corpus)

- 23,819 slots per format × 3 formats; 16,003 non-empty, 7,816 empty — identical counts
  across all three formats, matching the 15,820 DB rows with non-null
  `ZTHUMBNAILINDEX` (plus free-list reuse).
- All 48,009 slots decode with zero errors; 15/15 random slots verified against
  `ZASSET` (UUID + photographic content).

## References

- AppleTextureEncoder public header:
  `/Library/Developer/CommandLineTools/SDKs/MacOSX*.sdk/usr/include/AppleTextureEncoder.h`
- Khronos KTX1 specification (for the container Photos strips)
- Microsoft BC7 (BC7_UNORM) block format specification
