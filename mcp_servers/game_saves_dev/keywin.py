"""Try every high-entropy 16/32-byte window of a binary as an AES key (read-only).
usage:
  keywin.py gdec   <binary> <savegame.dat> <start> <step>     Godot FileAccessEncrypted (AES-256-CFB, MD5 check)
  keywin.py aesany <binary> <base64 save>  <start> <step>     AES-128/256 CBC (any IV) or ECB; checks that plaintext blocks look structured
"""
import base64, ctypes, hashlib, struct, sys

cc = ctypes.CDLL("/usr/lib/system/libcommonCrypto.dylib")
out = ctypes.create_string_buffer(1 << 16)
moved = ctypes.c_size_t(0)


def aes(op, key, iv, data, ecb):
    n = len(data)
    buf = out if n + 16 <= len(out) else ctypes.create_string_buffer(n + 16)
    rc = cc.CCCrypt(op, 0, 2 if ecb else 0, key, len(key), None if ecb else iv, data, n, buf, len(buf), ctypes.byref(moved))
    return buf.raw[: moved.value] if rc == 0 else None


def structured(b):
    return len(set(b)) <= 9 or all(c in (9, 10, 13) or 32 <= c < 127 for c in b)


mode, binary, save, start, step = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
buf = open(binary, "rb").read()
raw = open(save, "rb").read()
tested = 0

if mode == "gdec":
    assert raw[:4] == b"GDEC"
    md5, length = raw[4:20], struct.unpack_from("<Q", raw, 20)[0]
    iv, ct = raw[28:44], raw[44:]
    ct = ct[: (len(ct) // 16) * 16]
    for i in range(start, len(buf) - 32, step):
        w = buf[i:i + 32]
        if len(set(w)) < 24:
            continue
        tested += 1
        e = aes(0, w, None, iv, True)
        p1 = bytes(a ^ b for a, b in zip(ct[:16], e))
        t = struct.unpack_from("<I", p1)[0]
        if not (t < 0x200 or all(c in (9, 10, 13) or 32 <= c < 127 for c in p1)):
            continue
        ks = aes(0, w, None, iv + ct[:-16], True)
        if ks is None:
            continue
        p = bytes(a ^ b for a, b in zip(ct, ks))
        if hashlib.md5(p[:length]).digest() == md5:
            print(f"FOUND key at offset {i}: {w.hex()}  plaintext head {p[:60]!r}", flush=True)
            sys.exit(0)
    print(f"gdec offset%{step}=={start}: no key among {tested} windows", flush=True)
else:
    b = base64.b64decode(raw.strip())
    c1, c2 = b[:16], b[16:32]
    for size in (16, 32):
        for i in range(start, len(buf) - size, step):
            w = buf[i:i + size]
            if len(set(w)) < (size * 3 // 4):
                continue
            tested += 1
            # IV stored in front of the data: the first plaintext block can be a gzip/zlib header or text
            p1 = aes(1, w, b[:16], c1, False)
            if p1 and (p1[:3] == b"\x1f\x8b\x08" or p1[:2] in (b"\x78\x9c", b"\x78\x01", b"\x78\xda", b"\x78\x5e")):
                full = aes(1, w, b[:16], b[16:], False)
                try:
                    import gzip, zlib
                    dec = (gzip.decompress if p1[:2] == b"\x1f\x8b" else zlib.decompress)(full.rstrip(b"\x00")[: len(full) - full[-1]] if full else b"")
                    print(f"FOUND iv-in-file AES-{size*8} key at offset {i}: {w.hex()}  decompressed head {dec[:60]!r}", flush=True); sys.exit(0)
                except SystemExit:
                    raise
                except Exception:
                    pass
            for name, p in (("cbc-any-iv", aes(1, w, c1, c2, False)), ("ecb", aes(1, w, None, c2, True))):
                if p and structured(p):
                    # confirm on more blocks: most of the remaining blocks must look structured too
                    full = aes(1, w, c1, b[16:], False) if name == "cbc-any-iv" else aes(1, w, None, b, True)
                    if full:
                        blocks = [full[j:j + 16] for j in range(0, min(len(full), 16 * 64), 16)]
                        if sum(structured(x) for x in blocks) >= len(blocks) * 0.5:
                            print(f"FOUND {name} AES-{size*8} key at offset {i}: {w.hex()}  plaintext sample {full[:48]!r}", flush=True)
                            sys.exit(0)
    print(f"aesany offset%{step}=={start}: no key among {tested} windows", flush=True)
