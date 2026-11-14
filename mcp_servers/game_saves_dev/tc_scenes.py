"""List the scene name (first string) of every dialogue MonoBehaviour in Third Crisis's scene bundles (read-only)."""
import json, os, sys, UnityPy
root = sys.argv[1]
def first_string(d):
    n = int.from_bytes(d[28:32], "little") if len(d) > 40 else 0
    # MonoBehaviour header is 28 bytes (gameobject ppid 12, enabled 4, script ppid 12) then the object name string
    for off in (28, 32, 0):
        n = int.from_bytes(d[off:off+4], "little")
        if 1 <= n <= 160 and off + 4 + n <= len(d):
            s = d[off+4:off+4+n]
            try:
                t = s.decode("utf-8")
                if t.isprintable(): return t
            except UnicodeDecodeError: pass
    return None
out = {}
for dp, _, fs in os.walk(root):
    for f in sorted(fs):
        if not f.endswith(".bundle") or "scenes" not in f: continue
        try: env = UnityPy.load(os.path.join(dp, f))
        except Exception as e: print("skip", f, repr(e)[:50], file=sys.stderr); continue
        for o in env.objects:
            if o.type.name != "MonoBehaviour": continue
            try: d = o.get_raw_data()
            except Exception: continue
            if b"line_0" in d or b"line_1" in d:
                s = first_string(d)
                if s: out.setdefault(s, []).append(f)
json.dump({k: sorted(set(v)) for k, v in out.items()}, open(sys.argv[2], "w"), ensure_ascii=False, indent=0)
print(len(out), "distinct scene names from", len({b for v in out.values() for b in v}), "bundles")
