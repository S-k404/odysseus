"""Find an Easy Save 3 password among an IL2CPP game's own string literals (read-only).

ES3 AES file = 16-byte IV + AES-128-CBC/PKCS7 ciphertext; key = PBKDF2-HMAC-SHA1(password, salt=IV, 100 iterations, 16 bytes).
usage: es3_probe.py <global-metadata.dat> <save file> [<save file> ...]
"""
import ctypes
import hashlib
import struct
import sys

cc = ctypes.CDLL("/usr/lib/system/libcommonCrypto.dylib")


def aes_cbc_decrypt(key, iv, data):
    out = ctypes.create_string_buffer(len(data) + 16)
    moved = ctypes.c_size_t(0)
    # kCCDecrypt=1, kCCAlgorithmAES=0, options=0 (no padding: checked by hand)
    rc = cc.CCCrypt(1, 0, 0, key, len(key), iv, data, len(data), out, len(out), ctypes.byref(moved))
    return out.raw[: moved.value] if rc == 0 else None


def literals(path):
    b = open(path, "rb").read()
    magic, version = struct.unpack_from("<Ii", b, 0)
    assert magic == 0xFAB11BAF, hex(magic)
    sl_off, sl_size, sld_off, _ = struct.unpack_from("<4i", b, 8)
    seen = set()
    for i in range(sl_size // 8):
        length, idx = struct.unpack_from("<II", b, sl_off + 8 * i)
        raw = b[sld_off + idx: sld_off + idx + length]
        try:
            s = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if 1 <= len(s) <= 64 and "\n" not in s:
            seen.add(s)
    return version, sorted(seen)


def valid_plain(p):
    if not p:
        return None
    pad = p[-1]
    if not 1 <= pad <= 16 or p[-pad:] != bytes([pad]) * pad:
        return None
    body = p[:-pad]
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text


meta, *saves = sys.argv[1:]
version, cands = literals(meta)
print(f"metadata v{version}: {len(cands)} usable string literals", flush=True)
cands = ["password", ""] + cands
for sp in saves:
    data = open(sp, "rb").read()
    if len(data) < 32 or len(data) % 16:
        print(f"{sp}: size {len(data)} is not IV + 16-byte blocks, skipped")
        continue
    iv, ct = data[:16], data[16:]
    found = None
    for pw in cands:
        key = hashlib.pbkdf2_hmac("sha1", pw.encode("utf-8"), iv, 100, 16)
        first = aes_cbc_decrypt(key, iv, ct[:16])
        if first is None or not all(c in (9, 10, 13) or 32 <= c < 127 for c in first):
            continue
        text = valid_plain(aes_cbc_decrypt(key, iv, ct))
        if text is not None:
            found = (pw, text)
            break
    if found:
        print(f"{sp}: PASSWORD = {found[0]!r}; plaintext starts: {found[1][:160]!r}")
    else:
        print(f"{sp}: no literal worked")
