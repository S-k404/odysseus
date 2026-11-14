"""Lure of Passion: find the save password among the string constants of the game's compiled scripts (read-only).
Godot FileAccessEncrypted with a password: key = SHA-256(password); file = md5(16) length(8) iv(16) AES-256-CFB data.
"""
import compression.zstd as zstd
import ctypes, hashlib, re, struct, sys

pck, save = sys.argv[1:3]
cc = ctypes.CDLL("/usr/lib/system/libcommonCrypto.dylib")


def ecb_enc(key, data):
    out = ctypes.create_string_buffer(len(data) + 16); moved = ctypes.c_size_t(0)
    rc = cc.CCCrypt(0, 0, 2, key, len(key), None, data, len(data), out, len(out), ctypes.byref(moved))
    return out.raw[: moved.value] if rc == 0 else None


raw = open(save, "rb").read()
assert raw[:4] == b"GDEC"
md5, length = raw[4:20], struct.unpack_from("<Q", raw, 20)[0]
iv, ct = raw[28:44], raw[44:]
ct = ct[: (len(ct) // 16) * 16]


def try_key(key):
    ks = ecb_enc(key, iv + ct[:-16])
    if ks is None:
        return None
    p = bytes(a ^ b for a, b in zip(ct, ks))
    return p if hashlib.md5(p[:length]).digest() == md5 else None


f = open(pck, "rb"); hdr = f.read(32); fb, = struct.unpack_from("<Q", hdr, 24)
f.seek(96); cnt, = struct.unpack("<I", f.read(4)); ents = []
for _ in range(cnt):
    sl, = struct.unpack("<I", f.read(4)); path = f.read(sl).rstrip(b"\0").decode("utf-8", "replace")
    off, size = struct.unpack("<QQ", f.read(16)); f.read(20); ents.append((path, off, size))

cands, enc_scripts, n = set(), [], 0
for path, off, size in ents:
    if not path.endswith(".gdc"):
        continue
    f.seek(fb + off); d = f.read(size)
    try:
        body = zstd.decompress(d[12:])
    except Exception as e:
        print("zstd failed", path, repr(e)[:60]); continue
    n += 1
    x = bytes(c ^ 0xb6 for c in body)
    if re.search(rb"encrypted", x) or re.search(rb"e.{0,3}n.{0,3}c.{0,3}r.{0,3}y.{0,3}p.{0,3}t.{0,3}e.{0,3}d", x):
        enc_scripts.append(path)
    for m in re.finditer(rb"[\x20-\x7e]{3,64}", body):
        cands.add(m.group().decode("ascii"))
print(f"{n} scripts decompressed; {len(enc_scripts)} mention 'encrypted': {[p[-50:] for p in enc_scripts[:6]]}; {len(cands)} candidate strings", flush=True)

for s in sorted(cands):
    sb = s.encode()
    keys = [("md5-hex (open_encrypted_with_pass)", hashlib.md5(sb).hexdigest().encode()), ("sha256", hashlib.sha256(sb).digest())]
    if len(sb) == 32:
        keys.append(("raw 32-byte key", sb))
    if len(sb) == 33:                      # a stray neighbouring byte may have been captured
        keys += [("raw, first 32", sb[:32]), ("raw, last 32", sb[1:])]
    for kname, key in keys:
        p = try_key(key)
        if p is not None:
            print(f"FOUND password={s!r} ({kname}); plaintext head {p[:80]!r}")
            open(sys.argv[3], "wb").write(p) if len(sys.argv) > 3 else None
            sys.exit(0)
print("no candidate string worked")
