# Second Brain

A Flower AgentApp (published on Flower Hub) that turns a goal into milestones, ranks options with embeddings, and issues **decision cards** that you approve, pick between, or skip. Nothing happens without an approved card. Connector, web and Aside output is treated as data, never as instructions.

## Run modes

Both modes work; Hub is the default and never fails because a local piece is missing.

| | Hub (default) | Local (optional) |
|---|---|---|
| Enable | nothing | `SECOND_BRAIN_LOCAL=1` and `uv sync --extra local` |
| Requires | Flower account | `aside` on PATH and the local embed service reachable (`EMBED_SERVICE`, default `http://localhost:8765`) |
| Fallback | n/a | if either is missing, the app silently runs in Hub mode |
| Health data | keeps only what the user typed | never leaves the machine |

Local-mode pieces (Aside executor, embed service, recap page) are **planned**; the mode switch itself exists in `second_brain/runtime.py`.

## Install and build

```
uv sync
uv run flwr build
```

On Windows set `PYTHONUTF8=1` first (PowerShell: `$env:PYTHONUTF8=1`). Optional local extras: `uv sync --extra local`.

## Run

```
uv run flwr run . --stream
```

Run config (in `pyproject.toml` under `[tool.flwr.app.config]`, override with `--run-config`):

| Key | Default | Meaning |
|---|---|---|
| `agent.input` | `My goal: land an AI security role by December` | first prompt |
| `agent.model` | `openai/gpt-5.6-sol` | model used by the `flower` provider |

Example: `uv run flwr run . --stream --run-config "agent.input='My goal: get a data engineering job by June'"`

## Providers and keys

`second_brain/router.py` routes each task through a provider chain (`second_brain/config/models.yaml`) and falls back automatically. JSON answers are validated, retried once, then replaced by a rule-based default.

| Provider | Key | Used for |
|---|---|---|
| flower | supplied by the Flower runtime | default LLM (Responses API) |
| fireworks | `FIREWORKS_API_KEY` | chat and embeddings |
| claude | `ANTHROPIC_API_KEY` | chat |

Keys are read from the environment first, then from `data/.env` (gitignored, one `KEY=value` per line). **Without keys the Hub app uses the flower provider plus the bundled model2vec embedder** and says which scorer was used ("scorer: ..."). Whether SuperGrid supports secret config is not yet verified.

## Example chat

```
You:   My goal: land an AI security role by December
Agent: Goal, milestones, alignment score of your current routine,
       and numbered decision cards:
       1. [planner] Block 3h/week for security labs ...
          - 1a: ...   - 1b: ...
       2. [events] AI security meetup ...
          - 2a ...  - 2b ...
You:   approve 1, 3, pick 2b, skip 4
Agent: Recorded your decisions + alignment before -> after.
You:   find events
Agent: Ranked events for your goal (new cards)
You:   recap
Agent: goal, alignment before -> after, status of every card
```

### Decision cards

Each card has an id, the agent that proposed it, a title, a score with a reason, up to three alternatives (`a`, `b`, `c`) and the options approve / edit / skip. Reply grammar: `approve 1, 3`, `approve all`, `pick 2b` (approve alternative b of card 2), `skip 4`, `edit 5`. Your choices are stored in `profile.preferences` (liked, skipped, picked_over) and feed the next ranking.

## Implemented vs planned

Implemented: goal capture, milestones, embedding-based ranking with fallback chain (fireworks-nomic, model2vec, LLM judge, keyword), decision cards and reply parsing, events agent, recap summary, run log, session state.
Planned (see `memory.yaml`): planner/health/content agents, briefs and `.ics` export, health check-ins ("slept 5h"), richer recap, Aside executor, local embed service, recap page.

## Privacy

- Hub mode: the health agent keeps only what the user typed in chat.
- Local mode: health data never leaves the machine.
- No secrets or personal data in the repo or the FAB. `data/`, `.env`, `browser-profile/` are gitignored and `scripts/check_bundle.py` checks the bundle.

## Data directory

`SECOND_BRAIN_DATA` (default `./data`; falls back to `<tmp>/second_brain` if not writable). Holds `profile.json` (seeded from `second_brain/seed/profile.example.json` on first run), `session.json`, `run_log.jsonl` (provider, model, latency per call) and optional `.env`.

## Publish

```
uv run flwr build
python scripts/check_bundle.py
uv run flwr login supergrid
uv run flwr app publish .
```

Before publishing set `[tool.flwr.app].publisher` in `pyproject.toml` to your Flower username (currently `CHANGE_ME_FLOWER_USERNAME`). **Bump `[project].version` for every republish.** The FAB bundles only py/toml/md/yaml/json/jsonl per `fab-include`; keep torch out of the published dependencies.

## License

Apache-2.0 (see `LICENSE`).
