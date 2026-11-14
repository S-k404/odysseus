"""Find Third Crisis's Gallery object: a MonoBehaviour with Categories[].Scenes[] (read-only).
usage: tc_gallery.py main <game root> <data dir> <out.json>          (main data files except resources.assets, with the type-tree generator)
       tc_gallery.py bundles <aa dir> <out.json> <part> <parts>"""
import json, os, sys, time, UnityPy
mode = sys.argv[1]
hits = []
def check(tt, f, pid):
    if "CategoryName" in tt and "Scenes" in tt:
        hits.append({"kind": "category", "file": f, "path_id": pid, "name": tt.get("m_Name"), "CategoryName": tt.get("CategoryName"), "Scenes": tt.get("Scenes")})
        print("CATEGORY object", f, pid, tt.get("CategoryName"), "scenes:", len(tt.get("Scenes") or []), flush=True)
    if "StartUnlocked" in tt and "PreviewDialogue" in tt and "Scene" in tt:
        hits.append({"kind": "info", "file": f, "path_id": pid, "name": tt.get("m_Name"), "Name": tt.get("Name"), "Scene": tt.get("Scene"), "Preview": tt.get("PreviewDialogue"),
                     "StartHidden": tt.get("StartHidden"), "StartUnlocked": tt.get("StartUnlocked"), "Public": tt.get("AvailableInPublic")})
    cats = tt.get("Categories")
    if isinstance(cats, list) and cats and isinstance(cats[0], dict) and "Scenes" in cats[0]:
        scenes = []
        for c in cats:
            for s in c.get("Scenes", []):
                if isinstance(s, dict): scenes.append({"cat": c.get("CategoryName"), "name": s.get("Name"), "scene": s.get("Scene"), "preview": s.get("PreviewDialogue"),
                                                        "hidden": s.get("StartHidden"), "unlocked": s.get("StartUnlocked"), "public": s.get("AvailableInPublic")})
        hits.append({"file": f, "path_id": pid, "name": tt.get("m_Name"), "categories": [c.get("CategoryName") for c in cats], "n_scenes": len(scenes), "scenes": scenes})
        print("FOUND Gallery-like object in", f, "path_id", pid, "categories", len(cats), "scenes", len(scenes), flush=True)
t0 = time.time()
if mode == "main":
    from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator
    game, data, out = sys.argv[2:5]
    gen = None
    for f in sorted(os.listdir(data)):
        if f.endswith((".resS", ".resource", ".dat", ".json", ".config", ".info")) or not (f.endswith(".assets") or f.startswith(("level", "globalgamemanagers"))): continue
        try: env = UnityPy.load(os.path.join(data, f))
        except Exception: continue
        if gen is None: gen = TypeTreeGenerator(str(next(iter(env.assets)).unity_version)); gen.load_local_game(game)
        env.typetree_generator = gen
        n = 0
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour": continue
            n += 1
            try: tt = obj.read_typetree()
            except Exception: continue
            check(tt, f, obj.path_id)
        print(f"{f}: {n} MonoBehaviours checked ({time.time()-t0:.0f}s)", flush=True)
else:
    root, out, part, parts = sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
    files = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(root) for f in fs if f.endswith(".bundle"))[part::parts]
    for fp in files:
        try: env = UnityPy.load(fp)
        except Exception: continue
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour": continue
            try: tt = obj.read_typetree()
            except Exception: continue
            check(tt, os.path.basename(fp), obj.path_id)
        print(f"{os.path.basename(fp)} done ({time.time()-t0:.0f}s)", flush=True)
json.dump(hits, open(out, "w"), ensure_ascii=False, default=str)
print("FINISHED", len(hits), "gallery-like objects", flush=True)
