"""Easy Save 3 password search over every printable string in a Unity game's serialized data (read-only).
usage: es3_probe2.py <game *_Data dir> <save file> [<save file> ...]
Candidates: IL2CPP string literals + printable ASCII runs (4..48) in *.assets, level*, globalgamemanagers*
(never .resS / .resource streams). Checks every file, accepts only a password that decrypts a whole file to
well-padded UTF-8 text.
"""
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util

spec = importlib.util.spec_from_file_location("p1", os.path.join(os.path.dirname(os.path.abspath(__file__)), "es3_probe.py"))
# reuse helpers without running its CLI part
src = open(spec.origin).read().split("meta, *saves = sys.argv[1:]")[0]
ns = {}
exec(compile(src, "es3_probe_helpers", "exec"), ns)
aes_cbc_decrypt, literals, valid_plain = ns["aes_cbc_decrypt"], ns["literals"], ns["valid_plain"]

data_dir, *saves = sys.argv[1:]
cands = set(["password"])
meta = os.path.join(data_dir, "il2cpp_data", "Metadata", "global-metadata.dat")
if os.path.isfile(meta):
    cands.update(literals(meta)[1])
runs = re.compile(rb"[\x21-\x7e]{4,48}")
scanned = 0
for name in sorted(os.listdir(data_dir)):
    p = os.path.join(data_dir, name)
    if not os.path.isfile(p) or name.endswith((".resS", ".resource", ".dat", ".json", ".config")):
        continue
    if not (name.endswith(".assets") or name.startswith(("level", "globalgamemanagers"))):
        continue
    if os.path.getsize(p) > 700_000_000:
        continue
    with open(p, "rb") as fh:
        blob = fh.read()
    for m in runs.finditer(blob):
        cands.add(m.group().decode("ascii"))
    scanned += 1
print(f"{os.path.basename(os.path.dirname(data_dir))}: {len(cands)} candidates from {scanned} data files", flush=True)

for sp in saves:
    data = open(sp, "rb").read()
    if len(data) < 32 or len(data) % 16:
        print(f"{sp}: size {len(data)} is not IV + 16-byte blocks, skipped")
        continue
    iv, ct = data[:16], data[16:]
    found = None
    for i, pw in enumerate(cands):
        key = hashlib.pbkdf2_hmac("sha1", pw.encode("utf-8"), iv, 100, 16)
        first = aes_cbc_decrypt(key, iv, ct[:16])
        if first is None or not all(c in (9, 10, 13) or 32 <= c < 127 for c in first):
            continue
        text = valid_plain(aes_cbc_decrypt(key, iv, ct))
        if text is not None:
            found = (pw, text)
            break
    short = os.path.basename(sp)
    print(f"  {short}: " + (f"PASSWORD = {found[0]!r}; plaintext starts {found[1][:140]!r}" if found else "no candidate worked"), flush=True)
