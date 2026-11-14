"""Pick the local model that fits what the user just asked, so they don't have to switch by hand.

Pure and cheap: the message is read with a few rules (no model is loaded to decide), and the
RAM check is injected, so a model that the memory guard would refuse is never chosen. It only
ever *keeps* the current model unless that model is wrong for the job:

  image request            -> an image model, and back to a text model for the next message
  picture attached         -> a vision model (or the image model, if the user is editing it)
  plan mode                -> the biggest model that fits (the planner)
  agent / tools / code     -> at least MIN_AGENT_B parameters (small models can't follow tool prompts)
  anything else            -> stay where you are
"""

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from src.image_model_ids import looks_like_image_generation_model, model_id_leaf

MIN_AGENT_B = 7.0       # below this, models drift in agent/plan turns (a 1.5B coder answered "Reference context received.")
BALANCED_MAX_B = 14.0   # the default pick when the job doesn't need the biggest model

_PARAMS = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)b(?![a-z])")
_IMAGE_REQUEST = re.compile(
    r"\b(draw|paint|sketch|render|illustrate|generate|create|make|design|produce)\b[^.\n]{0,40}"
    r"\b(image|picture|photo|illustration|artwork|logo|wallpaper|portrait|painting|drawing|icon|poster)s?\b"
    r"|\b(image|picture|photo|illustration|drawing|painting|portrait) of\b"
    r"|^\s*(please\s+)?(draw|paint|sketch)\b"
    r"|\b(draw|paint|sketch)\s+(me\s+)?(an?|the|some)\b",
    re.I,
)
# On the image model, these mean "another picture", anything else is a text turn.
_IMAGE_FOLLOWUP = re.compile(
    r"\b(draw|paint|sketch|render|generate|regenerate|again|another|variation|redo|make it|same but|but with|"
    r"in the style|darker|brighter|bigger|smaller|at night|in the day)\b",
    re.I,
)
_NOT_AN_IMAGE_REQUEST = re.compile(
    r"classif|process|dataset|recogni|pipeline|docker|upload|resize|compress|format|function|script|code|\bapi\b|"
    r"\bbug\b|error|embed|caption|describe|analy[sz]e|explain|\bwhat\b|\bhow\b|library|model|detect|ocr",
    re.I,
)
_EDIT_VERB = re.compile(r"\b(edit|change|remove|add|replace|restyle|recolou?r|turn|make (it|this|him|her|them)|erase|fix)\b", re.I)
# A chat that already has a generated picture: is the message about it, or asking to change it?
_ABOUT_THE_PICTURE = re.compile(
    r"\b(this|that|the|it|its|above|previous|last|generated|my)\b[^.?!\n]{0,24}\b(image|picture|pic|photo|drawing|painting|"
    r"illustration|artwork|render|result)\b|\b(image|picture|photo)\b|\b(in|on|of|about) (it|this|that)\b|"
    r"\bdescribe it\b|\bwhat('s| is| are) (in|on) it\b",
    re.I,
)
# "what colours does it use?": no picture word, so it only counts as a question about the picture when it is
# a short question about "it/this/that" and is not about code.
_PRONOUN_QUESTION = re.compile(r"^\s*(what|which|how|where|is|are|does|do|why|can you (see|tell))\b[^.?!\n]*\b(it|this|that)\b|"
                               r"\b(colou?rs?|composition|mood|lighting|shadows?|foreground|background)\b", re.I)
_CHANGE_THE_PICTURE = re.compile(
    r"\b(make it|turn it|change (it|the)|add (a|an|some|the)|remove (the|a)|replace|recolou?r|restyle|darker|brighter|"
    r"sky|background|lighting|style)\b",
    re.I,
)
_CODE = re.compile(
    r"\b(code|function|script|bug|debug|refactor|regex|sql|python|javascript|typescript|rust|swift|bash|compile|"
    r"stack ?trace|traceback|unit test|implement|class|api|repo|commit)\b|```|c\+\+",
    re.I,
)


@dataclass
class Candidate:
    model: str
    endpoint_id: str = ""
    url: str = ""

    @property
    def leaf(self) -> str:
        return model_id_leaf(self.model)

    @property
    def is_image(self) -> bool:
        return looks_like_image_generation_model(self.model)

    @property
    def params_b(self) -> Optional[float]:
        m = _PARAMS.search(self.leaf)
        return float(m.group(1)) if m else None

    @property
    def is_vision(self) -> bool:
        return bool(re.search(r"(^|[-_.])(vl|vision|llava|pixtral|minicpm-v)([-_.:\d]|$)", self.leaf))

    @property
    def is_coder(self) -> bool:
        return "coder" in self.leaf or "codestral" in self.leaf


_QUANT_BITS = re.compile(r"(?<![a-z0-9])(\d{1,2})-?bit|(?<![a-z0-9])q(\d)[_k]", re.I)


def estimate_gb(model_id: str) -> Optional[float]:
    """Rough GB a local model needs once loaded, from its name: parameters x bits per weight, plus overhead.

    For engines the load guard does not know (Rapid-MLX, Ollama). Checked against measured loads: a 4-bit 35B is 20.4 GB
    (estimate 21.6), a 4-bit 7B is 4.6 GB (estimate 5.5). Unknown sizes return None. Most local builds are 4-bit.
    """
    params = Candidate(model_id).params_b
    if params is None:
        return None
    match = _QUANT_BITS.search(model_id_leaf(model_id))
    bits = int(match.group(1) or match.group(2)) if match else 4
    return round(params * bits / 8 * 1.15 + 1.5, 1)


@dataclass
class Decision:
    switch: bool = False
    model: str = ""
    endpoint_id: str = ""
    url: str = ""
    reason: str = ""
    intent: str = "chat"
    attach_last_image: bool = False  # hand the chat's last generated picture to this message as context


def classify(message: str, has_image: bool, plan_mode: bool, approved_plan: bool, mode: str,
             on_image_model: bool = False, last_image: bool = False) -> str:
    text = message or ""
    if has_image and _EDIT_VERB.search(text):
        return "image_edit"
    if has_image:
        return "vision"
    about = bool(_ABOUT_THE_PICTURE.search(text) or (_PRONOUN_QUESTION.search(text) and not _CODE.search(text)))
    if last_image and not plan_mode and not approved_plan and not (_CODE.search(text) and not about):
        # The chat already made a picture. Changing it needs the image model; anything else about it is answered
        # where the chat is, with the picture handed over as context (never a model switch for a question).
        if _CHANGE_THE_PICTURE.search(text) and (about or _EDIT_VERB.search(text)):
            return "image_edit_last"
        if about and not _IMAGE_REQUEST.search(text):
            return "about_image"
    if _IMAGE_REQUEST.search(text) and not _NOT_AN_IMAGE_REQUEST.search(text):
        return "image"
    if on_image_model and not plan_mode and not approved_plan and mode != "agent" and _IMAGE_FOLLOWUP.search(text):
        return "image"
    if plan_mode:
        return "plan"
    if approved_plan:
        return "execute"
    if mode == "agent" or _CODE.search(text):
        return "agent"
    return "chat"


def route(
    message: str,
    current: str,
    candidates: List[Candidate],
    *,
    has_image: bool = False,
    plan_mode: bool = False,
    approved_plan: bool = False,
    mode: str = "chat",
    previous_text: str = "",
    last_image: bool = False,
    fits: Callable[[Candidate], bool] = lambda c: True,
) -> Decision:
    decision = _route(message, current, candidates, has_image, plan_mode, approved_plan, mode, previous_text, last_image, fits)
    decision.attach_last_image = decision.intent in ("about_image", "image_edit_last")
    return decision


def _route(message, current, candidates, has_image, plan_mode, approved_plan, mode, previous_text, last_image, fits) -> Decision:
    cur = next((c for c in candidates if c.model == current), None)
    intent = classify(message, has_image, plan_mode, approved_plan, mode,
                      on_image_model=bool(cur and cur.is_image), last_image=last_image)
    if cur is None:
        return Decision(intent=intent)  # not one of the models we can reason about: leave it alone

    images = [c for c in candidates if c.is_image]
    texts = [c for c in candidates if not c.is_image]

    def keep() -> Decision:
        return Decision(intent=intent)

    def to(target: Candidate, reason: str) -> Decision:
        if target.model == cur.model and target.endpoint_id == cur.endpoint_id:
            return keep()
        return Decision(True, target.model, target.endpoint_id, target.url, reason, intent)

    def fitting(pool: List[Candidate]) -> List[Candidate]:
        out = []
        for c in pool:
            if c is cur or fits(c):
                out.append(c)
        return out

    def by_size(pool: List[Candidate], biggest: bool = True) -> List[Candidate]:
        return sorted(pool, key=lambda c: c.params_b or 0.0, reverse=biggest)

    def balanced(pool: List[Candidate]) -> Optional[Candidate]:
        """Smallest model that can run tools, preferring the 7-14B class; else the biggest that fits."""
        usable = [c for c in fitting(pool) if (c.params_b is None or c.params_b >= MIN_AGENT_B)]
        mid = [c for c in usable if c.params_b is not None and c.params_b <= BALANCED_MAX_B]
        if mid:
            return by_size(mid, biggest=True)[0]
        return by_size(usable)[0] if usable else None

    # 1. Pictures.
    if intent in ("image", "image_edit", "image_edit_last"):
        if cur.is_image:
            return keep()
        same_server = [c for c in images if c.url == cur.url] or images
        pick = next(iter(fitting(same_server)), None)
        if pick:
            return to(pick, "Picture request: switching to the image model.")
        return keep()
    if cur.is_image:
        # The previous turn drew a picture; this one is text. Without this every later message drew another.
        back = next((c for c in texts if c.model == previous_text), None)
        back = back if back and fits(back) else balanced(texts)
        return to(back, "Back to a text model after the picture.") if back else keep()

    # 2. A picture was attached for the model to look at.
    if intent == "vision" and not cur.is_vision:
        vision = fitting([c for c in texts if c.is_vision])
        if vision:
            return to(by_size(vision)[0], "A picture is attached: switching to a vision model.")
        return keep()

    # 3. Planning: the biggest model that fits.
    if intent == "plan":
        general = [c for c in texts if not c.is_vision] or texts
        best = next(iter(by_size(fitting(general))), None)
        if best and (best.params_b or 0) > (cur.params_b or 0):
            return to(best, "Planning: using the biggest model that fits in memory.")
        return keep()

    # 4. Doing the work: never on a model too small to follow tool prompts.
    if intent in ("agent", "execute") and cur.params_b is not None and cur.params_b < MIN_AGENT_B:
        if _CODE.search(message or ""):
            coders = [c for c in fitting(texts) if c.is_coder and (c.params_b or 0) >= MIN_AGENT_B]
            if coders:
                return to(by_size(coders, biggest=False)[0], "Code task: switching to a coding model.")
        pick = balanced(texts)
        if pick:
            return to(pick, f"{cur.params_b:g}B is too small for tools and plans: switching to a larger model.")
    return keep()


_NEEDS_REASONING = re.compile(
    r"\b(why|how (do|does|did|would|can|could|should)|prove|solve|calculate|compute|derive|compare|explain|analy[sz]e|"
    r"step by step|plan|design|debug|optimi[sz]e|difference between|pros and cons|should i|best way|reason|evaluate)\b|"
    r"\d\s*[-+*/^=]\s*\d",
    re.I,
)


def is_simple_chat(message: str, mode: str = "chat", plan_mode: bool = False, approved_plan: bool = False,
                   has_attachments: bool = False) -> bool:
    """A short, plain message that needs no reasoning ("say hi in five words", "thanks", "what's the capital of France").

    Thinking models spend hundreds of tokens (and sometimes loop) on these for nothing, so thinking is switched off.
    Anything that looks like code, a picture, a plan, a question that needs working out, tools or an attachment is left alone.
    """
    text = (message or "").strip()
    if not text or has_attachments or plan_mode or approved_plan or mode == "agent":
        return False
    if len(text) > 120 or len(text.split()) > 14 or "\n" in text:
        return False
    return not (_CODE.search(text) or _IMAGE_REQUEST.search(text) or _NEEDS_REASONING.search(text))
