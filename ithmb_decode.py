#!/usr/bin/env python3
"""
macOS Photos .ithmb (PLImageTable slot file) decoder — modern format (thumbnailConfiguration v31).

FORMAT (fully reverse-engineered & validated):
  Container: each <fmt>.ithmb = fixed-size slots, no file header.
    slot sizes: 3356→1052 B, 4133→4124 B, 4532→14428 B
    slot = [BC7 payload][zero pad][28-byte trailer]
    trailer = [16 B asset UUID][u32 contentWidth][u32 contentHeight][u32 zero]
    slot index = ZASSET.ZTHUMBNAILINDEX in Photos.sqlite
    empty (deleted) slots are all-zero.
  Payload: BC7 (DXGI_FORMAT_BC7_UNORM / at_block_format_bc7), 4x4 blocks, 16 B/block,
    channels BGRA, premultiplied alpha (encoded by AppleTextureEncoder via ImageIO:
    CGImageDestination type org.khronos.ktx + kCGImagePropertyEncoder=kCGImagePropertyBCEncoder,
    then PLTableThumbnailEncoderResult.entryDataForEntryLength: strips the 64-byte KTX1
    header and appends the 28-byte table footer).
  Canvas: raster = content dims upright (orientation already applied by Photos; rotate per
    ZASSET.ZORIENTATION to recover original aspect), each side rounded up to a multiple of 4;
    pad blocks replicate edge content.

USAGE:
  ithmb_decode.py <thumbs>/<fmt>.ithmb <index> [out.png]
  ithmb_decode.py --all <thumbs_dir> <fmt> [outdir]      # decode every non-empty slot
  ithmb_decode.py --uuid <thumbs>/<fmt>.ithmb <UUID> [out.png]

Dependencies: numpy + texture2ddecoder (pip); Pillow only for PNG output.
"""
import sys, os, struct, uuid as uuidlib

SLOT_SIZE = {3356: 1052, 4133: 4124, 4532: 14428}
BLOCK = 16

def canvas_dims(w, h):
    """Raster canvas = content dims (upright, orientation already applied), each side rounded up to a multiple of 4."""
    return (w + 3) // 4 * 4, (h + 3) // 4 * 4

def read_slot(path, fmt, index):
    ss = SLOT_SIZE[fmt]
    with open(path, 'rb') as f:
        f.seek(index * ss)
        slot = f.read(ss)
    if len(slot) != ss:
        raise IOError(f'short read (need {ss}, got {len(slot)})')
    if not any(slot):
        return None  # empty/deleted slot
    trailer = slot[-28:]
    w, h, zero = struct.unpack('<III', trailer[16:])
    if zero != 0 or w == 0 or h == 0:
        raise ValueError(f'invalid trailer: w={w} h={h} zero={zero}')
    cw, ch = canvas_dims(w, h)
    nblocks = (cw // 4) * (ch // 4)
    return slot[:nblocks * BLOCK], w, h, trailer[:16], cw, ch

def decode_bc7(payload, cw, ch):
    """Decode BC7 payload to (ch, cw, 4) uint8 BGRA."""
    import texture2ddecoder
    import numpy as np
    out = texture2ddecoder.decode_bc7(payload, cw, ch)
    return np.frombuffer(out, dtype=np.uint8).reshape(ch, cw, 4)

def to_rgb(bgra):
    """BGRA (premultiplied; alpha=255 for photo thumbs) -> RGB array."""
    rgb = bgra[..., :3].copy()
    rgb[..., 0] = bgra[..., 2]
    rgb[..., 2] = bgra[..., 0]
    return rgb

def save_png(rgb, path):
    from PIL import Image
    Image.fromarray(rgb, 'RGB').save(path)

def decode_slot(path, fmt, index):
    r = read_slot(path, fmt, index)
    if r is None:
        return None
    payload, w, h, uuid_b, cw, ch = r
    bgra = decode_bc7(payload, cw, ch)
    return {'uuid': uuidlib.UUID(bytes=uuid_b), 'w': w, 'h': h, 'canvas': (cw, ch), 'bgra': bgra}

def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return 2
    if a[0] == '--all':
        thumbs, fmt, outdir = a[1], int(a[2]), a[3]
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(thumbs, f'{fmt}.ithmb')
        n = os.path.getsize(path) // SLOT_SIZE[fmt]
        ok = empty = bad = 0
        for i in range(n):
            try:
                r = decode_slot(path, fmt, i)
            except Exception:
                bad += 1; continue
            if r is None:
                empty += 1; continue
            save_png(to_rgb(r['bgra']), os.path.join(outdir, f'{i:05d}.png'))
            ok += 1
        print(f'fmt {fmt}: {ok} decoded, {empty} empty, {bad} bad, of {n} slots -> {outdir}')
        return 0
    if a[0] == '--uuid':
        path, want, out = a[1], a[2].upper(), a[3] if len(a) > 3 else 'out.png'
        fmt = int(os.path.basename(path).split('.')[0])
        n = os.path.getsize(path) // SLOT_SIZE[fmt]
        for i in range(n):
            r = decode_slot(path, fmt, i)
            if r and str(r['uuid']).upper() == want:
                save_png(to_rgb(r['bgra']), out)
                print(f'index {i}: {r["uuid"]} content {r["w"]}x{r["h"]} canvas {r["canvas"]} -> {out}')
                return 0
        print('UUID not found'); return 1
    path, index = a[0], int(a[1])
    out = a[2] if len(a) > 2 else 'out.png'
    fmt = int(os.path.basename(path).split('.')[0])
    r = decode_slot(path, fmt, index)
    if r is None:
        print(f'slot {index}: empty'); return 1
    save_png(to_rgb(r['bgra']), out)
    print(f'index {index}: {r["uuid"]} content {r["w"]}x{r["h"]} canvas {r["canvas"]} -> {out}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
