"""
game_save_server.py

MCP server for inspecting and patching local single-player game saves
(Bridgeplay / Steam non-Steam shortcuts). Small tool schemas and compact
outputs so local models can drive it. Uses REA (docker image mcp/rea:games)
for .NET metadata of Unity Mono games.

Every write makes a timestamped backup next to the file and re-decodes the
written file to verify it.
"""

import asyncio
import base64
import hashlib
import io
import json
import os
import pickle
import re
import shutil
import struct
import subprocess
import time
import zlib
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("game_saves")

HOME = Path.home()
GAMES_ROOT = HOME / "Documents" / "Virtual Win11 Drive" / "Games"
STEAM = HOME / "Library" / "Application Support" / "Steam"
COMPAT = STEAM / "steamapps" / "compatdata"
CACHE = HOME / "Library" / "Caches" / "odysseus-game-saves"
REA_IMAGE = os.environ.get("REA_IMAGE", "mcp/rea:games")
DOCKER = shutil.which("docker") or next(
    (d for d in ("/usr/local/bin/docker", "/opt/homebrew/bin/docker", "/Applications/Docker.app/Contents/Resources/bin/docker") if os.path.exists(d)),
    "docker",
)
BACKUP_TAG = ".bak_odysseus_"
MAX_OUT = 12000

SAVE_EXT = re.compile(
    r"\.(rpgsave|rmmzsave|sav|save|dat|json|es3|sd|nson|cfg|ini|tres|mdrg|mdrgslot|pp|rvdata2)$|/(sav|persistent)$",
    re.I,
)
SKIP_DIR = re.compile(
    r"/(Unity|Cache|cache|GPUCache|Code Cache|shader_cache|vulkan|logs|Crash\w*|Analytics|blob_storage|"
    r"Session Storage|IndexedDB|Goldberg SteamEmu Saves|Microsoft|Temp|wine_gecko|D3DSCache)/"
)


# ---------------------------------------------------------------- games

def _read_shortcuts() -> list[dict]:
    out = []
    for vdf in STEAM.glob("userdata/*/config/shortcuts.vdf"):
        b = vdf.read_bytes()
        i = 0

        def cstr():
            nonlocal i
            j = b.index(b"\0", i)
            s = b[i:j].decode("utf-8", "replace")
            i = j + 1
            return s

        def obj():
            nonlocal i
            d = {}
            while True:
                t = b[i]
                i += 1
                if t == 8:
                    return d
                k = cstr()
                if t == 0:
                    d[k] = obj()
                elif t == 1:
                    d[k] = cstr()
                elif t == 2:
                    d[k] = struct.unpack("<I", b[i:i + 4])[0]
                    i += 4
                else:
                    raise ValueError(f"vdf type {t}")

        i = 1
        cstr()
        for v in obj().values():
            a = {k.lower(): x for k, x in v.items()}
            exe = a.get("exe", "").strip('"')
            out.append({"appid": str(a.get("appid")), "name": a.get("appname", ""), "exe": exe})
    return out


def _game_dir(exe: str) -> Path:
    p = Path(exe)
    try:
        rel = p.relative_to(GAMES_ROOT)
        # A lone exe in the Games root (e.g. an embedded-pck Godot build)
        # has no folder of its own; return the exe so folder scans skip it.
        return GAMES_ROOT / rel.parts[0] if len(rel.parts) > 1 else p
    except ValueError:
        return p.parent


def _engine(d: Path) -> str:
    if any(d.rglob("*_Data/Managed/Assembly-CSharp.dll")):
        return "unity-mono"
    if any(d.rglob("global-metadata.dat")):
        return "unity-il2cpp"
    if any(d.rglob("renpy")):
        return "renpy"
    if any(d.rglob("*.rmmzsave")) or any(d.rglob("rmmz_core.js")):
        return "rpgmaker-mz"
    if any(d.rglob("rpg_core.js")) or any(d.rglob("*.rpgsave")):
        return "rpgmaker-mv"
    if any(d.rglob("*.pck")):
        return "godot"
    if any(d.rglob("data.win")):
        return "gamemaker"
    if any(d.rglob("*.wolf")) or (d / "Data.wolf").exists():
        return "wolfrpg"
    if any(d.rglob("*-Shipping.exe")):
        return "unreal"
    return "unknown"


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", s.lower().replace("'s", ""))


def _find_game(game: str) -> dict:
    g = game.strip().lower()
    rows = _read_shortcuts()
    for r in rows:
        if r["appid"] == g:
            return r
    hits = [r for r in rows if g in r["name"].lower() or g in r["exe"].lower()]
    if not hits:
        n = _norm(game)
        hits = [r for r in rows if n and (n in _norm(r["name"]) or n in _norm(r["exe"]))]
    if not hits:
        raise ValueError(f"no game matches {game!r}; call list_games")
    return hits[0]


def _save_files(r: dict) -> list[Path]:
    files = []
    pfx = COMPAT / r["appid"] / "pfx" / "drive_c" / "users" / "steamuser"
    for root in ("AppData/LocalLow", "AppData/Roaming", "AppData/Local", "Saved Games", "Documents"):
        base = pfx / root
        if base.is_dir():
            for f in base.rglob("*"):
                s = str(f)
                if f.is_file() and BACKUP_TAG not in s and ".bak_" not in s and not SKIP_DIR.search(s + "/" if f.is_dir() else s):
                    if SAVE_EXT.search(s) and not SKIP_DIR.search(s):
                        files.append(f)
    gd = _game_dir(r["exe"])
    if gd.is_dir():
        for f in gd.rglob("*"):
            s = str(f)
            if not f.is_file() or BACKUP_TAG in s:
                continue
            low = s.lower()
            if re.search(r"/(www/)?save[^/]*/", low) or re.search(r"\.(rpgsave|rmmzsave)$", low) or re.search(r"/save[^/]*\.(sav|dat)$", low):
                files.append(f)
    reg = pfx.parent.parent.parent / "user.reg"
    if reg.exists():
        files.append(reg)
    return sorted(set(files))


# ---------------------------------------------------------------- formats

_KEYB64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="


def lz_decompress_b64(s: str) -> str:
    s = s.strip()
    if not s:
        return ""
    vals = [_KEYB64.index(c) for c in s]
    return _lz_decompress(len(vals), 32, lambda i: vals[i])


def _lz_decompress(length, reset, getval):
    dictionary = {0: 0, 1: 1, 2: 2}
    enlarge, dict_size, num_bits = 4, 4, 3
    result = []
    data_val, data_pos, data_idx = getval(0), reset, 1

    def bits(n):
        nonlocal data_val, data_pos, data_idx
        out, power = 0, 1
        for _ in range(n):
            resb = data_val & data_pos
            data_pos >>= 1
            if data_pos == 0:
                data_pos = reset
                data_val = getval(data_idx) if data_idx < length else 0
                data_idx += 1
            if resb:
                out |= power
            power <<= 1
        return out

    c = bits(2)
    if c == 0:
        c = chr(bits(8))
    elif c == 1:
        c = chr(bits(16))
    else:
        return ""
    dictionary[3] = c
    w = c
    result.append(c)
    while True:
        if data_idx > length:
            return ""
        c = bits(num_bits)
        if c == 0:
            dictionary[dict_size] = chr(bits(8))
            dict_size += 1
            c = dict_size - 1
            enlarge -= 1
        elif c == 1:
            dictionary[dict_size] = chr(bits(16))
            dict_size += 1
            c = dict_size - 1
            enlarge -= 1
        elif c == 2:
            return "".join(result)
        if enlarge == 0:
            enlarge = 1 << num_bits
            num_bits += 1
        if c in dictionary:
            entry = dictionary[c]
        elif c == dict_size:
            entry = w + w[0]
        else:
            return ""
        result.append(entry)
        dictionary[dict_size] = w + entry[0]
        dict_size += 1
        enlarge -= 1
        w = entry
        if enlarge == 0:
            enlarge = 1 << num_bits
            num_bits += 1


def lz_compress_b64(s: str) -> str:
    out = _lz_compress(s, 6, lambda a: _KEYB64[a])
    return out + "=" * ((4 - len(out) % 4) % 4)


def _lz_compress(uncompressed, bits_per_char, getchar):
    if uncompressed is None:
        return ""
    dictionary, to_create = {}, set()
    w, enlarge, dict_size, num_bits = "", 2, 3, 2
    data, data_val, data_pos = [], 0, 0

    def write(value, n):
        nonlocal data_val, data_pos
        for _ in range(n):
            data_val = (data_val << 1) | (value & 1)
            if data_pos == bits_per_char - 1:
                data_pos = 0
                data.append(getchar(data_val))
                data_val = 0
            else:
                data_pos += 1
            value >>= 1

    def emit_w():
        nonlocal enlarge, num_bits
        if w in to_create:
            if ord(w[0]) < 256:
                write(0, num_bits)
                write(ord(w[0]), 8)
            else:
                write(1, num_bits)
                write(ord(w[0]), 16)
            enlarge -= 1
            if enlarge == 0:
                enlarge = 1 << num_bits
                num_bits += 1
            to_create.discard(w)
        else:
            write(dictionary[w], num_bits)
        enlarge -= 1
        if enlarge == 0:
            enlarge = 1 << num_bits
            num_bits += 1

    for c in uncompressed:
        if c not in dictionary:
            dictionary[c] = dict_size
            dict_size += 1
            to_create.add(c)
        wc = w + c
        if wc in dictionary:
            w = wc
        else:
            emit_w()
            dictionary[wc] = dict_size
            dict_size += 1
            w = c
    if w != "":
        emit_w()
    write(2, num_bits)
    while True:
        data_val <<= 1
        if data_pos == bits_per_char - 1:
            data.append(getchar(data_val))
            break
        data_pos += 1
    return "".join(data)


def decode(path: Path) -> tuple[str, Any]:
    """Return (format, data). data is JSON-like for structured formats, str for text."""
    raw = path.read_bytes()
    name = path.name.lower()
    if name.endswith(".rpgsave"):
        return "rpgmv", json.loads(lz_decompress_b64(raw.decode("ascii")))
    if name.endswith(".rmmzsave"):
        try:
            return "rmmz", json.loads(zlib.decompress(raw).decode("utf-8"))
        except zlib.error:
            b = raw.decode("utf-8").encode("latin-1")
            return "rmmz-utf8", json.loads(zlib.decompress(b).decode("utf-8"))
    if name.endswith(".nson"):
        # Naninovel: raw deflate of UTF-8 JSON
        try:
            return "nson", _expand(json.loads(zlib.decompress(raw, -15).decode("utf-8-sig")))
        except (zlib.error, ValueError):
            pass
    if len(raw) >= 8 and struct.unpack_from("<I", raw)[0] <= len(raw) - 4:
        gd = godot_decode(raw)
        if gd:
            return f"godot{gd[0]}-var", gd[1]
    text = None
    encs = ("utf-16",) if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig",)
    for enc in encs:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is not None:
        t = text.strip()
        if t[:1] in "{[":
            try:
                return "json", _expand(json.loads(t))
            except json.JSONDecodeError:
                pass
        if re.fullmatch(r"[A-Za-z0-9+/=\s]{16,}", t):
            try:
                inner = base64.b64decode(t)
                return "json-b64", _expand(json.loads(inner.decode("utf-8")))
            except Exception:
                pass
        if "\0" not in t:
            return "text", text
    return "binary", raw


_LZ_RUNNER = """
const fs=require('fs'),vm=require('vm');const c={};vm.createContext(c);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';this.LZString=LZString;',c);
process.stdout.write(c.LZString.compressToBase64(fs.readFileSync(0,'utf8')));
"""


def _game_lzstring(save: Path) -> Path | None:
    # RPG Maker MV ships its own (often old 1.3.x) LZString; use it so the
    # output matches what the game itself writes.
    for d in [save.parent, *save.parents][:6]:
        for cand in (d / "js/libs/lz-string.js", d / "www/js/libs/lz-string.js"):
            if cand.exists():
                return cand
    return None


def encode(fmt: str, data: Any, original: bytes, path: Path | None = None) -> bytes:
    if fmt == "rpgmv":
        s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        lz = _game_lzstring(path) if path else None
        node = shutil.which("node") or "/opt/homebrew/bin/node"
        if lz and Path(node).exists():
            proc = subprocess.run([node, "-e", _LZ_RUNNER, str(lz)], input=s.encode("utf-8"), capture_output=True, timeout=120)
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout
        return lz_compress_b64(s).encode("ascii")
    if fmt in ("rmmz", "rmmz-utf8"):
        z = zlib.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 1)
        return z.decode("latin-1").encode("utf-8") if fmt == "rmmz-utf8" else z
    if fmt == "json":
        data = _collapse(data)
        utf16 = original[:2] in (b"\xff\xfe", b"\xfe\xff")
        t = original.decode("utf-16" if utf16 else "utf-8-sig", "replace")
        body = t.strip()
        m = re.search(r"\n([ \t]+)\S", body)
        indent = m.group(1) if m and "\n" in body else None
        ksep = " : " if '" : ' in body else ": " if '": ' in body else ":"
        isep = ", " if indent is None and re.search(r'[\]}"\d], "', body) else ","
        s = json.dumps(data, ensure_ascii=bool(re.search(r"\\u[0-9a-fA-F]{4}", body)) and not re.search(r"[^\x00-\x7f]", body),
                       indent=indent, separators=(isep, ksep))
        if "\r\n" in t:
            s = s.replace("\n", "\r\n")
        s = t[:len(t) - len(t.lstrip())] + s + t[len(t.rstrip()):]
        if utf16:
            return s.encode("utf-16")
        bom = b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b""
        return bom + s.encode("utf-8")
    if fmt == "json-b64":
        return base64.b64encode(_dumps_compact(_collapse(data)).encode("utf-8"))
    if fmt == "nson":
        inner = zlib.decompress(original, -15)
        bom = b"\xef\xbb\xbf" if inner.startswith(b"\xef\xbb\xbf") else b""
        c = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
        return c.compress(bom + _dumps_compact(_collapse(data)).encode("utf-8")) + c.flush()
    if fmt in ("godot3-var", "godot4-var"):
        return godot_encode(int(fmt[5]), data)
    if fmt == "text":
        return data.encode("utf-8")
    raise ValueError(f"cannot re-encode format {fmt}")


# ---------------------------------------------------------------- Godot store_var

_GD_TYPES = {
    3: ["Nil", "bool", "int", "float", "String", "Vector2", "Rect2", "Vector3", "Transform2D", "Plane", "Quat",
        "AABB", "Basis", "Transform", "Color", "NodePath", "RID", "Object", "Dictionary", "Array", "PoolByteArray",
        "PoolIntArray", "PoolRealArray", "PoolStringArray", "PoolVector2Array", "PoolVector3Array", "PoolColorArray"],
    4: ["Nil", "bool", "int", "float", "String", "Vector2", "Vector2i", "Rect2", "Rect2i", "Vector3", "Vector3i",
        "Transform2D", "Vector4", "Vector4i", "Plane", "Quaternion", "AABB", "Basis", "Transform3D", "Projection",
        "Color", "StringName", "NodePath", "RID", "Object", "Callable", "Signal", "Dictionary", "Array",
        "PackedByteArray", "PackedInt32Array", "PackedInt64Array", "PackedFloat32Array", "PackedFloat64Array",
        "PackedStringArray", "PackedVector2Array", "PackedVector3Array", "PackedColorArray", "PackedVector4Array"],
}
# fixed-size math types: (struct code, count); "f" becomes "d" in double-precision builds (flag 64)
_GD_MATH = {"Vector2": ("f", 2), "Vector2i": ("i", 2), "Rect2": ("f", 4), "Rect2i": ("i", 4), "Vector3": ("f", 3),
            "Vector3i": ("i", 3), "Transform2D": ("f", 6), "Vector4": ("f", 4), "Vector4i": ("i", 4),
            "Plane": ("f", 4), "Quat": ("f", 4), "Quaternion": ("f", 4), "AABB": ("f", 6), "Basis": ("f", 9),
            "Transform": ("f", 12), "Transform3D": ("f", 12), "Projection": ("f", 16), "Color": ("f", 4)}
_GD_PACKED = {"PoolIntArray": ("i", 1), "PoolRealArray": ("f", 1), "PackedInt32Array": ("i", 1),
              "PackedInt64Array": ("q", 1), "PackedFloat32Array": ("f", 1), "PackedFloat64Array": ("d", 1),
              "PoolVector2Array": ("f", 2), "PoolVector3Array": ("f", 3), "PoolColorArray": ("f", 4),
              "PackedVector2Array": ("f", 2), "PackedVector3Array": ("f", 3), "PackedColorArray": ("f", 4),
              "PackedVector4Array": ("f", 4)}
_F64 = 1 << 16


def _pad4(n: int) -> int:
    return (4 - n % 4) % 4


class _GodotVar:
    """Godot's binary Variant encoding (marshalls.cpp), as written by FileAccess.store_var.
    Non-JSON types become {"$type": name, ...} so their parts stay patchable."""

    def __init__(self, ver: int):
        self.ver = ver
        self.names = _GD_TYPES[ver]
        self.ids = {n: i for i, n in enumerate(self.names)}

    # decode
    def _u32(self, b, i):
        return struct.unpack_from("<I", b, i)[0], i + 4

    def _str(self, b, i):
        n, i = self._u32(b, i)
        if i + n > len(b):
            raise ValueError("string past end")
        return b[i:i + n].decode("utf-8"), i + n + _pad4(n)

    def _typeinfo(self, b, i, kind):
        if kind == 1:
            return self._u32(b, i)
        if kind in (2, 3):
            return self._str(b, i)
        return None, i

    def dec(self, b, i):
        h, i = self._u32(b, i)
        t, flags = h & 0xFFFF, h >> 16
        if t >= len(self.names):
            raise ValueError(f"godot{self.ver} type {t}")
        name = self.names[t]
        f64 = bool(h & _F64)
        if name == "Nil":
            return None, i
        if name == "bool":
            v, i = self._u32(b, i)
            return bool(v), i
        if name == "int":
            return (struct.unpack_from("<q", b, i)[0], i + 8) if f64 else (struct.unpack_from("<i", b, i)[0], i + 4)
        if name == "float":
            return (struct.unpack_from("<d", b, i)[0], i + 8) if f64 else (struct.unpack_from("<f", b, i)[0], i + 4)
        if name == "String":
            return self._str(b, i)
        if name == "StringName":
            s, i = self._str(b, i)
            return {"$type": name, "v": s}, i
        if name in _GD_MATH:
            code, n = _GD_MATH[name]
            dbl = code == "f" and f64 and name != "Color"
            code = "d" if dbl else code
            v = list(struct.unpack_from(f"<{n}{code}", b, i))
            out = {"$type": name, "v": v}
            if dbl:
                out["$double"] = True
            return out, i + n * struct.calcsize(code)
        if name == "NodePath":
            n, i = self._u32(b, i)
            if not n & 0x80000000:
                raise ValueError("old-format NodePath")
            sub, i = self._u32(b, i)
            fl, i = self._u32(b, i)
            parts = []
            for _ in range((n & 0x7FFFFFFF) + sub):
                s, i = self._str(b, i)
                parts.append(s)
            return {"$type": name, "names": parts[:n & 0x7FFFFFFF], "subnames": parts[n & 0x7FFFFFFF:], "flags": fl}, i
        if name == "RID":
            if self.ver == 3:
                return {"$type": name}, i
            return {"$type": name, "id": struct.unpack_from("<Q", b, i)[0]}, i + 8
        if name == "Object":
            if h & _F64:
                return {"$type": name, "id": struct.unpack_from("<Q", b, i)[0]}, i + 8
            cls, i = self._str(b, i)
            if not cls:
                return {"$type": name, "class": ""}, i
            n, i = self._u32(b, i)
            props = {}
            for _ in range(n):
                k, i = self._str(b, i)
                props[k], i = self.dec(b, i)
            return {"$type": name, "class": cls, "props": props}, i
        if name == "Dictionary":
            typed = None
            if self.ver == 4 and flags & 0xF:
                kt, i = self._typeinfo(b, i, flags & 3)
                vt, i = self._typeinfo(b, i, (flags >> 2) & 3)
                typed = [flags & 0xF, kt, vt]
            n, i = self._u32(b, i)
            d = {}
            for _ in range(n & 0x7FFFFFFF):
                k, i = self.dec(b, i)
                if not isinstance(k, (str, int, float, bool)) and k is not None:
                    raise ValueError("unsupported dictionary key type")
                d[k], i = self.dec(b, i)
            return ({"$type": name, "typed": typed, "v": d} if typed else d), i
        if name == "Array":
            typed = None
            if self.ver == 4 and flags & 3:
                ti, i = self._typeinfo(b, i, flags & 3)
                typed = [flags & 3, ti]
            n, i = self._u32(b, i)
            arr = []
            for _ in range(n & 0x7FFFFFFF):
                v, i = self.dec(b, i)
                arr.append(v)
            return ({"$type": name, "typed": typed, "v": arr} if typed else arr), i
        if name in ("PoolByteArray", "PackedByteArray"):
            n, i = self._u32(b, i)
            if i + n > len(b):
                raise ValueError("bytes past end")
            return {"$type": name, "hex": b[i:i + n].hex()}, i + n + _pad4(n)
        if name in ("PoolStringArray", "PackedStringArray"):
            n, i = self._u32(b, i)
            out = []
            for _ in range(n):
                ln, i = self._u32(b, i)
                out.append(b[i:i + ln].split(b"\0", 1)[0].decode("utf-8"))
                i += ln + _pad4(ln)
            return {"$type": name, "v": out}, i
        if name in _GD_PACKED:
            code, per = _GD_PACKED[name]
            dbl = code == "f" and f64 and "Color" not in name
            code = "d" if dbl else code
            n, i = self._u32(b, i)
            flat = list(struct.unpack_from(f"<{n * per}{code}", b, i))
            v = flat if per == 1 else [flat[k:k + per] for k in range(0, len(flat), per)]
            out = {"$type": name, "v": v}
            if dbl:
                out["$double"] = True
            return out, i + n * per * struct.calcsize(code)
        raise ValueError(f"godot type {name} not supported")

    # encode
    def _hdr(self, name, flags=0):
        return struct.pack("<I", self.ids[name] | flags)

    def _s(self, s):
        e = s.encode("utf-8")
        return struct.pack("<I", len(e)) + e + b"\0" * _pad4(len(e))

    def _tinfo(self, kind, info):
        if kind == 1:
            return struct.pack("<I", info)
        if kind in (2, 3):
            return self._s(info)
        return b""

    def enc(self, v) -> bytes:
        if v is None:
            return self._hdr("Nil")
        if isinstance(v, bool):
            return self._hdr("bool") + struct.pack("<I", int(v))
        if isinstance(v, int):
            if -0x80000000 <= v <= 0x7FFFFFFF:
                return self._hdr("int") + struct.pack("<i", v)
            return self._hdr("int", _F64) + struct.pack("<q", v)
        if isinstance(v, float):
            if struct.unpack("<f", struct.pack("<f", v))[0] == v or v != v:
                return self._hdr("float") + struct.pack("<f", v)
            return self._hdr("float", _F64) + struct.pack("<d", v)
        if isinstance(v, str):
            return self._hdr("String") + self._s(v)
        if isinstance(v, list):
            return self._hdr("Array") + struct.pack("<I", len(v)) + b"".join(self.enc(x) for x in v)
        if isinstance(v, dict) and "$type" not in v:
            return self._hdr("Dictionary") + struct.pack("<I", len(v)) + b"".join(self.enc(k) + self.enc(x) for k, x in v.items())
        name = v["$type"]
        if name == "StringName":
            return self._hdr(name) + self._s(v["v"])
        if name in _GD_MATH:
            code, n = _GD_MATH[name]
            dbl = bool(v.get("$double"))
            return self._hdr(name, _F64 if dbl else 0) + struct.pack(f"<{n}{'d' if dbl else code}", *v["v"])
        if name == "NodePath":
            out = self._hdr(name) + struct.pack("<III", len(v["names"]) | 0x80000000, len(v["subnames"]), v["flags"])
            return out + b"".join(self._s(x) for x in v["names"] + v["subnames"])
        if name == "RID":
            return self._hdr(name) + (struct.pack("<Q", v["id"]) if self.ver == 4 else b"")
        if name == "Object":
            if "id" in v:
                return self._hdr(name, _F64) + struct.pack("<Q", v["id"])
            if not v["class"]:
                return self._hdr(name) + self._s("")
            props = v["props"]
            return (self._hdr(name) + self._s(v["class"]) + struct.pack("<I", len(props))
                    + b"".join(self._s(k) + self.enc(x) for k, x in props.items()))
        if name == "Dictionary":
            fl, kt, vt = v["typed"]
            body = b"".join(self.enc(k) + self.enc(x) for k, x in v["v"].items())
            return (self._hdr(name, fl << 16) + self._tinfo(fl & 3, kt) + self._tinfo((fl >> 2) & 3, vt)
                    + struct.pack("<I", len(v["v"])) + body)
        if name == "Array":
            fl, ti = v["typed"]
            return (self._hdr(name, fl << 16) + self._tinfo(fl, ti) + struct.pack("<I", len(v["v"]))
                    + b"".join(self.enc(x) for x in v["v"]))
        if name in ("PoolByteArray", "PackedByteArray"):
            data = bytes.fromhex(v["hex"])
            return self._hdr(name) + struct.pack("<I", len(data)) + data + b"\0" * _pad4(len(data))
        if name in ("PoolStringArray", "PackedStringArray"):
            out = self._hdr(name) + struct.pack("<I", len(v["v"]))
            for s in v["v"]:
                e = s.encode("utf-8") + b"\0"
                out += struct.pack("<I", len(e)) + e + b"\0" * _pad4(len(e))
            return out
        if name in _GD_PACKED:
            code, per = _GD_PACKED[name]
            dbl = bool(v.get("$double"))
            code = "d" if dbl else code
            flat = v["v"] if per == 1 else [x for item in v["v"] for x in item]
            return self._hdr(name, _F64 if dbl else 0) + struct.pack("<I", len(v["v"])) + struct.pack(f"<{len(flat)}{code}", *flat)
        raise ValueError(f"cannot encode godot type {name}")


def godot_decode(raw: bytes):
    """Return (version, data) for a file of length-prefixed store_var values, or None."""
    found = []
    for ver in (3, 4):
        gv, vals, i = _GodotVar(ver), [], 0
        try:
            while i < len(raw):
                n = struct.unpack_from("<I", raw, i)[0]
                seg = raw[i + 4:i + 4 + n]
                if n == 0 or len(seg) != n:
                    raise ValueError("bad length")
                v, j = gv.dec(seg, 0)
                if j != n:
                    raise ValueError("trailing bytes")
                vals.append(v)
                i += 4 + n
        except (ValueError, struct.error, UnicodeDecodeError, IndexError):
            continue
        if vals:
            found.append((ver, vals[0] if len(vals) == 1 else {"$vars": vals}))
    if not found:
        return None
    # both layouts can parse tiny files; prefer the one that yields a container
    found.sort(key=lambda f: not isinstance(f[1], (dict, list)))
    return found[0]


def godot_encode(ver: int, data) -> bytes:
    gv = _GodotVar(ver)
    vals = data["$vars"] if isinstance(data, dict) and set(data) == {"$vars"} else [data]
    out = b""
    for v in vals:
        e = gv.enc(v)
        out += struct.pack("<I", len(e)) + e
    return out


# ---------------------------------------------------------------- nested JSON strings

def _dumps_compact(x) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def _expand(node):
    """Turn strings holding compact JSON (Unity JsonUtility, Naninovel) into {"$json": ...}
    so their contents are patchable. Only when re-serializing gives back the exact string."""
    if isinstance(node, dict):
        return {k: _expand(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand(v) for v in node]
    if isinstance(node, str) and len(node) > 1 and node[0] in "{[" and node[-1] in "}]":
        try:
            inner = json.loads(node)
        except ValueError:
            return node
        if isinstance(inner, (dict, list)) and _dumps_compact(inner) == node:
            return {"$json": _expand(inner)}
    return node


def _collapse(node):
    if isinstance(node, dict):
        if set(node) == {"$json"}:
            return _dumps_compact(_collapse(node["$json"]))
        return {k: _collapse(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_collapse(v) for v in node]
    return node


# ---------------------------------------------------------------- Unity PlayerPrefs (Wine user.reg)

_PP_ENTRY = re.compile(r'^("(?:[^"\\]|\\.)*")=(.*)$')


def _reg_unescape(s: str) -> str:
    return re.sub(r'\\x([0-9a-fA-F]{1,4})|\\(.)', lambda m: chr(int(m.group(1), 16)) if m.group(1) else m.group(2), s)


def _reg_escape(s: str) -> str:
    return "".join("\\\\" if c == "\\" else '\\"' if c == '"' else c if 32 <= ord(c) < 127 else f"\\x{ord(c):04x}" for c in s)


def _unity_hash(name: str) -> int:
    h = 5381
    for c in name:
        h = ((h * 33) ^ ord(c)) & 0xFFFFFFFF
    return h


def _pp_entries(lines: list[str]):
    """Yield (section, key, line_from, line_to, prefix, value_text) for Unity PlayerPrefs values
    (registry names ending in _h<hash>)."""
    sec, i = None, 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("["):
            sec = _reg_unescape(line[1:line.rindex("]")])
        j = i
        while lines[j].endswith("\\") and j + 1 < len(lines):
            j += 1
        m = _PP_ENTRY.match(line)
        if m and sec:
            hm = re.fullmatch(r"(.*)_h(\d+)", _reg_unescape(m.group(1)[1:-1]), re.S)
            if hm:
                value = m.group(2).rstrip("\\") + "".join(l.strip().rstrip("\\") for l in lines[i + 1:j + 1])
                yield sec, hm.group(1), i, j, m.group(1) + "=", value
        i = j + 1


def _pp_decode(v: str):
    if v.startswith("dword:"):
        x = int(v[6:], 16)
        return "int", x - (1 << 32) if x >= 1 << 31 else x
    m = re.fullmatch(r"hex(?:\((\w+)\))?:([0-9a-fA-F,]*)", v)
    if m:
        b = bytes.fromhex(m.group(2).replace(",", ""))
        if m.group(1) == "4" and len(b) == 8:
            return "float", struct.unpack("<d", b)[0]
        if m.group(1) is None and b.endswith(b"\0"):
            try:
                return "string", b[:-1].decode("utf-8")
            except UnicodeDecodeError:
                pass
    return "raw", v


def _pp_encode(prefix: str, kind: str, value) -> list[str]:
    """Registry lines for one value, wrapped exactly like wineserver's dump_value."""
    if kind == "int":
        return [f"{prefix}dword:{value & 0xFFFFFFFF:08x}"]
    head, data = ("hex(4):", struct.pack("<d", value)) if kind == "float" else ("hex:", value.encode("utf-8") + b"\0")
    out, count = prefix + head, len(prefix) + len(head)
    for n, byte in enumerate(data):
        out += f"{byte:02x}"
        count += 2
        if n < len(data) - 1:
            out += ","
            count += 1
            if count > 76:
                out += "\\\n  "
                count = 2
    return out.split("\n")


def _non_pp_lines(lines: list[str]) -> list[str]:
    skip = set()
    for _s, _k, a, b, _p, _v in _pp_entries(lines):
        skip.update(range(a, b + 1))
    return [l for n, l in enumerate(lines) if n not in skip]


def _wine_running() -> bool:
    return subprocess.run(["pgrep", "-f", "wineserver"], capture_output=True).returncode == 0


def _pp_read(reg: Path) -> list[tuple]:
    lines = reg.read_text(encoding="utf-8", errors="surrogateescape").split("\n")
    return [(sec, key, *_pp_decode(val)) for sec, key, *_rest, val in _pp_entries(lines)]


def _pp_write(reg: Path, edits: list[dict], create: bool) -> str:
    if _wine_running():
        raise RuntimeError("Wine is running; quit the game first (wineserver rewrites user.reg on exit and would drop this edit)")
    text = reg.read_text(encoding="utf-8", errors="surrogateescape")
    lines = text.split("\n")
    entries = list(_pp_entries(lines))
    sections = sorted({e[0] for e in entries})
    replace, add, report = {}, {}, []
    for e in edits:
        key, value, want_sec = e["key"], e["value"], e.get("section")
        hits = [x for x in entries if x[1] == key and (not want_sec or x[0] == want_sec)]
        if len(hits) > 1:
            raise ValueError(f"{key!r} is in several sections {[h[0] for h in hits]}; pass section")
        if isinstance(value, bool):
            value = int(value)
        if hits:
            sec, _k, a, b, prefix, old_text = hits[0]
            kind, old = _pp_decode(old_text)
            if kind == "raw":
                raise ValueError(f"{key}: unsupported registry value {old_text[:40]}")
            new = _coerce(old, value, key)
            replace[a] = (b, _pp_encode(prefix, kind, new))
            report.append(f"{sec}: {key} = {old!r} -> {new!r}")
        else:
            if not create:
                raise ValueError(f"{key!r} not found; read_playerprefs lists keys (create=true adds a new one)")
            sec = want_sec or (sections[0] if len(sections) == 1 else None)
            if not sec:
                raise ValueError(f"pass section for new key {key!r}; sections: {sections}")
            value = _coerce(None, value, key)
            if isinstance(value, bool):
                value = int(value)
            if not isinstance(value, (int, float, str)):
                raise ValueError(f"{key}: value must be a number or string")
            kind = "float" if isinstance(value, float) else "int" if isinstance(value, int) else "string"
            prefix = '"' + _reg_escape(f"{key}_h{_unity_hash(key)}") + '"='
            add.setdefault(sec, []).extend(_pp_encode(prefix, kind, value))
            report.append(f"{sec}: {key} = (new) {value!r}")
    out, i = [], 0
    while i < len(lines):
        if i in replace:
            b, new_lines = replace[i]
            out.extend(new_lines)
            i = b + 1
            continue
        line = lines[i]
        out.append(line)
        i += 1
        if line.startswith("[") and _reg_unescape(line[1:line.rindex("]")]) in add:
            while i < len(lines) and lines[i].startswith("#"):  # #time=/#class= stay first
                out.append(lines[i])
                i += 1
            out.extend(add.pop(_reg_unescape(line[1:line.rindex("]")])))
    if add:
        raise ValueError(f"section not found: {list(add)}")
    bak = _backup(reg)
    reg.write_text("\n".join(out), encoding="utf-8", errors="surrogateescape")
    # verify: every edited key reads back, nothing else in the file changed
    after = {(s, k): (t, v) for s, k, t, v in _pp_read(reg)}
    before = {(s, k): (t, v) for s, k, t, v in _pp_read(bak)}
    for e in edits:
        hit = [v for (s, k), v in after.items() if k == e["key"] and (not e.get("section") or s == e["section"])]
        if len(hit) != 1:
            shutil.copy2(bak, reg)
            return f"verification failed for {e['key']}; original restored"
    edited = {e["key"] for e in edits}
    untouched_before = {k: v for k, v in before.items() if k[1] not in edited}
    untouched_after = {k: v for k, v in after.items() if k[1] not in edited}
    if untouched_before != untouched_after or _non_pp_lines(lines) != _non_pp_lines(reg.read_text(encoding="utf-8", errors="surrogateescape").split("\n")):
        shutil.copy2(bak, reg)
        return "verification failed (other values changed); original restored"
    return f"wrote {reg}, backup {bak.name}, verified\n" + "\n".join(report)


# ---------------------------------------------------------------- Ren'Py scripts (.rpa / .rpyc)

_SAFE_BUILTINS = {"set", "frozenset", "object", "list", "dict", "tuple", "str", "bytes", "bytearray",
                  "int", "float", "bool", "complex", "slice", "unicode", "long", "basestring"}


class _Stub:
    def __init__(self, *args, **kw):
        self._args = args

    def __setstate__(self, state):
        self._state = state


class _StubUnpickler(pickle.Unpickler):
    """Loads Ren'Py pickles into inert stand-in classes; no game or library code runs."""
    _made: dict = {}

    def find_class(self, module, name):
        if module in ("builtins", "__builtin__") and name in _SAFE_BUILTINS:
            return {"unicode": str, "long": int, "basestring": str}.get(name) or getattr(__import__("builtins"), name)
        if module in ("copy_reg", "copyreg") and name == "_reconstructor":
            return lambda cls, base, state: cls.__new__(cls)
        if module == "collections" and name in ("OrderedDict", "defaultdict"):
            return lambda *a: {}
        key = (module, name)
        if key not in self._made:
            low = name.lower()
            base = dict if "dict" in low else list if "list" in low else set if "set" in low else str if name == "PyExpr" else _Stub
            ns = {"__module__": module}
            if base is not _Stub:
                ns["__setstate__"] = lambda self, st: setattr(self, "_state", st)
                if base is str:
                    ns["__new__"] = lambda cls, s="", *a: str.__new__(cls, s)
            self._made[key] = type(name, (base,) if base is _Stub else (base,), ns)
        return self._made[key]


def _strings(obj, out, seen):
    if id(obj) in seen:
        return
    seen.add(id(obj))
    if isinstance(obj, str):
        if obj.strip():
            out.append(obj)
        return
    if isinstance(obj, bytes):
        return
    if isinstance(obj, dict):
        items = list(obj.keys()) + list(obj.values())
    elif isinstance(obj, (list, tuple, set, frozenset)):
        items = list(obj)
    else:
        items = []
    items += [v for k, v in getattr(obj, "__dict__", {}).items()]
    for v in items:
        _strings(v, out, seen)


def _rpyc_text(data: bytes) -> str:
    if data.startswith(b"RENPY RPC2"):
        pos, blob = 10, None
        while True:
            slot, start, length = struct.unpack_from("<III", data, pos)
            pos += 12
            if slot == 0:
                break
            if slot == 1:
                blob = data[start:start + length]
        if blob is None:
            return ""
    else:
        blob = data
    obj = _StubUnpickler(io.BytesIO(zlib.decompress(blob)), encoding="utf-8", errors="replace").load()
    out: list[str] = []
    _strings(obj, out, set())
    # drop consecutive duplicates (PyExpr and its filename repeat a lot)
    return "\n".join(s for i, s in enumerate(out) if i == 0 or s != out[i - 1])


def _rpa_index(path: Path) -> dict:
    with open(path, "rb") as f:
        head = f.readline()
        parts = head.split()
        if parts[0] == b"RPA-3.0":
            off, key = int(parts[1], 16), int(parts[2], 16)
        elif parts[0] == b"RPA-2.0":
            off, key = int(parts[1], 16), 0
        else:
            raise ValueError(f"unknown archive {parts[0][:10]!r}")
        f.seek(off)
        idx = _StubUnpickler(io.BytesIO(zlib.decompress(f.read())), encoding="bytes").load()
    out = {}
    for name, entries in idx.items():
        e = entries[0]
        name = name.decode("utf-8", "replace") if isinstance(name, bytes) else name
        prefix = e[2] if len(e) > 2 else b""
        out[name] = (e[0] ^ key, e[1] ^ key, prefix.encode("latin-1") if isinstance(prefix, str) else prefix)
    return out


def _renpy_scripts(gd: Path) -> list[tuple[str, str]]:
    """(name, text) for every Ren'Py script: .rpy source, loose .rpyc, and .rpyc inside .rpa archives."""
    game = next((p for p in [gd / "game", *gd.glob("*/game")] if p.is_dir()), None)
    if not game:
        return []
    CACHE.mkdir(parents=True, exist_ok=True)
    out = []
    for f in sorted(game.rglob("*")):
        suf = f.suffix.lower()
        if suf not in (".rpy", ".rpyc", ".rpa") or not f.is_file():
            continue
        if suf == ".rpyc" and f.with_suffix(".rpy").exists():
            continue
        st = f.stat()
        cache = CACHE / ("renpy_" + hashlib.sha256(f"{f}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16] + ".json")
        if cache.exists():
            out.extend(json.loads(cache.read_text()))
            continue
        items = []
        try:
            if suf == ".rpy":
                items.append([str(f.relative_to(game)), f.read_text(encoding="utf-8", errors="replace")])
            elif suf == ".rpyc":
                items.append([str(f.relative_to(game)), _rpyc_text(f.read_bytes())])
            else:
                with open(f, "rb") as fh:
                    for name, (off, ln, prefix) in _rpa_index(f).items():
                        if name.endswith((".rpyc", ".rpy", ".rpym", ".rpymc")):
                            fh.seek(off)
                            data = prefix + fh.read(ln - len(prefix))
                            text = data.decode("utf-8", "replace") if name.endswith((".rpy", ".rpym")) else _rpyc_text(data)
                            items.append([f"{f.name}/{name}", text])
        except Exception as e:  # one unreadable script shouldn't hide the rest
            items.append([str(f.relative_to(game)), f"<unreadable: {type(e).__name__}: {e}>"])
        cache.write_text(json.dumps(items))
        out.extend(items)
    return out


_RENPY_UNLOCK = "zz_odysseus_unlock.rpy"
_DOTTED = re.compile(r"(persistent|store)(\.[A-Za-z_*][\w*]*)+$")
_IDENT = re.compile(r"[A-Za-z_]\w*$")


def _py_literal(v) -> str:
    v = _coerce(None, v, "value")
    if isinstance(v, str):
        return json.dumps(v)  # a valid literal in Python 2 and 3
    if v is None or isinstance(v, (bool, int, float)):
        return repr(v)
    raise ValueError(f"values must be plain numbers, strings, true/false or null, got {v!r}")


def _renpy_unlock_source(mark_all_seen: bool, sets: list, adds: list, calls: list) -> str:
    """Ren'Py drop-in that unlocks content from inside the game. Only fixed operations on
    persistent/store names; no free-form code."""
    acts = []
    for s in sets:
        if not _DOTTED.match(s["target"]):
            raise ValueError(f"set target must look like persistent.name or persistent.prefix_*.field: {s['target']!r}")
        acts.append(f"_ody_do('set {s['target']}', _ody_set, {json.dumps(s['target'])}, {_py_literal(s['value'])})")
    for s in adds:
        if not _DOTTED.match(s["target"]) or "*" in s["target"]:
            raise ValueError(f"add target must be persistent.name or store.name: {s['target']!r}")
        vals = ", ".join(_py_literal(v) for v in s["values"])
        acts.append(f"_ody_do('add {s['target']}', _ody_add, {json.dumps(s['target'])}, [{vals}])")
    for c in calls:
        if not (_IDENT.match(c["call"]) and _IDENT.match(c["over"])):
            raise ValueError("call and over must be plain names defined by the game")
        item = c.get("item")
        if item is not None and not isinstance(item, int):
            raise ValueError("item must be an integer index or omitted")
        acts.append(f"_ody_do('call {c['call']} over {c['over']}', _ody_call, {json.dumps(c['call'])}, {json.dumps(c['over'])}, {item!r})")
    body = "\n".join("    " + a for a in acts) or "    pass"
    seen = "True" if mark_all_seen else "False"
    return f'''# Added by Odysseus game_saves (renpy_unlock). Delete this file and its .rpyc to stop it.
# What it already wrote to persistent data stays; the persistent files were backed up first.
init 1990 python:
    import fnmatch as _ody_fn
    _odysseus_report = {{"done": [], "errors": []}}

    def _ody_do(what, fn, *args):
        try:
            _odysseus_report["done"].append([what, fn(*args)])
        except Exception as e:
            _odysseus_report["errors"].append([what, repr(e)])

    def _ody_objs(path):
        parts = path.split(".")
        objs = [persistent if parts[0] == "persistent" else store]
        for p in parts[1:-1]:
            nxt = []
            for o in objs:
                names = [n for n in list(vars(o)) if _ody_fn.fnmatchcase(n, p)] if "*" in p else [p]
                nxt += [getattr(o, n) for n in names if getattr(o, n, None) is not None]
            objs = nxt
        return objs, parts[-1]

    def _ody_set(path, value):
        objs, last = _ody_objs(path)
        n = 0
        for o in objs:
            for k in ([k for k in list(vars(o)) if _ody_fn.fnmatchcase(k, last)] if "*" in last else [last]):
                setattr(o, k, value)
                n += 1
        return n

    def _ody_add(path, values):
        objs, last = _ody_objs(path)
        coll = getattr(objs[0], last)
        for v in values:
            if isinstance(coll, dict):
                coll[v] = True
            elif hasattr(coll, "add"):
                coll.add(v)
            elif v not in coll:
                coll.append(v)
        return len(values)

    def _ody_call(fn, over, item):
        f = getattr(store, fn)
        seq = list(getattr(store, over))
        for x in seq:
            f(x if item is None else x[item])
        return len(seq)

    def _ody_seen():
        labels = [l for l in renpy.get_all_labels() if isinstance(l, basestring if str is bytes else str)]
        for l in labels:
            persistent._seen_ever[l] = True
        images = renpy.list_images()
        for i in images:
            persistent._seen_images[tuple(i.split())] = True
        return [len(labels), len(images)]

    if {seen}:
        _ody_do("mark all labels and images seen", _ody_seen)
{body}
    try:
        renpy.save_persistent()
    except Exception as e:
        _odysseus_report["errors"].append(["save_persistent", repr(e)])
'''


def _renpy_game_dir(r: dict) -> Path:
    gd = _game_dir(r["exe"])
    game = next((p for p in [gd / "game", *gd.glob("*/game")] if p.is_dir()), None)
    if not game:
        raise ValueError(f"{r['name']} is not a Ren'Py game (no game/ folder)")
    return game


# ---------------------------------------------------------------- paths

def _walk(node, prefix="", hint=""):
    """Yield (path, leaf value, hint). hint names a value inside a parallel
    {"keys": [...], "values": [...]} map, which Unity and Naninovel use for dictionaries."""
    if isinstance(node, dict):
        keys = node.get("keys")
        paired = isinstance(keys, list) and isinstance(node.get("values"), list) and len(keys) == len(node["values"])
        for k, v in node.items():
            sub = f"{prefix}.{k}" if prefix else str(k)
            if paired and k == "values":
                for i, item in enumerate(v):
                    yield from _walk(item, f"{sub}[{i}]", f"key={keys[i]}" if not isinstance(keys[i], (dict, list)) else hint)
            else:
                yield from _walk(v, sub, hint)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{prefix}[{i}]", hint)
    else:
        yield prefix, node, hint


_TOK = re.compile(r"\[(\d+|\*)\]|\.?([^.\[\]]+)")


def _tokens(path: str) -> list:
    toks = []
    for m in _TOK.finditer(path):
        if m.group(1) is not None:
            toks.append("*" if m.group(1) == "*" else int(m.group(1)))
        else:
            toks.append(m.group(2))
    return toks


def _coerce(old, value, where):
    """Keep the save's original value type; models sometimes send "9", {"$numberLong": "9"},
    {"__int__": "9"} or {"type": "number", "value": 9}."""
    if isinstance(value, dict):
        if "value" in value and not isinstance(value["value"], (dict, list)):
            value = value["value"]
        elif len(value) == 1 and not isinstance(next(iter(value.values())), (dict, list)):
            value = next(iter(value.values()))
    if old is None:
        return value
    if isinstance(old, bool):
        if isinstance(value, bool):
            return value
        if value in (0, 1, "true", "false", "True", "False"):
            return value in (1, "true", "True")
    elif isinstance(old, (int, float)):
        if isinstance(value, bool):
            raise ValueError(f"{where}: number expected, got boolean")
        if isinstance(value, str):
            try:
                value = float(value) if re.search(r"[.eE]", value) else int(value)
            except ValueError:
                raise ValueError(f"{where}: number expected, got {value!r}")
        if isinstance(value, (int, float)):
            if isinstance(old, float):
                return float(value)
            return int(value) if float(value).is_integer() else value
    elif isinstance(old, str):
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return str(value)
    elif type(old) is type(value):
        return value
    raise ValueError(f"{where}: keeps type {type(old).__name__}, refused {json.dumps(value)[:80]}")


def _set(node, toks, value, changed, trail=""):
    if not toks:
        return
    t, rest = toks[0], toks[1:]
    if t == "*":
        keys = range(len(node)) if isinstance(node, list) else list(node.keys())
        for k in keys:
            child = node[k]
            if rest:
                if isinstance(child, (dict, list)):
                    _set(child, rest, value, changed, f"{trail}[{k}]")
            elif isinstance(child, (int, float, bool)) or child is None:
                old = node[k]
                node[k] = _coerce(old, value, f"{trail}[{k}]")
                changed.append((f"{trail}[{k}]", old, node[k]))
        return
    if isinstance(node, list):
        t = int(t)
    elif isinstance(node, dict) and t not in node and str(t).isdigit() and int(t) in node:
        t = int(t)
    if rest:
        _set(node[t], rest, value, changed, f"{trail}.{t}")
    else:
        old = node.get(t) if isinstance(node, dict) else node[t]
        node[t] = _coerce(old, value, f"{trail}.{t}")
        changed.append((f"{trail}.{t}", old, node[t]))


def _backup(path: Path) -> Path:
    b = path.with_name(path.name + BACKUP_TAG + time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(path, b)
    return b


def _clip(s: str) -> str:
    return s if len(s) <= MAX_OUT else s[:MAX_OUT] + f"\n...[{len(s) - MAX_OUT} more chars cut; narrow the query]"


# ---------------------------------------------------------------- REA

def _rea_fields(dll: Path) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(dll.read_bytes()).hexdigest()[:16]
    out = CACHE / f"{digest}.fields.tsv"
    if out.exists():
        return out
    proc = subprocess.run(
        [DOCKER, "run", "--rm", "-v", f"{dll.parent}:/m:ro", "--entrypoint", "rea", REA_IMAGE,
         "inspect-managed-members", f"/m/{dll.name}", "--format", "json"],
        capture_output=True, timeout=900,
    )
    data = json.loads(proc.stdout)
    n = data.get("normalized_result") or {}
    if not n.get("fields"):
        raise RuntimeError("REA returned no fields: " + "; ".join(n.get("limitations", []) or [proc.stderr.decode()[-300:]]))
    lines = []
    for f in n["fields"]:
        sig = f.get("signature") or {}
        lines.append(f"F\t{f.get('declaring_type')}\t{f.get('name')}\t{sig.get('field_type')}")
    for m in n.get("methods", []):
        lines.append(f"M\t{m.get('declaring_type')}\t{m.get('name')}\t")
    out.write_text("\n".join(lines))
    return out


# ---------------------------------------------------------------- tools

TOOLS = [
    Tool(name="list_games", description="List installed games (appid, name, engine, number of save files). Optional name filter.",
         inputSchema={"type": "object", "properties": {"filter": {"type": "string"}}}),
    Tool(name="list_save_files", description="List a game's save files (Wine prefix AppData, in-game save folders, and user.reg for Unity PlayerPrefs) with detected format.",
         inputSchema={"type": "object", "properties": {"game": {"type": "string", "description": "appid or part of the name"}}, "required": ["game"]}),
    Tool(name="read_save", description="Decode a save (RPG Maker MV/MZ, JSON, base64 JSON, text) and list leaf values as path = value. Use 'query' (regex on path) to narrow, e.g. 'gold|money|coin'.",
         inputSchema={"type": "object", "properties": {"path": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}),
    Tool(name="patch_save", description="Set values in a save and re-encode it. edits: [{\"path\": \"party._gold\", \"value\": 99999999}]. '*' matches every array item/object key, e.g. 'party._items.*'. Backs up first and verifies.",
         inputSchema={"type": "object", "properties": {"path": {"type": "string"}, "edits": {"type": "array", "items": {"type": "object", "properties": {"path": {"type": "string"}, "value": {"type": ["number", "string", "boolean"], "description": "plain JSON value, e.g. 99999999 or true; never an object"}}, "required": ["path", "value"]}}}, "required": ["path", "edits"]}),
    Tool(name="read_playerprefs", description="Unity games: list PlayerPrefs stored in the game's Wine registry (user.reg) as section: key = value (int|float|string). Optional regex query on key names.",
         inputSchema={"type": "object", "properties": {"game": {"type": "string"}, "query": {"type": "string"}}, "required": ["game"]}),
    Tool(name="set_playerprefs", description="Unity games: set PlayerPrefs values in user.reg. Keeps each key's type. create=true adds keys that do not exist yet. Refuses while Wine is running. Backs up and verifies.",
         inputSchema={"type": "object", "properties": {"game": {"type": "string"}, "edits": {"type": "array", "items": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": ["number", "string", "boolean"], "description": "plain value, e.g. 1 or 99999"}, "section": {"type": "string"}}, "required": ["key", "value"]}}, "create": {"type": "boolean"}}, "required": ["game", "edits"]}),
    Tool(name="renpy_unlock", description="Ren'Py games: install game/zz_odysseus_unlock.rpy, which unlocks content from inside the game at startup. mark_all_seen marks every label and image seen (unlocks standard galleries/replays). sets: [{target: 'persistent.sc1' or 'persistent.scene_for_replay_*.unlocked', value}], adds: [{target: 'persistent.unlocked_replays', values: [...]}], calls: [{call: 'unlock_replay', over: 'replays_by_order', item: 0}] calls a game function for each entry of a game list. Find names with search_game_files first. Backs up persistent files. remove=true deletes the file.",
         inputSchema={"type": "object", "properties": {
             "game": {"type": "string"}, "mark_all_seen": {"type": "boolean"}, "remove": {"type": "boolean"},
             "sets": {"type": "array", "items": {"type": "object", "properties": {"target": {"type": "string"}, "value": {"type": ["number", "string", "boolean"]}}, "required": ["target", "value"]}},
             "adds": {"type": "array", "items": {"type": "object", "properties": {"target": {"type": "string"}, "values": {"type": "array", "items": {"type": ["number", "string"]}}}, "required": ["target", "values"]}},
             "calls": {"type": "array", "items": {"type": "object", "properties": {"call": {"type": "string"}, "over": {"type": "string"}, "item": {"type": "integer"}}, "required": ["call", "over"]}}},
             "required": ["game"]}),
    Tool(name="replace_in_text_save", description="Regex replace in a text save (ini/cfg/tres/text). Backs up first. Returns changed lines.",
         inputSchema={"type": "object", "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}, "replacement": {"type": "string"}}, "required": ["path", "pattern", "replacement"]}),
    Tool(name="restore_save", description="Restore a save from its newest Odysseus backup.",
         inputSchema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}),
    Tool(name="rea_find_fields", description="Unity Mono games: use REA to list C# fields/methods whose type or name matches a regex (e.g. 'gold|money|unlock|gallery'). Shows Type.field : fieldType.",
         inputSchema={"type": "object", "properties": {"game": {"type": "string"}, "pattern": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["game", "pattern"]}),
    Tool(name="search_game_files", description="Regex search a game's script/data text files (js, json, rpy, gd, cs, txt, ini) and return matching lines with file names. Ren'Py games: also searches compiled .rpyc scripts, including those inside .rpa archives.",
         inputSchema={"type": "object", "properties": {"game": {"type": "string"}, "pattern": {"type": "string"}, "glob": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["game", "pattern"]}),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


def _save_path(s: str, read_only: bool = False) -> Path:
    p = Path(s).expanduser()
    if not p.is_absolute():
        raise ValueError(f"{s!r} is relative; pass the full path exactly as list_save_files printed it")
    if not p.is_file():
        raise FileNotFoundError(f"{p} does not exist; copy the path from list_save_files")
    if p.name == "user.reg" and not read_only:
        raise ValueError("user.reg holds Unity PlayerPrefs; use read_playerprefs / set_playerprefs")
    return p


def _run(name: str, a: dict) -> str:
    if name == "list_games":
        flt = (a.get("filter") or "").lower()
        lines = []
        for r in _read_shortcuts():
            if flt and flt not in r["name"].lower() and flt not in r["exe"].lower():
                continue
            gd = _game_dir(r["exe"])
            lines.append(f"{r['appid']}\t{r['name']}\t{_engine(gd) if gd.is_dir() else 'missing'}\t{len(_save_files(r))} files")
        return "\n".join(lines) or "no games"

    if name == "list_save_files":
        r = _find_game(a["game"])
        out = [f"{r['name']} (appid {r['appid']}) game dir: {_game_dir(r['exe'])}"]
        for f in _save_files(r):
            try:
                fmt = f"registry: {len(_pp_read(f))} Unity PlayerPrefs (use read_playerprefs)" if f.name == "user.reg" else decode(f)[0]
            except Exception as e:
                fmt = f"undecodable ({type(e).__name__})"
            out.append(f"{f}\t{f.stat().st_size} B\t{fmt}")
        return "\n".join(out)

    if name == "read_save":
        p = _save_path(a["path"], read_only=True)
        fmt, data = decode(p)
        q = re.compile(a["query"], re.I) if a.get("query") else None
        limit = int(a.get("limit") or 200)
        if fmt == "binary":
            strings = re.findall(rb"[\x20-\x7e]{5,}", data)[:limit]
            return f"format=binary size={len(data)}; printable strings:\n" + "\n".join(s.decode() for s in strings if not q or q.search(s.decode()))
        if fmt == "text":
            lines = [l for l in data.splitlines() if not q or q.search(l)]
            return _clip(f"format=text\n" + "\n".join(lines[:limit]))
        rows = [(k, v, h) for k, v, h in _walk(data) if not q or q.search(k) or (h and q.search(h))]
        body = "\n".join(f"{k} = {json.dumps(v, ensure_ascii=False)[:120]}" + (f"   # {h}" if h else "") for k, v, h in rows[:limit])
        return _clip(f"format={fmt} matches={len(rows)} (showing {min(limit, len(rows))})\n{body}")

    if name == "patch_save":
        p = _save_path(a["path"])
        original = p.read_bytes()
        fmt, data = decode(p)
        if fmt in ("binary", "text"):
            return f"format={fmt}: use replace_in_text_save for text; binary needs a game-specific editor"
        changed = []
        for e in a["edits"]:
            _set(data, _tokens(e["path"]), e["value"], changed)
        if not changed:
            return "no values matched; nothing written"
        new = encode(fmt, data, original, p)
        bak = _backup(p)
        p.write_bytes(new)
        fmt2, data2 = decode(p)
        if fmt2 != fmt or data2 != data:
            shutil.copy2(bak, p)
            return "verification failed; original restored"
        lines = [f"{k}: {json.dumps(o)} -> {json.dumps(n)}" for k, o, n in changed[:60]]
        more = f"\n...and {len(changed) - 60} more" if len(changed) > 60 else ""
        return f"wrote {p} ({fmt}), backup {bak.name}, verified\n" + "\n".join(lines) + more

    if name in ("read_playerprefs", "set_playerprefs"):
        r = _find_game(a["game"])
        reg = COMPAT / r["appid"] / "pfx" / "user.reg"
        if not reg.exists():
            return f"no Wine registry for {r['name']} (appid {r['appid']}); run the game once"
        if name == "set_playerprefs":
            return _pp_write(reg, a["edits"], bool(a.get("create")))
        q = re.compile(a["query"], re.I) if a.get("query") else None
        rows = [f"{sec}: {key} = {json.dumps(v, ensure_ascii=False)[:120]} ({kind})"
                for sec, key, kind, v in _pp_read(reg) if not q or q.search(key)]
        return _clip(f"{r['name']} {reg} ({len(rows)} keys)\n" + "\n".join(rows)) if rows else "no PlayerPrefs keys match"

    if name == "renpy_unlock":
        r = _find_game(a["game"])
        game = _renpy_game_dir(r)
        target = game / _RENPY_UNLOCK
        if a.get("remove"):
            removed = [str(f.name) for f in (target, target.with_suffix(".rpyc")) if f.exists()]
            for f in (target, target.with_suffix(".rpyc")):
                f.unlink(missing_ok=True)
            return f"removed {removed or 'nothing'} from {game}"
        src = _renpy_unlock_source(a.get("mark_all_seen", True), a.get("sets") or [], a.get("adds") or [], a.get("calls") or [])
        baks = [_backup(f).name for f in _save_files(r) if f.name == "persistent"]
        if target.exists():
            _backup(target)
        target.write_text(src, encoding="utf-8")
        target.with_suffix(".rpyc").unlink(missing_ok=True)
        return (f"wrote {target}; it runs the next time the game starts. persistent backups: {baks or 'none found'}\n"
                + "\n".join(l for l in src.splitlines() if l.startswith("    _ody_do(") or l.startswith("        _ody_do(")))

    if name == "replace_in_text_save":
        p = _save_path(a["path"])
        text = p.read_text(encoding="utf-8")
        new, n = re.subn(a["pattern"], a["replacement"], text, flags=re.M)
        if n == 0:
            return "pattern not found; nothing written"
        bak = _backup(p)
        p.write_text(new, encoding="utf-8")
        changed = [l for l in new.splitlines() if re.search(a["pattern"], l) or l not in text][:40]
        return f"{n} replacements, backup {bak.name}\n" + "\n".join(changed)

    if name == "restore_save":
        p = _save_path(a["path"])
        baks = sorted(p.parent.glob(p.name + BACKUP_TAG + "*"))
        if not baks:
            return "no Odysseus backup found"
        shutil.copy2(baks[-1], p)
        return f"restored {p} from {baks[-1].name}"

    if name == "rea_find_fields":
        r = _find_game(a["game"])
        dlls = list(_game_dir(r["exe"]).rglob("*_Data/Managed/Assembly-CSharp.dll"))
        if not dlls:
            return "no Assembly-CSharp.dll (not a Unity Mono game; IL2CPP games need il2cpp metadata tools)"
        tsv = _rea_fields(dlls[0])
        q = re.compile(a["pattern"], re.I)
        limit = int(a.get("limit") or 120)
        hits = []
        for line in tsv.read_text().splitlines():
            kind, typ, fname, ftype = (line.split("\t") + ["", "", "", ""])[:4]
            if q.search(typ) or q.search(fname):
                hits.append(f"{kind} {typ}.{fname}" + (f" : {ftype}" if ftype else ""))
        return _clip(f"REA {dlls[0].name}: {len(hits)} matches\n" + "\n".join(hits[:limit]))

    if name == "search_game_files":
        r = _find_game(a["game"])
        gd = _game_dir(r["exe"])
        q = re.compile(a["pattern"], re.I)
        limit = int(a.get("limit") or 80)
        pat = a.get("glob") or "*"
        exts = {".js", ".json", ".rpy", ".gd", ".cs", ".txt", ".ini", ".cfg", ".tscn", ".tres", ".csv", ".xml"}
        hits = []
        for f in gd.rglob(pat):
            if not f.is_file() or f.suffix.lower() not in exts or f.stat().st_size > 20_000_000:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if q.search(line):
                    hits.append(f"{f.relative_to(gd)}:{i}: {line.strip()[:200]}")
                    if len(hits) >= limit:
                        return _clip("\n".join(hits))
        if _engine(gd) == "renpy" and not a.get("glob"):
            for sname, text in _renpy_scripts(gd):
                if not sname.endswith(".rpyc") and not sname.endswith(".rpymc"):
                    continue
                for line in text.splitlines():
                    if q.search(line):
                        hits.append(f"{sname}: {line.strip()[:200]}")
                        if len(hits) >= limit:
                            return _clip("\n".join(hits))
        return _clip("\n".join(hits) or "no matches")

    raise ValueError(f"unknown tool {name}")


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        text = await asyncio.to_thread(_run, name, arguments or {})
    except Exception as e:
        text = f"error: {type(e).__name__}: {e}"
    return [TextContent(type="text", text=text)]


async def main():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
