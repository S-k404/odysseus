"""Dump printable strings from the non-media objects of a Unity data file/bundle (read-only).
usage: unity_strings.py <path> <out.txt>"""
import re, sys, UnityPy
SKIP = {"Texture2D", "AudioClip", "Mesh", "Sprite", "Shader", "AnimationClip", "VideoClip", "Font", "Cubemap",
        "Texture3D", "Texture2DArray", "SpriteAtlas", "ComputeShader", "AnimatorController", "NavMeshData", "TerrainData"}
runs = re.compile(rb"[\x21-\x7e]{4,48}")
env = UnityPy.load(sys.argv[1])
out, n, seen = open(sys.argv[2], "w", encoding="utf-8"), 0, set()
for obj in env.objects:
    if obj.type.name in SKIP:
        continue
    try:
        data = obj.get_raw_data()
    except Exception:
        continue
    n += 1
    for m in runs.finditer(data):
        s = m.group().decode("ascii")
        if s not in seen:
            seen.add(s); out.write(s + "\n")
print(f"{n} objects, {len(seen)} distinct strings -> {sys.argv[2]}")
