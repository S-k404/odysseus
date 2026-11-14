"""Search for the AES scheme and key of a base64-encoded save among a game's own strings (read-only).
usage: aes_probe.py <game *_Data dir> <save file> [<save file> ...]
Schemes per candidate string s: key = s (if 16/24/32 bytes) | md5(s) | sha256(s) | sha1(s)[:16]
  IV from file (first 16 bytes) | zero IV | IV = key[:16] | ECB | Easy Save PBKDF2(s, salt=IV, 100) AES-128
A hit needs the first plaintext block to be mostly printable text, then the whole file to unpad correctly.
"""
import base64, ctypes, gzip, hashlib, os, re, struct, sys, zlib

cc = ctypes.CDLL("/usr/lib/system/libcommonCrypto.dylib")


def crypt(key, iv, data, ecb=False, pad=False):
    out = ctypes.create_string_buffer(len(data) + 16)
    moved = ctypes.c_size_t(0)
    opt = (2 if ecb else 0) | (1 if pad else 0)
    rc = cc.CCCrypt(1, 0, opt, key, len(key), None if ecb else iv, data, len(data), out, len(out), ctypes.byref(moved))
    return out.raw[: moved.value] if rc == 0 else None


def printable_ratio(b):
    return sum(1 for c in b if c in (9, 10, 13) or 32 <= c < 127) / max(1, len(b))


def texty(b):
    # a first block of real text: every byte printable, and it looks like the start of JSON/XML/CSV/INI
    return b is not None and printable_ratio(b) == 1.0 and b[:1] in (b"{", b"[", b"<", b'"') + tuple(bytes([c]) for c in range(48, 58)) + tuple(bytes([c]) for c in range(65, 91))


def packed(b):
    # first block of a gzip or zlib stream
    return b is not None and (b[:3] == b"\x1f\x8b\x08" or b[:2] in (b"\x78\x9c", b"\x78\x01", b"\x78\xda", b"\x78\x5e"))


def good(full):
    if full is None:
        return False
    if printable_ratio(full) > 0.9:
        return True
    for fn in (gzip.decompress, zlib.decompress):
        try:
            return len(fn(full)) > 8
        except Exception:
            pass
    return False


def literals(path):
    b = open(path, "rb").read()
    sl_off, sl_size, sld_off, _ = struct.unpack_from("<4i", b, 8)
    out = set()
    for i in range(sl_size // 8):
        n, idx = struct.unpack_from("<II", b, sl_off + 8 * i)
        try:
            s = b[sld_off + idx: sld_off + idx + n].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if 1 <= len(s) <= 64 and s.isprintable():
            out.add(s)
    return out


data_dir, *saves = sys.argv[1:]
cands = {"password"}
meta = os.path.join(data_dir, "il2cpp_data", "Metadata", "global-metadata.dat")
cands |= literals(meta)
runs = re.compile(rb"[\x21-\x7e]{4,48}")
for name in sorted(os.listdir(data_dir)):
    p = os.path.join(data_dir, name)
    if os.path.isfile(p) and (name.startswith(("globalgamemanagers", "level", "sharedassets", "resources")) and not name.endswith((".resS", ".resource"))) and os.path.getsize(p) < 300_000_000:
        for m in runs.finditer(open(p, "rb").read()):
            cands.add(m.group().decode("ascii"))
print(f"{len(cands)} candidate strings", flush=True)

blobs = []
for sp in saves:
    b = base64.b64decode(open(sp, "rb").read().strip())
    blobs.append((os.path.basename(sp), b))

for name, b in blobs:
    found = None
    first16, rest = b[:16], b[16:]
    for s in cands:
        sb = s.encode("utf-8")
        keys = []
        if len(sb) in (16, 24, 32):
            keys.append(("raw", sb))
        keys += [("md5", hashlib.md5(sb).digest()), ("sha256", hashlib.sha256(sb).digest()), ("sha1-16", hashlib.sha1(sb).digest()[:16])]
        for kname, k in keys:
            for scheme, iv, ct, ecb in (("iv-in-file", first16, rest, False), ("zero-iv", bytes(16), b, False), ("iv=key", k[:16], b, False), ("ecb", None, b, True)):
                if len(ct) < 16 or len(ct) % 16:
                    continue
                blk = crypt(k, iv, ct[:16], ecb)
                if texty(blk) or packed(blk):
                    full = crypt(k, iv, ct, ecb, pad=True)
                    if good(full):
                        found = (s, kname, scheme, full[:100])
                        break
            if found:
                break
        if found:
            break
        # Easy Save style
        key = hashlib.pbkdf2_hmac("sha1", sb, first16, 100, 16)
        blk = crypt(key, first16, rest[:16])
        if texty(blk) or packed(blk):
            full = crypt(key, first16, rest, pad=True)
            if good(full):
                found = (s, "pbkdf2-sha1-100", "easy-save", full[:100]); break
    print(f"{name}: " + (f"FOUND string={found[0]!r} key={found[1]} scheme={found[2]} plaintext starts {found[3]!r}" if found else "no scheme/candidate worked"), flush=True)
