"""PBKDF2 (.NET Rfc2898DeriveBytes) password search for a base64 AES save (read-only).
usage: pbkdf2_probe.py <game *_Data dir> <base64 save> <part> <parts>
Key = first 32 (or 16) bytes of PBKDF2-HMAC-SHA1(password, salt, iterations), IV = the next 16 bytes, AES-CBC/PKCS7.
Salts tried: the well-known 'Ivan Medvedev' sample salt, an empty-ish 8-byte salt, and each candidate used as its own salt.
"""
import base64, ctypes, gzip, hashlib, os, re, struct, sys, zlib

cc = ctypes.CDLL("/usr/lib/system/libcommonCrypto.dylib")


def cbc_dec(key, iv, data, pad=False):
    out = ctypes.create_string_buffer(len(data) + 16); moved = ctypes.c_size_t(0)
    rc = cc.CCCrypt(1, 0, 1 if pad else 0, key, len(key), iv, data, len(data), out, len(out), ctypes.byref(moved))
    return out.raw[: moved.value] if rc == 0 else None


def printable(b):
    return sum(1 for c in b if c in (9, 10, 13) or 32 <= c < 127) / max(1, len(b))


def good(p):
    if p is None: return False
    if printable(p) > 0.9: return True
    for fn in (gzip.decompress, zlib.decompress):
        try: return len(fn(p)) > 8
        except Exception: pass
    return False


def literals(path):
    b = open(path, "rb").read()
    sl_off, sl_size, sld_off, _ = struct.unpack_from("<4i", b, 8)
    out = set()
    for i in range(sl_size // 8):
        n, idx = struct.unpack_from("<II", b, sl_off + 8 * i)
        try: s = b[sld_off + idx: sld_off + idx + n].decode("utf-8")
        except UnicodeDecodeError: continue
        if 1 <= len(s) <= 64 and s.isprintable(): out.add(s)
    return out


data_dir, save, part, parts = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
cands = {"password"} | literals(os.path.join(data_dir, "il2cpp_data", "Metadata", "global-metadata.dat"))
runs = re.compile(rb"[\x21-\x7e]{4,48}")
for name in sorted(os.listdir(data_dir)):
    p = os.path.join(data_dir, name)
    if os.path.isfile(p) and name.startswith(("globalgamemanagers", "level", "sharedassets", "resources")) and not name.endswith((".resS", ".resource")) and os.path.getsize(p) < 300_000_000:
        for m in runs.finditer(open(p, "rb").read()): cands.add(m.group().decode("ascii"))
cands = sorted(cands)[part::parts]
b = base64.b64decode(open(save, "rb").read().strip())
assert len(b) % 16 == 0
SALTS = [bytes([0x49, 0x76, 0x61, 0x6e, 0x20, 0x4d, 0x65, 0x64, 0x76, 0x65, 0x64, 0x65, 0x76]), b"salt", b"Salt", b"12345678", bytes(8)]
tried = 0
for s in cands:
    sb = s.encode("utf-8")
    for salt in SALTS + [sb if len(sb) >= 8 else sb + bytes(8 - len(sb))]:
        for iters in (1000,):
            km = hashlib.pbkdf2_hmac("sha1", sb, salt, iters, 48)
            for klen in (32, 16):
                key, iv = km[:klen], km[klen:klen + 16] if klen == 32 else km[16:32]
                first = cbc_dec(key, iv, b[:16])
                tried += 1
                if first and (printable(first) == 1.0 or first[:3] == b"\x1f\x8b\x08" or first[:2] in (b"\x78\x9c", b"\x78\x01", b"\x78\xda")):
                    full = cbc_dec(key, iv, b, pad=True)
                    if good(full):
                        print(f"FOUND password={s!r} salt={salt!r} iters={iters} key={klen*8}bit plaintext {full[:80]!r}", flush=True)
                        sys.exit(0)
print(f"part {part}/{parts}: no match in {tried} derivations ({len(cands)} candidates)", flush=True)
