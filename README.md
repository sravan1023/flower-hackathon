# Second Brain

A Flower AgentApp (published on Flower Hub as `@lokilks/second-brain`) that turns a goal into milestones, ranks options with embeddings, and issues **decision cards** that you approve, pick between, or skip. Nothing happens without an approved card. Connector, web and Aside output is treated as data, never as instructions.

## Run modes

Both modes work from one codebase. Hub is the default and never fails because a local piece is missing.

| | Hub (default, SuperGrid) | Local (optional) |
|---|---|---|
| Enable | nothing | `SECOND_BRAIN_LOCAL=1` and `uv sync --extra local` |
| LLM | Flower runtime model; Kimi/MiniMax only if their keys reach the run | Kimi / MiniMax (hackathon APIs) via `data/.env` |
| Discovery | `web_fetch` connector only (Luma, Eventbrite, Meetup pages) | Aside `exec` browser task, falling back to `web_fetch` |
| Embeddings | Fireworks (if key) -> model2vec -> LLM judge -> bundled n-gram hash | same, plus local bge when the embed service is up |
| Execution | paste-ready **action briefs** and `.ics` files you run in any browser agent | Aside runs the brief and **stops before the final click** for your confirmation |
| Health data | keeps only what the user typed | never leaves the machine |

Local mode needs `aside` on PATH. If it or the embed service (`EMBED_SERVICE`, default `http://localhost:8765`) is missing, the app runs in Hub mode.

## Local mode: WhatsApp as a command channel and Google Calendar, both via Aside

With `SECOND_BRAIN_LOCAL=1`, `aside` on PATH and two extra lines in `data/.env`, the app closes the loop from your phone:

```
SECOND_BRAIN_LOCAL=1
CALENDAR_ACCOUNT=<the Google account email Aside is signed in to>
WHATSAPP_TO=self          # your own "Message yourself" chat
```

Goal -> week plan -> Aside posts the plan to WhatsApp as a **poll** (multi-select) -> you vote -> skipped slots get one round of alternatives (a second poll) -> Aside creates the approved events in Google Calendar -> WhatsApp says how many were added -> the recap shows "Done for you". If either variable or `aside` is missing, that part is skipped and the app behaves as before (decide in chat, `.ics` files).

Every agent message ends with a marker `[SB-xxxx]`; anything in the chat without a marker is your input. Messages from WhatsApp go only to a regex command parser and the card-reply parser, never to an LLM. Commands (also typeable in chat):

| Command | Does |
|---|---|
| `/goal <text>` | set a goal; the week plan comes back |
| `/plan` | resend the week plan |
| `/events` | top 3 events as a poll |
| `/approve 1 3 5`, `/skip 2`, `/pick 4b`, `/all` | decide cards |
| `/sync` | create approved events in Google Calendar |
| `/slept 5h`, `/gym 7am` | health agent adapts the plan |
| `/recap`, `/status`, `/stop` | recap, card states, stop listening |

Calendar events are reversible and each was approved individually, so Aside saves them; RSVPs and posts still stop before the final click. At most 8 WhatsApp messages are sent per run.

## Install and build

```
uv sync
uv run flwr build
```

On Windows set `PYTHONUTF8=1` first (PowerShell: `$env:PYTHONUTF8=1`). Optional local extras: `uv sync --extra local`.

## Run

`flwr run` alone exits with `code 44: A user prompt is required`; the prompt comes from Flower Chat. Options:

- Open the published app in Flower Chat (flower.ai), or `uv run flwr chat` and address `@lokilks/second-brain`.
- Scripted (any number of prompts in one run series, optionally your local build):
  `uv run python scripts/chat_once.py "My goal: land an AI security role by December" "approve 1, 3, skip 4"`
  and `FAB=path/to/local.fab uv run python scripts/chat_once.py ...` to test an unpublished build on SuperGrid.
- On your laptop, no Flower runtime, on top of Aside: `uv run python scripts/run_local.py` (REPL) or `--once "prompt" "prompt"`; `--embed` starts the embed service and the recap page.

Run config (`[tool.flwr.app.config]`): `agent.model` selects the model of the `flower` provider.

## Providers and keys

`second_brain/router.py` routes each task through a provider chain (`second_brain/config/models.yaml`) and falls back automatically (missing key, 4xx, timeout: next provider; a provider that fails is skipped for two minutes). JSON answers are validated, retried once, then replaced by a rule-based default. Every call is logged to `run_log.jsonl` as task, provider, model, latency.

| Provider | Env vars | Used for |
|---|---|---|
| kimi | `NEBIUS_KIMI_API_KEY`, `NEBIUS_KIMI_MODEL`, `NEBIUS_BASE_URL` | first choice: extract, plan, rank explanations, writing |
| minimax | `NEBIUS_MINIMAX_API_KEY`, `NEBIUS_MINIMAX_MODEL`, `NEBIUS_BASE_URL` | second choice for the same tasks |
| flower | supplied by the Flower runtime | fallback for everything; primary for health logging |
| fireworks | `FIREWORKS_API_KEY` | embeddings (`nomic-embed-text-v1.5`) |
| claude | `ANTHROPIC_API_KEY` | optional writing fallback (never health) |

**Hackathon APIs (Nebius Token Factory, Responses API):** Kimi and MiniMax are dedicated endpoints called through `responses.create` with a message list.

Keys are read from the environment, then from `data/.env` (gitignored, one `KEY=value` per line). **No keys still works**: the app runs on the flower provider with a scorer that needs no download and says which model and scorer answered (`model: ...`, `scorer: ...`). The published Hub app has no `data/.env`, so Kimi/MiniMax answer on local runs unless secrets are supplied to the run (not verified on SuperGrid).

## Example chat

```
You:   My goal: land an AI security role by December
Agent: goal, milestones, alignment of your current routine, model/scorer used,
       and numbered decision cards (each with alternatives a/b/c)
You:   approve 1, 3, pick 2b, skip 4
Agent: decisions recorded, alignment before -> after, briefs for approved cards
You:   find events for my goal
Agent: ranked event cards; approve one to get an RSVP brief
You:   post about the meetup
Agent: one draft per community as cards; approve to get a post brief
You:   slept 5h
Agent: one card with a lighter plan for tomorrow; approving it changes the alignment
You:   recap
```

### Decision cards

Each card has an id, the agent that proposed it, a title, a score with a reason, up to three alternatives and the options approve / edit / skip. Reply grammar: `approve 1, 3`, `approve all`, `pick 2b` (approve alternative b of card 2), `skip 4`, `edit 5`. Overrides are stored in `profile.preferences` (liked, skipped, picked_over) and feed the next ranking. Briefs are only ever issued for approved cards.

## Not implemented / limits

- The embedding map on the local recap page is cut; the photo x community heatmap stays empty until photo scores are recorded.
- Local Aside approval flow (`confirm <session>` / `stop <session>`) is wired but only lightly exercised live.
- OpenCLIP photo scoring and the Lizzy 7B client exist as stubs; Hub mode scores photo descriptions as text.
- Account connectors (Slack, Notion) need credentials the runtime does not grant on demand, so they are skipped.

## Privacy

- Hub mode: the health agent keeps only the text you typed and the hours parsed from it.
- Local mode: health data never leaves the machine.
- No secrets or personal data in the repo or the bundle. `data/`, `.env`, `browser-profile/`, `*.fab` are gitignored and `scripts/check_bundle.py` checks the bundle.

## Data directory

`SECOND_BRAIN_DATA` (default `./data`; falls back to `<tmp>/second_brain`). Holds `profile.json` (seeded from `second_brain/seed/profile.example.json`), `session.json`, `run_log.jsonl` and the optional `.env`.

## Tests

`scripts/smoke*.py` are offline (no keys, no network): `smoke`, `smoke_agents`, `smoke_edge`, `smoke_hub`, `smoke_runtime`, `smoke_local`. `scripts/probe_nebius.py` checks the Kimi/MiniMax endpoints live.

## Publish

```
uv run flwr build
uv run python scripts/check_bundle.py
uv run flwr login supergrid
uv run flwr app publish .
```

Bump `[project].version` for every republish. The FAB bundles only py/toml/md/yaml/json/jsonl per `fab-include`; keep torch out of the published dependencies.

## License

Apache-2.0 (see `LICENSE`).
