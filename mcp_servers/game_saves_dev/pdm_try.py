"""Combined password/key search for a base64 AES save, over a candidate-string file (read-only).
usage: pdm_try.py <candidates.txt> <base64 save> <part> <parts>
Schemes: key = s | md5(s) | sha256(s) | sha1(s)[:16] with IV in file / zero IV / IV=key / ECB;
         Easy Save PBKDF2-SHA1(100, salt=IV); .NET Rfc2898 PBKDF2-SHA1(1000) key+IV with several salts.
A hit must decrypt the WHOLE file to mostly printable text or a valid gzip/zlib stream.
"""
import base64, ctypes, gzip, hashlib, sys, zlib

cc = ctypes.CDLL("/usr/lib/system/libcommonCrypto.dylib")


def crypt(key, iv, data, ecb=False, pad=False):
    out = ctypes.create_string_buffer(len(data) + 16); moved = ctypes.c_size_t(0)
    rc = cc.CCCrypt(1, 0, (2 if ecb else 0) | (1 if pad else 0), key, len(key), None if ecb else iv, data, len(data), out, len(out), ctypes.byref(moved))
    return out.raw[: moved.value] if rc == 0 else None


def pr(b):
    return sum(1 for c in b if c in (9, 10, 13) or 32 <= c < 127) / max(1, len(b))


def first_ok(b):
    return b is not None and (pr(b) == 1.0 and b[:1] in (b"{", b"[", b"<", b'"') + tuple(bytes([c]) for c in range(48, 58)) + tuple(bytes([c]) for c in range(65, 91))
                              or b[:3] == b"\x1f\x8b\x08" or b[:2] in (b"\x78\x9c", b"\x78\x01", b"\x78\xda", b"\x78\x5e"))


def good(full):
    if full is None:
        return False
    if pr(full) > 0.9:
        return True
    for fn in (gzip.decompress, zlib.decompress):
        try:
            return len(fn(full)) > 8
        except Exception:
            pass
    return False


cands_file, save, part, parts = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
cands = [l.rstrip("\n") for l in open(cands_file, encoding="utf-8")][part::parts]
b = base64.b64decode(open(save, "rb").read().strip())
assert len(b) % 16 == 0 and len(b) >= 48
iv0, rest = b[:16], b[16:]
SALTS = [bytes([0x49, 0x76, 0x61, 0x6e, 0x20, 0x4d, 0x65, 0x64, 0x76, 0x65, 0x64, 0x65, 0x76]), b"salt", b"Salt", b"12345678", bytes(8)]
tried = 0


def hit(how, s, full):
    print(f"FOUND password/key string={s!r} scheme={how} plaintext head {full[:80]!r}", flush=True)
    sys.exit(0)


for s in cands:
    sb = s.encode("utf-8")
    keys = ([("raw", sb)] if len(sb) in (16, 24, 32) else []) + [("md5", hashlib.md5(sb).digest()), ("sha256", hashlib.sha256(sb).digest()), ("sha1-16", hashlib.sha1(sb).digest()[:16])]
    # a key written as base64 or hex text
    if len(sb) >= 16 and len(sb) % 4 == 0:
        try:
            kb = base64.b64decode(sb, validate=True)
            if len(kb) in (16, 24, 32): keys.append(("base64-decoded", kb))
        except Exception:
            pass
    if len(sb) in (32, 48, 64):
        try: keys.append(("hex-decoded", bytes.fromhex(s)))
        except ValueError: pass
    for kn, k in keys:
        for sch, iv, ct, ecb in (("iv-in-file", iv0, rest, False), ("zero-iv", bytes(16), b, False), ("iv=key", k[:16], b, False), ("ecb", None, b, True)):
            tried += 1
            if first_ok(crypt(k, iv, ct[:16], ecb)):
                full = crypt(k, iv, ct, ecb, pad=True)
                if good(full):
                    hit(f"{kn}/{sch}", s, full)
    # the IV may be a separate field: with the key alone, plaintext block 2 (CBC with IV = block 1) must look like text
    for kn, k in keys:
        tried += 1
        p2 = crypt(k, b[:16], b[16:32])
        if p2 is not None and pr(p2) == 1.0 and len(set(p2)) > 4:
            full = crypt(k, b[:16], b[16:], pad=False)
            if full is not None and pr(full[:-16]) > 0.9:
                hit(f"{kn}/any-iv (block 2 is text)", s, full)
    key = hashlib.pbkdf2_hmac("sha1", sb, iv0, 100, 16)
    if first_ok(crypt(key, iv0, rest[:16])):
        full = crypt(key, iv0, rest, pad=True)
        if good(full):
            hit("easy-save pbkdf2-100", s, full)
    for salt in SALTS + [sb if len(sb) >= 8 else sb + bytes(8 - len(sb))]:
        km = hashlib.pbkdf2_hmac("sha1", sb, salt, 1000, 48)
        for klen in (32, 16):
            key, iv = km[:klen], (km[klen:klen + 16] if klen == 32 else km[16:32])
            tried += 1
            if first_ok(crypt(key, iv, b[:16])):
                full = crypt(key, iv, b, pad=True)
                if good(full):
                    hit(f"rfc2898-1000 salt={salt!r} {klen*8}-bit", s, full)
print(f"part {part}/{parts}: no match ({len(cands)} candidates, {tried} trials)", flush=True)
