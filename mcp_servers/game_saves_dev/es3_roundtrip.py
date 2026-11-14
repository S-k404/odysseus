import importlib.util, glob, json, os
from pathlib import Path
spec = importlib.util.spec_from_file_location("gss", os.path.expanduser("~/Documents/Docker/Odysseus/mcp_servers/game_save_server.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
comp = Path.home() / "Library/Application Support/Steam/steamapps/compatdata"
ll = "pfx/drive_c/users/steamuser/AppData/LocalLow"
files = [comp/"4143744370"/ll/"Studio Ginkgo/ISEKAI QUEST/0.sav", comp/"4143744370"/ll/"Studio Ginkgo/ISEKAI QUEST/config"]
files += [Path(p) for p in glob.glob(str(comp/"2570448322"/ll/"InstantArrow/ルーザーメーカー/save/**/*.es3"), recursive=True)]
files += [f for f in (comp/"2553943689"/ll/"SheableSoft/SecretFlasherManaka").rglob("*.sd") if ".bak" not in str(f)]
ident = same_data = fail = 0; notes = []
for f in files:
    raw = f.read_bytes()
    try:
        fmt, data = m.decode(f); assert fmt in ("es3", "es3-text"), fmt
        out = m.encode(fmt, data, raw, f)
        if out == raw: ident += 1; continue
        pw = m._es3_password(f)
        a, b = m._es3_decrypt(raw, pw), m._es3_decrypt(out, pw)
        if json.loads(a.decode("utf-8-sig")) == json.loads(b.decode("utf-8-sig")): same_data += 1; notes.append((f.name, "same data, text differs", len(a), len(b)))
        else: fail += 1; notes.append((f.name, "DATA differs"))
    except Exception as e:
        fail += 1; notes.append((f.name, repr(e)[:120]))
print(f"{len(files)} files: {ident} byte-identical, {same_data} same data (text differs), {fail} failed")
for n in notes[:8]: print("  ", n)
