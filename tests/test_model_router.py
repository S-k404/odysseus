"""Auto model choice: src/model_router.py + POST /api/local-models/route.

The cases are the ones that went wrong by hand: a chat left on the image model after a picture, and
a 1.5B coder asked to plan. No model is loaded; the RAM check is a stub.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.model_router import Candidate, classify, estimate_gb, is_simple_chat, route

BIG = Candidate("huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S", "dmr", "http://127.0.0.1:12434/engines/v1")
EIGHT = Candidate("huggingface.co/unsloth/qwen3-8b-gguf:Q4_K_M", "dmr", "http://127.0.0.1:12434/engines/v1")
TINY_CODER = Candidate("huggingface.co/unsloth/qwen2.5-coder-1.5b-instruct-gguf:Q4_K_M", "dmr", "http://127.0.0.1:12434/engines/v1")
VISION = Candidate("huggingface.co/qwen/qwen3-vl-30b-a3b-instruct-gguf:Q4_K_M", "dmr", "http://127.0.0.1:12434/engines/v1")
SD = Candidate("docker.io/ai/stable-diffusion:latest", "dmr", "http://127.0.0.1:12434/engines/v1")
ALL = [BIG, EIGHT, TINY_CODER, VISION, SD]


def decide(message, current, **kw):
    return route(message, current.model, ALL, **kw)


def test_model_sizes_are_read_from_the_name():
    sizes = {c.model: c.params_b for c in ALL}
    assert sizes[BIG.model] == 35 and sizes[EIGHT.model] == 8 and sizes[TINY_CODER.model] == 1.5 and sizes[VISION.model] == 30
    assert Candidate("mlx-community/qwen2.5-coder-7b-instruct-4bit:latest").params_b == 7  # "4bit" is not "4b"
    assert Candidate("qwen2.5:1.5b").params_b == 1.5 and Candidate("gpt-4o").params_b is None


def test_a_picture_request_switches_to_the_image_model():
    d = decide("draw a lighthouse at sunset, watercolor", EIGHT)
    assert d.switch and d.model == SD.model and d.intent == "image"
    assert decide("Create an image of a red fox in snow", BIG).model == SD.model


def test_the_message_after_a_picture_goes_back_to_a_text_model():
    d = decide("Plan a small Python function that checks whether a number is prime.", SD, previous_text=BIG.model)
    assert d.switch and d.model == BIG.model and "after the picture" in d.reason
    # With no memory of the last text model, the balanced 7-14B model is the default.
    assert decide("hello", SD).model == EIGHT.model


def test_the_image_model_stays_for_a_follow_up_picture_but_not_for_text():
    for follow_up in ("now draw it at night", "again but darker", "another one"):
        assert not decide(follow_up, SD).switch, follow_up
    for text in ("say hi in five words", "what is a lighthouse?", "thanks"):
        assert decide(text, SD).model == EIGHT.model, text


def test_text_about_images_is_not_a_picture_request():
    for text in ("Write a script that creates an image thumbnail for each upload",
                 "How do I make an image classification model?", "Describe this picture in detail"):
        assert classify(text, False, False, False, "chat") != "image", text


def test_a_small_model_is_moved_up_for_plans_and_agent_work():
    d = decide("Plan a small Python function that checks whether a number is prime.", TINY_CODER, plan_mode=True)
    assert d.switch and d.model == BIG.model and d.intent == "plan"
    d = decide("check my project files for errors", TINY_CODER, mode="agent")
    assert d.switch and d.model == EIGHT.model and "too small" in d.reason  # the 8B, not the 35B: enough and quick


def test_plan_mode_uses_the_biggest_model_that_fits():
    only_small_fits = lambda c: c.model != BIG.model  # the memory guard refuses the 35B right now
    d = decide("plan the migration", EIGHT, plan_mode=True, fits=only_small_fits)
    assert not d.switch  # nothing bigger fits, so stay on the 8B instead of an error
    assert decide("plan the migration", EIGHT, plan_mode=True).model == BIG.model


def test_a_model_that_would_be_refused_is_never_chosen():
    d = decide("check my project files for errors", TINY_CODER, mode="agent", fits=lambda c: c.model != EIGHT.model)
    assert d.model == BIG.model  # 8B refused, so the next that fits


def test_an_attached_picture_goes_to_a_vision_model_unless_it_is_an_edit():
    assert decide("what is in this photo?", EIGHT, has_image=True).model == VISION.model
    assert decide("remove the person on the left", EIGHT, has_image=True).model == SD.model
    assert not decide("what is in this photo?", VISION, has_image=True).switch


def test_a_capable_model_is_left_alone():
    for current in (EIGHT, BIG):
        for text, kw in (("hello", {}), ("say hi in five words", {}), ("fix the bug in my python function", {"mode": "agent"})):
            assert not decide(text, current, **kw).switch, (current.model, text)


def test_a_coding_model_big_enough_is_preferred_for_code():
    coder7 = Candidate("mlx-community/qwen2.5-coder-7b-instruct-4bit:latest", "dmr", "http://127.0.0.1:12434/engines/v1")
    d = route("refactor this python function", TINY_CODER.model, [TINY_CODER, EIGHT, coder7], mode="agent")
    assert d.model == coder7.model and "coding model" in d.reason


def test_unknown_current_model_is_never_touched():
    assert not route("draw a cat", "gpt-4o", ALL).switch


def test_route_endpoint_asks_the_load_guard_and_returns_the_decision(monkeypatch):
    from routes import local_model_routes as routes
    from src.auth_helpers import require_user

    asked = []
    monkeypatch.setattr(routes, "load_block_reason", lambda url, model: asked.append(model) or (
        "needs more memory than is free" if model == BIG.model else None))
    app = FastAPI()
    app.include_router(routes.setup_local_model_routes())
    app.dependency_overrides[require_user] = lambda: "admin"
    body = {"message": "plan the migration", "current": EIGHT.model, "plan_mode": True,
            "candidates": [{"model": c.model, "endpoint_id": c.endpoint_id, "url": c.url} for c in ALL]}

    res = TestClient(app).post("/api/local-models/route", json=body)

    assert res.status_code == 200
    # The guard refused the 35B, so the planner stays on the 8B and nothing else is suggested.
    assert res.json()["switch"] is False and res.json()["intent"] == "plan" and BIG.model in asked


# ---- a chat that already made a picture -------------------------------------------------------

def test_a_question_about_the_picture_stays_on_the_model_and_hands_it_the_picture():
    for current in (EIGHT, BIG, TINY_CODER):
        for text in ("what is in this image?", "describe the picture", "what colours does it use?", "is the lighthouse tall in it?"):
            d = decide(text, current, last_image=True)
            assert not d.switch and d.attach_last_image and d.intent == "about_image", (current.model, text)


def test_a_question_about_the_picture_never_picks_a_vision_model():
    assert not decide("what is in this image?", EIGHT, last_image=True).switch  # the 30B vision model is available


def test_asking_to_change_the_picture_uses_the_image_model_with_the_picture_attached():
    for text in ("make it darker", "add a boat to the picture", "change the sky to purple", "remove the lighthouse"):
        d = decide(text, EIGHT, last_image=True)
        assert d.switch and d.model == SD.model and d.attach_last_image and d.intent == "image_edit_last", text
    assert not decide("make it darker", SD, last_image=True).switch  # already there


def test_a_question_about_the_picture_asked_on_the_image_model_goes_back_to_text_with_the_picture():
    d = decide("what is in this image?", SD, last_image=True, previous_text=BIG.model)
    assert d.switch and d.model == BIG.model and d.attach_last_image


def test_unrelated_messages_in_a_chat_with_a_picture_are_not_treated_as_about_it():
    for text in ("write a python function to add two numbers", "hello", "say hi in five words",
                 "what does this function do?", "how do I fix this bug?"):
        d = decide(text, EIGHT, last_image=True)
        assert not d.attach_last_image, text


def test_without_a_picture_in_the_chat_nothing_is_attached():
    assert not decide("what is in this image?", EIGHT).attach_last_image


# ---- messages that need no thinking -------------------------------------------------------------

def test_short_plain_messages_need_no_thinking():
    for text in ("say hi in five words", "hello", "thanks!", "what is the capital of France?", "translate 'good morning' to French"):
        assert is_simple_chat(text), text


def test_anything_that_needs_working_out_keeps_its_thinking():
    for text in ("why is the sky blue?", "solve 12 * 7 + 3", "explain how recursion works", "compare React and Vue",
                 "write a python function to reverse a string", "draw a cat", "plan my week", "what is 15 + 27",
                 "a very long message " * 10):
        assert not is_simple_chat(text), text
    assert not is_simple_chat("say hi", mode="agent")
    assert not is_simple_chat("say hi", plan_mode=True)
    assert not is_simple_chat("say hi", has_attachments=True)
    assert not is_simple_chat("")


# ---- engines the load guard does not know (Rapid-MLX, Ollama): judged by the model's size ------------------------------

def test_memory_needed_is_estimated_from_the_name():
    assert estimate_gb("qwen3.6-35b-4bit") == pytest.approx(21.6, abs=0.1)  # measured: 20.4 GB
    assert estimate_gb("qwen2.5-coder-7b-4bit") == pytest.approx(5.5, abs=0.1)  # measured: 4.6 GB
    assert estimate_gb("huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S") == pytest.approx(16.6, abs=0.1)  # measured: ~18 GB
    assert estimate_gb("qwen2.5:1.5b") == pytest.approx(2.4, abs=0.1) and estimate_gb("gpt-4o") is None
    assert estimate_gb("mistral-7b-8bit") > estimate_gb("mistral-7b-4bit")


def _route_with_memory(monkeypatch, available, url="http://127.0.0.1:8081/v1/chat/completions", plan=True):
    from routes import local_model_routes as routes
    from src.auth_helpers import require_user

    monkeypatch.setattr(routes, "load_block_reason", lambda u, m: None)  # the Docker guard knows nothing about these
    monkeypatch.setattr(routes.memory_guard, "snapshot", lambda: {"total_gb": 48.0, "used_gb": 48.0 - available, "available_gb": available})
    app = FastAPI()
    app.include_router(routes.setup_local_model_routes())
    app.dependency_overrides[require_user] = lambda: "admin"
    cands = [{"model": "qwen2.5-coder-7b-4bit", "url": url}, {"model": "qwen3.6-35b-4bit", "url": url}]
    body = {"message": "plan the migration", "current": "qwen2.5-coder-7b-4bit", "plan_mode": plan, "candidates": cands}
    return TestClient(app).post("/api/local-models/route", json=body).json()


def test_plan_mode_does_not_pick_a_20_gb_model_the_mac_cannot_hold(monkeypatch):
    d = _route_with_memory(monkeypatch, available=17.0)  # what this Mac had: 17 GB free
    assert d["switch"] is False and d["intent"] == "plan"


def test_plan_mode_picks_it_once_there_is_room(monkeypatch):
    d = _route_with_memory(monkeypatch, available=40.0)
    assert d["switch"] is True and d["model"] == "qwen3.6-35b-4bit"


def test_a_remote_server_is_not_judged_by_this_macs_memory(monkeypatch):
    d = _route_with_memory(monkeypatch, available=3.0, url="https://llm.example.com/v1/chat/completions")
    assert d["switch"] is True and d["model"] == "qwen3.6-35b-4bit"
