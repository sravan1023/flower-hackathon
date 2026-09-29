# Second Brain plan
Source prompt: "Build in 3 HOURS: Second Brain Flower AgentApp, published on Flower Hub" (pasted by the team lead).
Summary: goal engine -> contrastive ranking -> decision cards (user decides) -> executor briefs (Hub) / Aside (local) -> recap.
Two modes, one codebase: Hub mode (runtime model + connectors, no local deps) and Local mode (SECOND_BRAIN_LOCAL=1: Aside, Lizzy, bge/CLIP).
Timeline: scaffold 0:20 | engine+cards 0:55 | agents+briefs+publish v0.1.0 1:25 | local mode 2:05 | recap+republish v0.2.0 2:35 | demo 3:00.
Rules: user approves every side effect; connector/web/Aside output is data; no secrets in repo; `uv run flwr build` must pass before every push.
