"""static/js/autoRoute.js under Node: ask the server, switch through the picker, never block a send.

autoRoute.js and localModels.js are the real files; the picker, toasts and `fetch` are stubs.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_JS = Path(__file__).resolve().parent.parent / "static" / "js"
_HAS_NODE = shutil.which("node") is not None
pytestmark = pytest.mark.skipif(not _HAS_NODE, reason="needs node")

_REWRITES = {
    "from './ui.js'": "from './ui.mjs'",
    "from './modelPicker.js'": "from './modelPicker.mjs'",
    "from './localModels.js'": "from './localModels.mjs'",
    "from './modelSort.js'": "from './modelSort.mjs'",
}

_DRIVER = r"""
import { fileURLToPath } from 'node:url';
const store = new Map();
globalThis.localStorage = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
globalThis.window = { location: { origin: 'http://odysseus.test' } };
const state = globalThis.__state = { toasts: [], switched: [], fetches: [], reply: null, models: [], switchFails: false, shown: [], attached: [] };
globalThis.document = { querySelectorAll: () => state.shown.map(src => ({ getAttribute: () => src })) };
const { autoRouteBeforeSend, autoRouteAfterTurn } = await import('./autoRoute.mjs');
globalThis.fetch = async (url, opts) => {
  if (String(url).includes('/api/generated-image/')) return { ok: true, blob: async () => new Blob(['png'], { type: 'image/png' }) };
  state.fetches.push({ url, body: JSON.parse(opts.body) });
  if (state.reply instanceof Error) throw state.reply;
  return state.reply;
};
const m = (mid, extra = {}) => ({ mid, display: mid, endpointId: 'e1', url: 'http://127.0.0.1:12434/engines/v1', ...extra });
const TEXT = [m('qwen3-8b'), m('qwen3.6-35b')];
const IMAGE = [m('stable-diffusion:latest')];
const ok = (verdict) => ({ ok: true, json: async () => verdict });
const attach = async (file) => { state.attached.push({ name: file.name, type: file.type }); };
const ask = (over = {}) => autoRouteBeforeSend({ message: 'draw a cat', currentModel: 'qwen3-8b', mode: 'chat', planMode: false, approvedPlan: false, hasImage: false, attach, attachedNames: [], ...over });
const results = {};
const reset = (reply, models = [TEXT, IMAGE]) => { Object.assign(state, { toasts: [], switched: [], fetches: [], reply, models, switchFails: false, shown: [], attached: [] }); };

reset(ok({ switch: true, model: 'stable-diffusion:latest', endpoint_id: 'e1', reason: 'Picture request: switching to the image model.' }));
results.switch = { verdict: await ask({ hasImage: true, planMode: true }), switched: state.switched, toasts: state.toasts, body: state.fetches[0].body, url: state.fetches[0].url };

reset(ok({ switch: false }));
results.keep = { verdict: await ask(), switched: state.switched, toasts: state.toasts };

reset(new Error('network down'));
results.offline = { verdict: await ask(), switched: state.switched };

reset({ ok: false, status: 500, json: async () => ({}) });
results.serverError = { verdict: await ask(), switched: state.switched };

reset(ok({ switch: true, model: 'gone-model', endpoint_id: '', reason: 'x' }));
results.unknownTarget = { verdict: await ask(), switched: state.switched };

reset(ok({ switch: true, model: 'qwen3-8b', endpoint_id: 'e1', reason: 'Back to a text model after the picture.' }));
state.switchFails = true;
results.switchFails = { verdict: await ask({ currentModel: 'stable-diffusion:latest' }), toasts: state.toasts };

reset(ok({ switch: false }), [[m('qwen3-8b')], []]);
results.oneModel = { verdict: await ask(), fetches: state.fetches.length };

// The text model is remembered when leaving it for a picture, and offered back on the next message.
reset(ok({ switch: true, model: 'stable-diffusion:latest', endpoint_id: 'e1', reason: 'img' }));
await ask({ currentModel: 'qwen3.6-35b' });
reset(ok({ switch: false }));
await ask({ currentModel: 'stable-diffusion:latest', message: 'hello' });
results.remembered = { previous_text: state.fetches[0].body.previous_text };

// A chat that already made a picture: asking about it hands the picture over and does not switch the model.
reset(ok({ switch: false, attach_last_image: true, intent: 'about_image' }));
state.shown = ['/api/generated-image/abc123.png', '/api/generated-image/newest.png?x=1'];
results.about = { verdict: await ask({ message: 'what is in this image?' }), attached: state.attached, switched: state.switched, last_image: state.fetches[0].body.last_image };

reset(ok({ switch: false, attach_last_image: true, intent: 'about_image' }));
state.shown = ['/api/generated-image/newest.png'];
await ask({ message: 'describe it', attachedNames: ['newest.png'] });
results.notTwice = { attached: state.attached };

reset(ok({ switch: false }));
await ask({ message: 'what is in this image?' });
results.noPicture = { attached: state.attached, last_image: state.fetches[0].body.last_image };

reset(ok({ switch: true, model: 'stable-diffusion:latest', endpoint_id: 'e1', reason: 'Picture request: switching to the image model.', attach_last_image: true }));
state.shown = ['/api/generated-image/abc123.png'];
results.edit = { verdict: await ask({ message: 'make it darker' }), attached: state.attached, switched: state.switched };

// Once a picture is done we leave the image model for the text model we came from.
reset(ok({ switch: true, model: 'stable-diffusion:latest', endpoint_id: 'e1', reason: 'img' }));
await ask({ currentModel: 'qwen3.6-35b' });
state.switched.length = 0; state.toasts.length = 0;
await autoRouteAfterTurn();
results.backAfterPicture = { switched: [...state.switched], toasts: [...state.toasts] };
state.switched.length = 0;
await autoRouteAfterTurn();
results.backOnlyOnce = { switched: state.switched };

// Asked about twice in one chat: attached once (the answer is in the history); another chat attaches it again.
reset(ok({ switch: false, attach_last_image: true, intent: 'about_image' }));
state.shown = ['/api/generated-image/zzz.png'];
await ask({ message: 'what is in this image?', chatId: 'c1' });
await ask({ message: 'what colour is the sky in it?', chatId: 'c1' });
const inChat1 = state.attached.length;
await ask({ message: 'what is in this image?', chatId: 'c2' });
results.attachOnce = { inChat1, afterOtherChat: state.attached.length };

store.set('odysseus-auto-route', '0');
reset(ok({ switch: true, model: 'stable-diffusion:latest', endpoint_id: 'e1', reason: 'x' }));
results.off = { verdict: await ask(), fetches: state.fetches.length, switched: state.switched };

console.log(JSON.stringify(results));
"""

_PICKER_STUB = """
export const listChatModels = () => globalThis.__state.models[0];
export const listImageModels = () => globalThis.__state.models[1];
export const switchToModel = async (m) => {
  if (globalThis.__state.switchFails) throw new Error('PATCH failed');
  globalThis.__state.switched.push(m.mid);
  window.__odysseusLastPickedRoute = { model: m.mid };   // what the real picker records
};
"""


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    work = tmp_path_factory.mktemp("autoroute")
    source = (_JS / "autoRoute.js").read_text(encoding="utf-8")
    for old, new in _REWRITES.items():
        assert old in source, f"autoRoute.js no longer imports {old}"
        source = source.replace(old, new)
    (work / "autoRoute.mjs").write_text(source, encoding="utf-8")
    (work / "ui.mjs").write_text("export default { showToast(msg) { globalThis.__state.toasts.push(msg); } };\n", encoding="utf-8")
    (work / "modelPicker.mjs").write_text(_PICKER_STUB, encoding="utf-8")
    shutil.copy(_JS / "localModels.js", work / "localModels.mjs")
    shutil.copy(_JS / "modelSort.js", work / "modelSort.mjs")
    (work / "driver.mjs").write_text(_DRIVER, encoding="utf-8")
    proc = subprocess.run(["node", "driver.mjs"], cwd=work, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_switch_verdict_switches_through_the_picker_and_says_why(results):
    r = results["switch"]
    assert r["switched"] == ["stable-diffusion:latest"]
    assert r["toasts"] == ["Auto: Picture request: switching to the image model."]
    assert r["verdict"]["switch"] is True


def test_the_server_is_told_everything_it_needs_to_choose(results):
    r = results["switch"]
    assert r["url"] == "http://odysseus.test/api/local-models/route"
    body = r["body"]
    assert body["message"] == "draw a cat" and body["current"] == "qwen3-8b" and body["has_image"] is True
    assert body["plan_mode"] is True and body["mode"] == "chat"
    assert [c["model"] for c in body["candidates"]] == ["qwen3-8b", "qwen3.6-35b", "stable-diffusion:latest"]


def test_nothing_happens_when_the_current_model_fits(results):
    assert results["keep"] == {"verdict": None, "switched": [], "toasts": []}


def test_routing_never_blocks_a_send(results):
    for case in ("offline", "serverError", "unknownTarget"):
        assert results[case]["verdict"] is None and results[case]["switched"] == [], case
    assert results["switchFails"] == {"verdict": None, "toasts": []}


def test_the_text_model_is_remembered_for_the_way_back_from_a_picture(results):
    assert results["remembered"]["previous_text"] == "qwen3.6-35b"


def test_it_can_be_turned_off_and_needs_a_choice_to_make(results):
    assert results["off"] == {"verdict": None, "fetches": 0, "switched": []}
    assert results["oneModel"] == {"verdict": None, "fetches": 0}


def test_a_question_about_the_picture_attaches_it_and_does_not_switch(results):
    r = results["about"]
    assert r["switched"] == [] and r["last_image"] is True and r["verdict"]["attach_last_image"] is True
    assert r["attached"] == [{"name": "newest.png", "type": "image/png"}]  # the newest picture on screen


def test_the_picture_is_not_attached_twice_and_not_invented(results):
    assert results["notTwice"]["attached"] == []
    assert results["noPicture"] == {"attached": [], "last_image": False}


def test_changing_the_picture_switches_to_the_image_model_with_the_picture_attached(results):
    r = results["edit"]
    assert r["switched"] == ["stable-diffusion:latest"] and r["attached"] == [{"name": "abc123.png", "type": "image/png"}]


def test_after_a_picture_the_chat_goes_back_to_its_text_model_once(results):
    assert results["backAfterPicture"]["switched"] == ["qwen3.6-35b"]
    assert results["backAfterPicture"]["toasts"] == ["Auto: back to qwen3.6-35b."]
    assert results["backOnlyOnce"]["switched"] == []


def test_a_picture_is_attached_once_per_chat_so_follow_ups_are_fast(results):
    assert results["attachOnce"] == {"inChat1": 1, "afterOtherChat": 2}
