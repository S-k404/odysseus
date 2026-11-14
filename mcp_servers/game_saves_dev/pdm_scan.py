"""Peeping Dorm Manager: find serialized fields that look like save-encryption settings (read-only)."""
import json, os, re, sys, time, UnityPy
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator
game, data, out = sys.argv[1:4]
pat = re.compile(r"key|pass|secret|salt|(^|_)iv($|_)|encrypt|cipher|aes|crypt|token|seed|sign", re.I)
SKIP = (".resS", ".resource", ".dat", ".json", ".config", ".info", ".txt")
gen = None
hits, stats = [], {}
t0 = time.time()
def walk(o, path, depth=0):
    if depth > 6: return
    if isinstance(o, dict):
        for k, v in o.items():
            p = f"{path}.{k}" if path else k
            if pat.search(str(k)) and not str(k).startswith("m_"):
                yield p, v
            yield from walk(v, p, depth + 1)
    elif isinstance(o, list):
        for i, v in enumerate(o[:200]): yield from walk(v, f"{path}[{i}]", depth + 1)
for f in sorted(os.listdir(data)):
    if f.endswith(SKIP) or not (f.endswith(".assets") or f.startswith(("level", "globalgamemanagers"))): continue
    if os.path.getsize(os.path.join(data, f)) > 400_000_000: continue
    try: env = UnityPy.load(os.path.join(data, f))
    except Exception as e: print("skip", f, repr(e)[:60], flush=True); continue
    if gen is None:
        ver = str(next(iter(env.assets)).unity_version)
        gen = TypeTreeGenerator(ver); gen.load_local_game(game); print("generator ready for", ver, flush=True)
    env.typetree_generator = gen
    n = ok = 0
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour": continue
        n += 1
        try: tt = obj.read_typetree()
        except Exception: continue
        ok += 1
        for p, v in walk(tt, ""):
            s = json.dumps(v, ensure_ascii=False, default=str)
            if s in ("0", "false", "true", '""', "[]", "null", "{}") or len(s) < 3: continue
            hits.append({"file": f, "path_id": obj.path_id, "name": tt.get("m_Name"), "field": p, "value": s[:200]})
    stats[f] = (n, ok)
    print(f"{f}: {n} MonoBehaviours, readable {ok}, hits so far {len(hits)}, {time.time()-t0:.0f}s", flush=True)
json.dump({"stats": stats, "hits": hits}, open(out, "w"), ensure_ascii=False)
print("FINISHED", len(hits), "hits", flush=True)
