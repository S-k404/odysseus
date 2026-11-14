"""ES3 password search with a candidate file (one per line). usage: es3_probe3.py <cands.txt> <save> [<save> ...]"""
import hashlib, os, sys
ns = {}; exec(compile(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "es3_probe.py")).read().split("meta, *saves = sys.argv[1:]")[0], "h", "exec"), ns)
dec, valid = ns["aes_cbc_decrypt"], ns["valid_plain"]
cands = ["password", ""] + [l.rstrip("\n") for l in open(sys.argv[1], encoding="utf-8")]
print(len(cands), "candidates", flush=True)
for sp in sys.argv[2:]:
    d = open(sp, "rb").read()
    if len(d) < 32 or len(d) % 16: print(os.path.basename(sp), "not IV+blocks"); continue
    iv, ct = d[:16], d[16:]; found = None
    for pw in cands:
        key = hashlib.pbkdf2_hmac("sha1", pw.encode("utf-8"), iv, 100, 16)
        first = dec(key, iv, ct[:16])
        if first is None or not all(c in (9, 10, 13) or 32 <= c < 127 for c in first): continue
        t = valid(dec(key, iv, ct))
        if t is not None: found = (pw, t); break
    print(os.path.basename(sp), "->", f"PASSWORD = {found[0]!r}; starts {found[1][:120]!r}" if found else "no candidate worked", flush=True)
