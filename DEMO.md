# Demo script (about 60 seconds)

Start: `uv run flwr run . --stream` (or open the published app in Flower Chat). Steps 3 and 4 depend on features marked **planned** in `memory.yaml` (briefs/post, health check-in); until they land, the current build answers with the goal summary/recap only.

## Steps

1. **Goal**
   Type: `My goal: land an AI security role by December`
   Expect: goal + deadline, 3-5 milestones with weekly actions, "Alignment of your current routine: 0.xx (scorer: ...)", and numbered decision cards each with alternatives a/b/c.
   Then decide: `approve 1, 3, pick 2b, skip 4`
   Expect: "Recorded your decisions", goal line with alignment before -> after, one line per card with status.

2. **Find events**
   Type: `find events for my goal`
   Expect: "Ranked events for your goal" with new cards ranked by embedding score, each with a reason. Reply `approve 5`.

3. **Recap / post** (post/briefs: planned)
   Type: `recap`
   Expect: summary line `Goal ... | Alignment: before -> after` and each card with approved / skipped / picked.

4. **Health check-in, then recap** (health agent: planned)
   Type: `slept 5h`
   Expect: a card suggesting a lighter plan; approve it. Then `recap` again: alignment changes and the health note appears. In Hub mode only the text you typed is kept.

## Fallbacks

- No keys: the app uses the flower provider plus model2vec and the reply shows `scorer: model2vec`. Say so; it is by design.
- Provider/network error: router falls back down the chain, then to rule-based defaults; the chat never goes silent.
- Connectors (calendar/events) fail: events step may return few cards; continue with `recap`. Keep a pre-run session (`data/session.json`) or screenshots as backup.
- Flower Chat unavailable: run `uv run flwr run . --stream` locally.

## 60-second talk track

"Everyone has goals and a calendar that ignores them. Second Brain is a Flower AgentApp: you state a goal, it breaks it into milestones and scores your current routine against it with embeddings, so you see an alignment number. (10s)
It never acts on its own: every suggestion is a decision card with alternatives. I say 'approve 1, 3, pick 2b, skip 4' and that is the only authority it has. (15s)
Ask for events and it ranks real options against the goal and explains why. (10s)
Tell it 'slept 5h' and the plan adapts; the recap shows alignment before and after. (10s)
Privacy: on the Hub it keeps only what I typed; in local mode health data never leaves my machine. No keys? It still runs on the Flower provider and a small local embedder, and tells you so. (15s)"
