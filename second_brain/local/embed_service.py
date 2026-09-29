"""Local embed + CLIP + recap service on localhost:8765. Run: python -m second_brain.local.embed_service"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .. import runtime

app = FastAPI(title="second-brain local")
_ST = None
_CLIP = None


class EmbedReq(BaseModel):
    texts: list[str]


class ClipReq(BaseModel):
    image_paths: list[str]
    texts: list[str]


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/embed")
def embed(req: EmbedReq) -> dict:
    global _ST
    if _ST is None:
        from sentence_transformers import SentenceTransformer

        _ST = SentenceTransformer(os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5"))
    v = _ST.encode(req.texts, normalize_embeddings=True)
    return {"vectors": [[float(x) for x in row] for row in v]}


@app.post("/clip/score")
def clip_score(req: ClipReq) -> dict:
    global _CLIP
    import open_clip
    import torch
    from PIL import Image

    if _CLIP is None:
        model, _, pre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
        _CLIP = (model.eval(), pre, open_clip.get_tokenizer("ViT-B-32"))
    model, pre, tok = _CLIP
    with torch.no_grad():
        imgs = torch.stack([pre(Image.open(p).convert("RGB")) for p in req.image_paths])
        fi = model.encode_image(imgs)
        ft = model.encode_text(tok(req.texts))
        fi /= fi.norm(dim=-1, keepdim=True)
        ft /= ft.norm(dim=-1, keepdim=True)
        return {"matrix": (fi @ ft.T).tolist()}


def _read_json(name: str, default):
    p = runtime.data_dir() / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def build_recap() -> dict:
    """Assemble the recap page payload from data_dir(). Tolerates missing/empty files."""
    session = _read_json("session.json", {}) or {}
    profile = _read_json("profile.json", {}) or {}
    log = runtime.read_log() if (runtime.data_dir() / "run_log.jsonl").exists() else []
    cards = session.get("cards", []) or []
    events = [{"title": c.get("title", ""), "score": c.get("score", 0), "status": c.get("status", "")} for c in cards]
    events.sort(key=lambda e: -float(e["score"] or 0))
    decisions = [{"id": c.get("id"), "title": c.get("chosen") or c.get("title"), "status": c.get("status")} for c in cards if c.get("status") not in (None, "pending")]
    communities = profile.get("communities", []) or []
    heat = session.get("heatmap") or {"rows": [], "cols": communities, "values": []}
    actions = [e for e in log if e.get("task") in ("aside", "action", "executor", "ics", "brief")][-30:]
    return {
        "goal": session.get("goal", ""),
        "scorer": session.get("scorer", ""),
        "alignment_before": session.get("alignment_before"),
        "alignment_after": session.get("alignment_after"),
        "decisions": decisions,
        "events": events,
        "heatmap": heat,
        "actions": actions,
        "log_count": len(log),
    }


@app.get("/recap/data.json")
def recap_data() -> dict:
    return build_recap()


@app.get("/recap", response_class=HTMLResponse)
def recap_page() -> str:
    return (Path(__file__).parent.parent / "recap_page" / "index.html").read_text(encoding="utf-8")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
