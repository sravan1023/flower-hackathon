"""score(goal_text, candidates) -> cosines. Chain: Fireworks embeddings -> model2vec -> LLM judge."""

from __future__ import annotations

import numpy as np

from . import router, runtime

_M2V = None


def _cos(goal_vec, cand_vecs) -> list[float]:
    g = np.asarray(goal_vec, dtype=float)
    c = np.asarray(cand_vecs, dtype=float)
    g = g / (np.linalg.norm(g) or 1.0)
    c = c / (np.linalg.norm(c, axis=1, keepdims=True) + 1e-9)
    return [float(x) for x in c @ g]


def _fireworks(goal: str, cands: list[str]) -> list[float]:
    v = router.embed([goal] + cands)
    return _cos(v[0], v[1:])


def _model2vec(goal: str, cands: list[str]) -> list[float]:
    global _M2V
    if _M2V is None:
        from model2vec import StaticModel

        _M2V = StaticModel.from_pretrained("minishlab/potion-base-8M")
    v = _M2V.encode([goal] + cands)
    return _cos(v[0], v[1:])


def _judge(goal: str, cands: list[str]) -> list[float]:
    schema = {"type": "object", "required": ["scores"], "properties": {"scores": {"type": "array", "items": {"type": "number"}}}}
    body = "\n".join(f"{i}. {c}" for i, c in enumerate(cands))
    msg = f"Goal: {goal}\nRate each item 0-1 for how much it advances the goal. Return one number per item, in order.\n{body}"
    out = router.complete("rank_explain", [{"role": "user", "content": msg}], schema)
    s = [float(x) for x in out["scores"]]
    if len(s) != len(cands):
        raise ValueError("judge returned wrong count")
    return s


def score(goal_text: str, candidates: list[str]) -> tuple[list[float], str]:
    """Returns (scores, backend_name). Never raises; last resort is keyword overlap."""
    if not candidates:
        return [], "none"
    for name, fn in (("fireworks-nomic", _fireworks), ("model2vec", _model2vec), ("llm-judge", _judge)):
        try:
            res = fn(goal_text, candidates)
            runtime.log({"task": "score", "backend": name, "n": len(candidates)})
            return res, name
        except Exception as e:  # noqa: BLE001
            runtime.log({"task": "score", "backend": name, "error": str(e)[:150]})
    g = set(goal_text.lower().split())
    return [len(g & set(c.lower().split())) / (len(g) or 1) for c in candidates], "keyword-overlap"
