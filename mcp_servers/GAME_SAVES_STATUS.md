# Game saves via Odysseus: status and plans

Last updated: 2026-11-03 13:45

## Goal

Use REA inside Odysseus to give game saves max currency or unlock hidden content, for the games in
`~/Documents/Virtual Win11 Drive/Games` (Bridgeplay / Steam non-Steam shortcuts). Use only local
models for the AI work. Claude builds and checks the tools; the local model makes every save edit.

## How it works

- **Local model:** Docker Model Runner at `http://127.0.0.1:12434/v1`, model
  `huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S` (131k context, about 99 tok/s, native
  tool calls). The Anthropic endpoint in Odysseus stays disabled.
- **MCP server `game_saves`:** `mcp_servers/game_save_server.py`, registered in `data/app.db` as
  "Game Saves (REA-backed)". It has 12 small tools, about 5 KB of schema (`add_list_items` appends unlocked ids to a list).
  - Every write makes a `<file>.bak_odysseus_<YYYYmmdd_HHMMSS>` backup, re-decodes the written
    file, and puts the original back if the check fails.
  - `restore_save` brings back the newest backup.
- **MCP server `rea`:** image `mcp/rea:games`, which is REA with the .NET metadata limit raised
  from 64 MB to 1 GB (`game_saves_dev/rea-games.Dockerfile`). Games and saves are mounted read-only,
  and only 7 of its 170 tools are on. `rea_find_fields` calls it for Unity Mono C# fields.
- **Odysseus.app:** serves on 127.0.0.1:7860. The log shows
  `Game Saves (REA-backed) (game_saves) - 12 tools via stdio` (13:40:44).

### Formats the server reads and writes

| Format | Games | Round-trip test on every save on disk |
|---|---|---|
| RPG Maker MV `.rpgsave` (encoded with the game's own `lz-string.js`) | Dungeon with Girl, Harem, Meltys, Daily Lives … | 44/44 byte-identical |
| RPG Maker MZ `.rmmzsave` (zlib, UTF-8 string form) | Exposed Livestream, Stalking the Sisters | 12/12 byte-identical |
| JSON, base64 JSON, nested JSON strings (`$json` in paths) | REC, Full Service, MDRG, Spooky Milk Life, Third Crisis, Barely Working, Living with My Little Sister, Sleeping Sister … | 26 byte-identical, 16 same data with typed check (whitespace and float digits only) |
| Naninovel `.nson` (raw deflate JSON); `read_save` labels parallel keys/values maps with `# key=…` | Adelaide Remake, Chubby Story | 13/13 byte-identical |
| Godot 3/4 `store_var` binary Variant | ACM, Lovecraft Locker 1 and 2 | 6/6 byte-identical |
| Unity PlayerPrefs in Wine `user.reg` (`read_playerprefs` / `set_playerprefs`) | 17 Unity prefixes (Tangled, Roxanne, Framed, …) | 420/420 entries: key hash and Wine line wrapping match exactly; Wine's own `reg query` read edits back in a scratch prefix |
| Ren'Py: `renpy_unlock` drop-in `game/zz_odysseus_unlock.rpy`; `search_game_files` reads `.rpyc` and `.rpa` | AnotherChance, Knightly Passions, Norikascases2, PokeSluts | Checked in each game's own Linux engine (Docker, APFS clone), see below |

### Ren'Py checks (on clones, real game folders untouched)

`game_saves_dev/renpy_verify.py` runs the game's Linux build headless in the
`odysseus-renpy-test` image and asks the game itself what is unlocked:

- **AnotherChance (Ren'Py 7.4.4):** `calls unlock_replay over replays_by_order item 0`. 154/154
  replays unlocked, 3867/3867 labels and 13564/13564 images seen, persistent rewritten.
- **Knightly Passions (7.6.3):** `set persistent.scene_for_replay_*.unlocked = true`. 49/49
  replays unlocked, 1376 labels and 2059 images seen.
- **Norikascases2 (8.3.2):** `mark_all_seen`. 268/268 labels and 3811/3811 images. Its `sc1`–`sc39`
  gallery flags were already true.
- **PokeSluts (8.3.7):** `mark_all_seen`. 363/363 labels and 2827/2827 images.

## Done: saves changed by the local model, checked independently

Each file was checked with the game's own decoder (`verify_mv.js` uses the game's `lz-string.js`,
`verify_mz.js` uses its `pako`), comparing it with its backup. Gold is the only change in every file.

| Game | Files | Gold |
|---|---|---|
| Dungeon with Girl | `www/save/file1`, `file2` | 738910 / 785910 → 99999999 |
| Harem in Another World | `www/save/file1`, `file20` | 763199 → 99999999 |
| Meltys's Quest | `www/save/file1`–`file7` | → 9999999999999 (the game's YEP Gold Max) |
| Daily Lives of My Countryside | `www/save/file1`–`file9` (not root `save/` or `3 save/`) | ~89.6M → 99999999 |
| Exposed Livestream | `save/file0`–`file3` | 0 → 99999999 |
| Stalking the Sisters | `save/file1` | 1000 → 99999999 |

Tangled by Tentacles was fully unlocked in an earlier session (`user.reg.bak_endgame`).

### Second round (13:30 to 13:42): all made by the local model, then checked independently

| Game | What changed | Independent check |
|---|---|---|
| AnotherChance | `renpy_unlock`: mark_all_seen + `unlock_replay` over `replays_by_order` | Installed file run in the game's own engine on a clone: 154/154 replays, 3867 labels, 13564 images |
| Knightly Passions, **both** installs | `renpy_unlock`: mark_all_seen + `persistent.scene_for_replay_*.unlocked = true` | Both run in 7.6.3: 49/49 replays, 1376 labels, 2059 images |
| PokeSluts, Norikascases2 | `renpy_unlock`: mark_all_seen | 363 labels / 2827 images and 268 labels / 3811 images, `sc*` flags all true |
| Adelaide Remake | 10 `g_*` scene flags `"0"` to `"1"` in `GlobalSave.nson` (11 of 11 now `"1"`) | Raw-deflate decode of file vs backup: only those 10 values differ |
| Lovecraft Locker 1 | `currency` 0 to 999999, `game.skill_pts` 0 to 99 | Byte diff vs backup: same size, only the two int32 values differ |
| Lovecraft Locker 2 | `progress.currency` 30 to 999999, `progress.talent_pts` 0 to 99 | Same byte-diff check |
| ACM (Anomalous Coffee Machine) | `progress.game_data.game_info.coins` 0 to 999999 | Same byte-diff check |
| Third Crisis Neon Nights | `Currency_Default` to 999999 in Autosave, after_shower, full_save, newgame; `Currency` in Chapter 2 save | `json.loads` diff: one leaf per file |
| REC | `Credits` to 9999999 in `savegame0/1.save` | Same |
| My Dystopian Robot Girlfriend | `money` to 99999999 in `A1.mdrgslot`, `M1.mdrgslot` | Same |
| Living with My Little Sister | `money` to 9999999 in `savedata0.json` (save folder and `Save backup`), `savedata1.json` | Same |
| Full Service | `metadata.money` 1000 to 9999999 | Same. Not run in the game, so the game reading this field is assumed |
| Sleeping Sister | 8 ending ids added to `watchedEpisodeIds` in `commonsave.dat` (all 10 ids found in the game's `level2` data) | Other keys equal; list has all 10 |
| Barely Working | all 20 `level.*.*.complete` to true (best_time untouched) | 19 changed False to True, nothing else |

Pick a game by **appid** when two shortcuts match one name (`list_games` shows appids). A name like
`Knightly_passions-1.60-pc` matched the nested `..._2_DLC_PC/Knightly_passions-1.60-pc` install both
times; the top-level install (appid 3816299858) needed `game="3816299858"`.

## Checked and left alone

- **Spooky Milk Life:** `omake.sav` gallery is already all true; money is already 1,350,436 in all three saves.
- **Third Crisis `Gallery.sav`:** holds only scenes already seen (77, all true). There is no list of all scene ids to add.
- **Unity PlayerPrefs (all 16 other games):** surveyed with `read_playerprefs`; they hold only settings (volume,
  resolution, language), plus `Level2Completed` (SisterFriendsSleep), `Stars`/`FullInventory` (Framed) and
  `Profile_inventory=life:5` (ISEKAI QUEST). No money or gallery keys.
- **Full Service:** `pre_debug_money` left at 1000 (the game's own restore value for debug mode).

## Still open

1. **Unity Mono games that keep state in their own file format:** use `rea_find_fields` to find it.
2. **Full Service:** confirm in the game that the money shows 9,999,999 (Wine run).
3. **Encrypted and undecoded games** (next section).
4. Optional: raise Spooky Milk Life money above 1.35M (cap unknown).

## Unsupported or blocked

- **Lure of Passion:** Godot 4.4 pack with an encrypted directory (`GDEC` save, key compiled into
  the exe). Needs key extraction from the exe first.
- **Encrypted saves:** ISEKAI QUEST `0.sav`, LEWD GOD `play_N.json` (`enc` prefix), Peeping Dorm
  `*.dat` (base64 + cipher), Secret Flasher Manaka `*.sd`, Loser Maker `.es3` (AES; ES3's default
  password `password` fails). They need keys from IL2CPP metadata or code.
- **Not decoded yet:** Nemurimouto `sav` (XOR-like obfuscation), Imouto Life (Wolf RPG `.sav`).
- **Nothing to edit:** Sister Love (Unreal; settings saves only), PocketCampfire (no `savefile.sav`),
  AML, NightHigh 1–3, Space Misadventures DX, chikanif (no saves found).
- **Odysseus API token:** creating an `ody_` token was blocked as credential creation. To drive
  Odysseus agent mode over HTTP, create a chat-scoped token in Odysseus Settings. Until then, runs
  go through `local_agent.py` (same model, same MCP server) or the Odysseus chat UI.

## Lessons for the local model

- It once wrote `{"$numberLong": "99999999"}`, and later `{"__int__": …}` and
  `{"type": "number", "value": …}`. `_coerce` now unwraps these and keeps each value's original type.
  Schemas declare `value` as number/string/boolean.
- Relative paths are refused with a clear message; it must copy paths from `list_save_files`.
- Name matching ignores punctuation and `'s` ("Meltys Quest" finds "Meltys's Quest v1.2r").
- Keep tasks narrow: name the folder, the field path and the cap. Precise tasks finished in 2–5
  tool calls each.

## Files

- Server: `mcp_servers/game_save_server.py` (pre-feature copy in the session scratchpad only).
- Dev tools: `mcp_servers/game_saves_dev/`:
  - `local_agent.py`: local-model agent loop over the MCP server.
  - `verify_mv.js` / `verify_mz.js`: check saves with the game's own decoder.
  - `renpy_verify.py` and `renpy-img/Dockerfile`: headless Ren'Py check on an APFS clone. With
    `ODY_KEEP_INSTALLED=1` it tests the `zz_odysseus_unlock.rpy` already in the game folder.
  - `rea-games.Dockerfile`.
- Caches: `~/Library/Caches/odysseus-game-saves` (REA field lists, Ren'Py script text).
- Odysseus DB backup from the first setup: `data/app.db.bak_rea_<timestamp>`.

## Restart note

After editing `game_save_server.py`, restart Odysseus.app. A quick quit and reopen once failed with
`DataDirInUse` (two server copies racing); a second quit and reopen fixed it. Check the log for
`game_saves) - 12 tools`.

## Third round (3 Nov, 14:50): Easy Save 3 games

- **ES3 codec added to `game_save_server.py`** (`es3` format; backup of the old server is `game_save_server.py.pre-es3`).
  Easy Save AES = 16-byte IV + AES-128-CBC/PKCS7, key = PBKDF2-HMAC-SHA1(password, IV, 100). The server writes
  Easy Save's own JSON layout and keeps the IV. Round trip on all 73 files of the two games below: 73/73
  byte-identical. Restart Odysseus.app to load it there (`local_agent.py` starts a fresh server each run).
- **Passwords** (found with `game_saves_dev/es3_probe*.py`, which tries the game's IL2CPP string literals and the
  printable strings of its serialized data files against the save):
  ISEKAI QUEST = `projectHS`; Loser Maker = `qawssdHJ` (all 71 of its `.es3` files).
- **ISEKAI QUEST:** the local model set `playerGOLD` 18 → 99999 in `0.sav` (3 tool calls). Checked by a separate
  decrypt and diff: only that line changed. All existing `A_<character>_<n>` gallery flags were already true,
  and which absent ones exist is unknown, so none were added. `config` holds only settings.
- **Loser Maker:** every file decrypts, but nothing was changed. Progress is inventory lists (`itemId`, `itemNum`
  in `player`, `player_equip`, `player_accessory`, `MagicChestInventory`, 66 `Inventory_*`); `SaveFile.es3` is key
  bindings only. Needs the item table to know which id is currency before editing.
- **Third Crisis gallery (correction):** an earlier note in this session said the scene ids are not plain text. That
  search never ran (macOS has no `timeout`). They are plain text in `resources.assets`, but only as keys inside
  embedded sample save states, not as a master list, so the full gallery list still needs the game's Unity assets.
- **Secret Flasher Manaka:** `.sd` saves are 16-byte aligned (probably Easy Save), but 11,050 literals failed and the
  game's data is one compressed bundle (`data.unity3d`), so the password is inside it. Same blocker as the Third
  Crisis list: a Unity bundle reader (UnityPy in an isolated venv) is needed.
- **Peeping Dorm Manager:** its code has one ES3 mention and no Easy Save; `.dat` files are base64 text. Not tried.
- **Nemurimouto:** one save (`sav`, identical `sav.bak`), so a key cannot be found by comparing saves.

## Fourth round (3 Nov, 15:05): Unity bundles and Secret Flasher Manaka

- **UnityPy 1.25.4** is installed in its own venv, `~/Library/Caches/odysseus-game-saves/venv-unitypy` (not the
  Odysseus venv). Helpers in `game_saves_dev/`: `unity_strings.py` (printable strings of a data file or bundle),
  `bundle_find.py` (which bundle object holds a string), `tc_scenes.py`, `es3_probe3.py` (ES3 password from a
  candidate list). The REA image cannot read these IL2CPP games (no Ghidra/Hopper/IDA), so UnityPy did that job.
- **Secret Flasher Manaka:** password `unReRU821Drq83`, found among 101,722 strings from its `data.unity3d`. It
  decrypts `SaveData/s.sd`, `0.sd`, `1.sd`. The player saves hold `Dictionary<int,…>` written with bare integer keys
  (`{0:{…}}`, not JSON), so the server now has an `es3-text` format (decrypted text, re-encrypted on write; use
  `replace_in_text_save`). Round trip: 77/77 files byte-identical across the three Easy Save games.
- **Edit made by the local model:** `CurrentRp` (the game's currency) 110 → 9999999 in `0.sd` and 44253 → 9999999 in
  `1.sd`. Checked by a separate decrypt and diff: only that line changed in each. Ranks (`ReleasedInfoRank`,
  `ConfirmedReinforceRank`) were left alone because their caps are unknown. `SaveDataBackup/0.sd` is the game's own
  copy and was not changed. Note: on its first try the model wrote a literal `${1}9999999`; it noticed, called
  `restore_save`, and retried with `\g<1>`. Give it the exact pattern and replacement.
- **Third Crisis gallery: not done.** Scenes are separate dialogue assets in the `aa/*.bundle` files, and their
  first string is the scene name, but only 5 bundles hold assets of that kind and they cover 6 of the 18 ids in
  `Gallery.sav`. The others are stored another way, so a list built this way would be partial. `Gallery.sav` is
  unchanged.
- **Loser Maker:** still unedited; needs the item table to know which `itemId` is currency.
- **Still open:** Peeping Dorm Manager (`.dat` base64 + cipher, no Easy Save in its code), Lure of Passion (GDEC key in
  the exe), LEWD GOD (`enc` cipher; the game does not run on Mac yet), Nemurimouto, Imouto Life.

## Fifth round (3 Nov, 15:40): the open items

- **Loser Maker (done).** The item table is in `sharedassets2.assets` (97 items: 1xxx weapons, 2xxx consumables, 3xxx
  materials, 4xxx rings, 5xxx special items). There is no currency item; the economy is materials. The player owned
  every weapon. The local model filled 17 of the magic chest's 36 empty slots (`{"itemId": "None", "itemNum": 0}`)
  in `save/inventory/MagicChestInventory.es3` with the missing rings 4001, 4005 and special items 5000-5006 (x1) and
  consumables 2009, 2012, 2023-2025, 2027, 2028 plus material 3024 (x99). Checked by a separate decrypt: only those 17
  slots changed, all empty before; size and IV unchanged. Tested on a scratch copy first. Lesson: `list_save_files` is cut
  at 12,000 characters, so in a game with many saves the model cannot see all files; give it exact paths.
- **Lure of Passion (decrypted, nothing to unlock).** The pack is NOT encrypted (all 4469 entries have flag 0; the earlier
  note was wrong). Compiled `.gdc` scripts are `GDSC` + version + size + a zstd stream (Python 3.15 `compression.zstd`).
  `Scenes/GameState.gdc` holds the string `dR$8sF2!qL5vE#p9XzYt*d3mWbNcA7HjP`; Godot's `open_encrypted_with_pass` uses the
  32-character hex MD5 of the password as the AES-256 key (not SHA-256), and the header MD5 confirms it. The save is
  already maxed: gold 99,999, all 23 `opened_scenes` true, papers 10/10, sparks 9/9, element levels 3, inventory item 6 =
  999,999. `_security_flags` (cheat_valid, debug, signature) is the game's own tamper check, left as it is. No server codec
  for GDEC was added because nothing needs editing.
- **Nemurimouto (done).** `sav` is JSON XORed with the repeating key `word`, found among the string literals of its
  `Assembly-CSharp.dll`; the server has an `xor-json` format (byte-identical round trip on both copies). The local model
  set `money` 0 -> 999999 in both prefixes (3334441717 and 2325601988). Checked by a separate XOR and diff: one line.
  `sav.bak` (the game's own copy) was not changed.
- **Peeping Dorm Manager (still locked).** Saves are base64 of 16-aligned high-entropy data. Ruled out: 349k strings
  (metadata literals and printable strings of the data files) as key or password under raw / MD5 / SHA-256 / SHA-1 keys with
  IV from the file / zero IV / IV = key / ECB, and Easy Save PBKDF2, with text or gzip/zlib plaintext; all 16- and
  32-byte windows of `GameAssembly.dll` as a raw key (38M windows, CBC with any IV, and ECB); PBKDF2-SHA1 (1000
  iterations) with six salts including the common "Ivan Medvedev" sample salt. Next: read the `SaveSystem` methods
  (Il2CppDumper-style) or capture the key at run time. Two early "hits" were false positives (a 1-in-256 padding
  match): always require the whole file to decrypt to text or a valid gzip/zlib stream.
- **Third Crisis gallery:** unchanged (see the fourth round). **LEWD GOD** and **Imouto Life (Wolf RPG):** not attempted;
  LEWD GOD does not run on Mac yet, so editing its save is not useful.

## Sixth round (3 Nov, 20:50): Third Crisis gallery done, Peeping Dorm still locked

- **Third Crisis gallery (done: 27/27 scenes unlocked).** The game is Mono (not IL2CPP as noted earlier), so REA works on
  it: `rea_find_fields` (through the save server) gave the data model: `Gallery.Categories[].Scenes[]`, each `GalleryInfo`
  pointing at a dialogue asset (`Scene`, `ScenesToPlay`, `PreviewDialogue`) plus an embedded debug save. UnityPy found the
  Gallery object: `resources.assets` object `72008` (starts with `Gallery_Scenes`; 3.2 MB because each entry carries a
  72-120 KB debug save). Its typetree is unreadable even with the generator, so its 12-byte PPtrs were read from the raw
  bytes and resolved to dialogue objects (script PPtr (1,1736)); the result is 27 distinct dialogues, and all 18 ids
  already in `Gallery.sav` are among them (validation). List: `odysseus-game-saves/tools/third_crisis_gallery_scenes.json`.
  The local model added the 9 missing keys (variants such as `Room205 - 3 - SexScene2/3`, `Transit_SexScene_2_Yes 1/2`,
  `Transit_SexScene_3_Yes 1`, `Intro_NailSalon_1_Salon_5_Chair_2`, `0.3 - Nail Salon - Told Max - Porn - 1 - 2`,
  `Cypher_1_Intro_3_Zoey_ShowBoobs_HasPic`, `SlutService_3_Hideable_1_BoxMoved Rewrite 1`) as `true` in one `patch_save`
  call. Checked by a separate diff: 19 -> 28 keys, only those 9 added, none changed or removed, pinups unchanged.
  Server change: paths now accept `["key. with dots"]` (needed for `0.3 - ...`).
- **Tooling added to the UnityPy venv** (`~/Library/Caches/odysseus-game-saves/venv-unitypy`): `TypeTreeGeneratorAPI`
  0.0.10. With it `env.typetree_generator = TypeTreeGenerator(version); gen.load_local_game(game_root)` makes about 97% of
  a Mono game's MonoBehaviours readable (`resources.assets`: 26,064 of 27,610). It does not work for IL2CPP v29 (Peeping Dorm:
  "Error generating tree nodes").
- **Peeping Dorm Manager: key still not found.** More ruled out: a candidate list of 639k strings (all ASCII runs of the
  metadata incl. the default-value blob, strings with spaces, `GameAssembly.dll` ASCII and UTF-16 strings, data-file strings)
  under raw / MD5 / SHA-256 / SHA-1 / base64-decoded / hex-decoded keys with IV in file / zero / IV=key / ECB / any IV,
  Easy Save PBKDF2 and .NET Rfc2898 (1000 iterations, six salts); every aligned 16/32-byte window of `GameAssembly.dll` and
  of all 131 data files (CBC with IV in file for gzip/zlib plaintext, any IV and ECB for text). Logs: it uses Pixel Crushers'
  Save System with a JSON serializer wrapped by `LuXuan.SaveSystem.SaveSystem` (`Save_Game`, `RecordData_Game`,
  `ApplydData_Game(SavedData_Game, Boolean)`); a Mac session loaded and saved without errors, so the key is not
  machine-bound. The key is therefore built at run time (concatenation, hashing, or a product-name derivation). Next needs the
  code: Il2CppDumper (needs a .NET runtime) for names and constants, and a disassembler (Ghidra via REA, which needs JDK 21+;
  this Mac has Java 11). REA itself is current (6.8.0); it lacks an analysis engine, not an update.
- **REA setup facts:** the Odysseus image `mcp/rea:games` is Debian-based, so REA calls it "unsupported_host" and has no
  Ghidra/Hopper/IDA; `inspect-managed-members` (.NET) works, `analyze`/`decompile` on native code do not.

## Memory guard for the local model (3 Nov, 21:15)

- Odysseus refused to load `qwen3.6-35b-a3b` ("needs about 18 GB, only about 14 GB can be spared"). That guard only
  protects Odysseus itself: `local_agent.py` and `~/.local/bin/rea-local` call Docker Model Runner directly and had no check.
  Both now measure spare memory first (free + inactive + speculative pages minus 4 GiB, from `vm_stat`).
  `rea-local` falls back to the 8B model with a visible note when the 35B does not fit, and stops when even the 8B
  (about 7 GiB) does not. `local_agent.py` stops instead of falling back, because the smaller model is less reliable at
  editing saves. Overrides: `REA_LOCAL_RAM_GUARD=0` / `ODY_RAM_GUARD=0` (can freeze the Mac); `REA_LOCAL_SPARE_GIB` /
  `ODY_SPARE_GIB` simulate a value for tests.
- A test run of `local_agent.py` with no guard loaded the 35B model by accident (about 18 GB). Unload with
  `docker model unload --all`. A model unloads by itself about 5 minutes after its last use.
