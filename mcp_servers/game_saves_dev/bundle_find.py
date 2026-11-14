"""Find which Unity bundle objects contain given strings (read-only).
usage: bundle_find.py <dir or file> <needle> [<needle> ...]"""
import os, sys, UnityPy
path, *needles = sys.argv[1:]
nb = [n.encode("utf-8") for n in needles]
files = [path] if os.path.isfile(path) else [os.path.join(d, f) for d, _, fs in os.walk(path) for f in fs if f.endswith((".bundle", ".unity3d", ".assets"))]
SKIP = {"Texture2D", "AudioClip", "Mesh", "Sprite", "Shader", "AnimationClip", "VideoClip", "Font"}
for fp in sorted(files):
    try:
        env = UnityPy.load(fp)
    except Exception as e:
        print("skip", os.path.basename(fp), repr(e)[:60], flush=True); continue
    for obj in env.objects:
        if obj.type.name in SKIP: continue
        try: d = obj.get_raw_data()
        except Exception: continue
        hit = [n.decode() for n in nb if n in d]
        if hit:
            print(f"{os.path.basename(fp)} | {obj.type.name} path_id={obj.path_id} size={len(d)} | hits={hit}", flush=True)
