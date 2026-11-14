"""Run a Ren'Py game's own Linux engine headless (Docker, linux/amd64) on an APFS clone of the game
with zz_odysseus_unlock.rpy installed, and report what the game sees after init.
usage: [ODY_KEEP_INSTALLED=1] renpy_verify.py <game dir> <unlock spec json> <probe expr json> -> prints report
ODY_KEEP_INSTALLED=1 tests the zz_odysseus_unlock.rpy already in the game folder instead of regenerating it from the spec"""
import json, os, shutil, subprocess, sys, zlib
from pathlib import Path
sys.path.insert(0, os.path.expanduser("~/Documents/Docker/Odysseus/mcp_servers"))
import game_save_server as g

src, spec, probes = Path(sys.argv[1]), json.loads(sys.argv[2]), json.loads(sys.argv[3])
work = Path(os.environ.get("TMPDIR", "/tmp")) / "odysseus-renpy-verify" / src.name
if work.exists():
    shutil.rmtree(work)
work.parent.mkdir(exist_ok=True)
subprocess.run(["cp", "-cR", str(src), str(work)], check=True)  # APFS clone: copy-on-write, original untouched
game = next(p for p in [work / "game", *work.glob("*/game")] if p.is_dir())
for f in game.glob("presplash*"):  # clone only: the presplash window needs a real display
    f.unlink()
if not (os.environ.get("ODY_KEEP_INSTALLED") and (game / g._RENPY_UNLOCK).exists()):  # else test the file as installed
    (game / g._RENPY_UNLOCK).write_text(g._renpy_unlock_source(spec.get("mark_all_seen", True), spec.get("sets", []), spec.get("adds", []), spec.get("calls", [])))
checks = ",\n".join(f"        {json.dumps(k)}: (lambda: {v})" for k, v in probes.items())
(game / "zz_odysseus_probe.rpy").write_text(f'''init 1995 python:
    import json as _j, os as _o
    _rep = {{"report": dict(_odysseus_report) if "_odysseus_report" in globals() else "unlock file did not run"}}
    _ls = [l for l in renpy.get_all_labels() if isinstance(l, basestring if str is bytes else str)]
    _rep["labels_seen"] = [sum(1 for l in _ls if renpy.seen_label(l)), len(_ls)]
    _im = renpy.list_images()
    _rep["images_seen"] = [sum(1 for i in _im if renpy.seen_image(i)), len(_im)]
    _rep["renpy"] = renpy.version()
    for _k, _f in {{
{checks}
    }}.items():
        try:
            _rep[_k] = _f()
        except Exception as e:
            _rep[_k] = "error: " + repr(e)
    with open("/g/ody_report.json", "w") as _fh:
        _j.dump(_rep, _fh, default=repr)
    _o._exit(0)
''')
sh = next(work.glob("*.sh"))
before = {f: f.stat().st_mtime for f in game.rglob("persistent")}
p = subprocess.run(["docker", "run", "--rm", "--platform", "linux/amd64", "-v", f"{work}:/g", "-e", "SDL_VIDEODRIVER=dummy",
                    "-e", "SDL_AUDIODRIVER=dummy", "-e", "HOME=/tmp/h", "odysseus-renpy-test", "sh", "-c",
                    f"cd /g && ./{sh.name} 2>&1 | tail -15"], capture_output=True, text=True, timeout=900)
rep = work / "ody_report.json"
print(json.dumps(json.loads(rep.read_text()), indent=1, ensure_ascii=False)[:3000] if rep.exists() else "NO REPORT\n" + p.stdout[-2500:] + p.stderr[-1500:])
for f in game.rglob("persistent"):
    st = "rewritten" if f.stat().st_mtime != before.get(f) else "unchanged"
    obj = g._StubUnpickler(__import__("io").BytesIO(zlib.decompress(f.read_bytes())), encoding="utf-8", errors="replace").load()
    d = getattr(obj, "_state", None) or vars(obj)
    if isinstance(d, tuple): d = d[0]
    print(f"persistent on disk ({f.relative_to(work)}, {st}): _seen_ever={len(d.get('_seen_ever') or {})} _seen_images={len(d.get('_seen_images') or {})}")
for t in ("errors.txt", "traceback.txt"):
    if (work / t).exists() or (game.parent / t).exists():
        print(t, ((work / t) if (work / t).exists() else (game.parent / t)).read_text()[:1500])
