"""Decrypt Easy Save 3 files with a known password and summarise them (read-only).
usage: es3_dump.py <password> <file> [<file> ...]
"""
import hashlib
import json
import os
import sys

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "es3_probe.py")).read().split("meta, *saves = sys.argv[1:]")[0]
ns = {}
exec(compile(src, "helpers", "exec"), ns)
aes_cbc_decrypt, valid_plain = ns["aes_cbc_decrypt"], ns["valid_plain"]

pw, *files = sys.argv[1:]
for f in files:
    d = open(f, "rb").read()
    iv, ct = d[:16], d[16:]
    key = hashlib.pbkdf2_hmac("sha1", pw.encode(), iv, 100, 16)
    text = valid_plain(aes_cbc_decrypt(key, iv, ct)) if len(d) % 16 == 0 and len(d) >= 32 else None
    rel = f.split("LocalLow/")[-1]
    if text is None:
        print(f"{rel}: does not decrypt with this password")
        continue
    try:
        obj = json.loads(text)
    except ValueError as e:
        print(f"{rel}: decrypts, {len(text)} chars, not plain JSON ({e}); head {text[:120]!r}")
        continue
    print(f"{rel}: decrypts, {len(obj)} keys")
    for k, v in list(obj.items())[:int(os.environ.get('N', '60'))]:
        if isinstance(v, dict) and "value" in v:
            val = v["value"]
            s = json.dumps(val, ensure_ascii=False)
            print(f"   {k} [{v.get('__type', '?').split(',')[0]}] = {s[:90]}{'...' if len(s) > 90 else ''}")
        else:
            print(f"   {k} = {json.dumps(v, ensure_ascii=False)[:90]}")
