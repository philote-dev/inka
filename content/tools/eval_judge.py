"""The LLM-as-judge, rater 2 for the gold-set gate (L4.0e).

Frank is rater 1 and the adjudicator (C7); this module is the second opinion. It
scores a candidate item against its gold reference on the rubric in
``docs_pgrep/ai/gold-set-spec.md`` section 5, blind to which system produced the
item. The judge model is pinned to a dated OpenAI snapshot, different from the
generator so it never grades its own outputs.

Two judges share one interface:
  - ``OpenAIJudge``: the real judge (needs the API key).
  - ``HeuristicJudge``: a deterministic offline stand-in for smoke tests, so the
    scoring pipeline runs end to end without burning API calls or a key.

A refused candidate (the AI declined to cite a source) is scored without a model
call: it asserts no facts (fact precision holds vacuously) but is not useful.
"""

from __future__ import annotations

import json
import os
import re

_WORD = re.compile(r"[a-z0-9]+")

RUBRIC = """You grade a study item against a verified gold reference for a Physics GRE prep app.
Be strict and objective. You do not know which system produced the item.

Return STRICT JSON only, no prose.

For a CARD, return:
{"fact_precision": bool,   // true only if every asserted fact is correct, no wrong-fact
 "useful": bool,           // true only if correct AND it actually teaches or tests the point
 "category": "correct_useful" | "wrong_fact" | "correct_bad_teaching",
 "notes": "one short sentence"}

For a PROBLEM (MCQ), return:
{"fact_precision": bool,
 "key_correct": bool,      // is the marked key correct
 "useful": bool,
 "distractors": [ {"plausible": bool, "misconception_grounded": bool,
                   "non_overlapping": bool, "source_grounded": bool}, ... 4 items ],
 "notes": "one short sentence"}
"""


def _refused_judgment(kind: str) -> dict:
    j = {"fact_precision": True, "useful": False, "refused": True,
         "notes": "refused: no cited source"}
    if kind == "problem":
        j.update({"key_correct": False,
                  "distractors": [{"plausible": False, "misconception_grounded": False,
                                   "non_overlapping": False, "source_grounded": False}
                                  for _ in range(4)]})
    else:
        j["category"] = "correct_bad_teaching"
    return j


class HeuristicJudge:
    """Deterministic offline judge for smoke tests (no API, no key)."""

    model = "heuristic-smoke"

    def judge(self, item: dict, gold: dict, kind: str) -> dict:
        if item.get("refused"):
            return _refused_judgment(kind)
        item_toks = set(_WORD.findall((item.get("text", "") + " " +
                                       item.get("back", "") + " " +
                                       item.get("stem", "")).lower()))
        gold_toks = set(_WORD.findall(json.dumps(gold).lower()))
        overlap = len(item_toks & gold_toks) / (len(gold_toks) or 1)
        has_source = bool(item.get("source_ref"))
        choices = item.get("choices") or []
        # A retrieval baseline returns a raw passage (text only). A generated
        # item carries card or problem structure. The heuristic rewards the
        # latter, matching the gold-spec point that search rarely yields a
        # correct-and-useful item.
        if kind == "problem":
            has_structure = len(choices) >= 5 and bool(item.get("key"))
        else:
            back = item.get("back", "")
            has_structure = bool(back) and len(back) < 600
        useful = has_source and has_structure and overlap > 0.15
        j = {"fact_precision": has_source, "useful": bool(useful),
             "notes": f"heuristic overlap={overlap:.2f} structure={has_structure}"}
        if kind == "problem":
            distinct = len({str(c) for c in choices}) == len(choices) and len(choices) >= 5
            grounded = bool(item.get("distractor_rationales"))
            j["key_correct"] = has_structure and has_source
            j["distractors"] = [{"plausible": bool(useful), "misconception_grounded": grounded,
                                 "non_overlapping": distinct, "source_grounded": has_source}
                                for _ in range(4)]
        else:
            j["category"] = "correct_useful" if useful else (
                "wrong_fact" if not has_source else "correct_bad_teaching")
        return j


class OpenAIJudge:
    """The real rater-2 judge, a pinned OpenAI snapshot, blind to system."""

    def __init__(self, model: str, temperature: float = 0.0):
        from openai import OpenAI

        self.model = model
        self.temperature = temperature
        self._client = OpenAI()

    def judge(self, item: dict, gold: dict, kind: str) -> dict:
        if item.get("refused"):
            return _refused_judgment(kind)
        # Blind: strip any system identifier before showing the item.
        shown = {k: v for k, v in item.items() if k not in ("system", "target_id")}
        user = (f"KIND: {kind}\n\nGOLD REFERENCE:\n{json.dumps(gold, ensure_ascii=False)}\n\n"
                f"ITEM TO GRADE:\n{json.dumps(shown, ensure_ascii=False)}")
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": RUBRIC},
                      {"role": "user", "content": user}],
        )
        try:
            return json.loads(resp.choices[0].message.content)
        except (json.JSONDecodeError, AttributeError, IndexError):
            return _refused_judgment(kind) | {"notes": "judge returned unparseable output"}


def make_judge(mode: str, model: str | None = None):
    """``mode`` is 'openai' (needs ``model``) or 'fake'/'heuristic' (offline)."""
    if mode in ("fake", "heuristic", "none"):
        return HeuristicJudge()
    if mode == "openai":
        if not model:
            raise ValueError("openai judge requires a pinned model snapshot")
        return OpenAIJudge(model)
    raise ValueError(f"unknown judge mode: {mode}")
