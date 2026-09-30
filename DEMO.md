# Demo script (about 90 seconds)

Start: open the published app in Flower Chat, or run `uv run python scripts/run_local.py` (local mode on top of Aside, Kimi via `data/.env`). Every turn shows a `model: ...` line and, where scoring happens, `scorer: ...`.

## Steps

1. **Goal**
   Type: `My goal: land an AI security role by December`
   Expect: goal + deadline, 3 milestones with weekly targets, "Alignment of your current routine: 0.xx", `model: kimi` (local) or `model: flower` / `rule-based` (Hub without keys), `scorer: fireworks-nomic` (with a Fireworks key) or a fallback, and numbered decision cards with alternatives a/b/c.
   Then decide: `approve 1, 3, pick 2b, skip 4`
   Expect: decisions recorded, alignment before -> after, briefs issued only for approved cards.

2. **Find events**
   Type: `find events for my goal`
   Expect: ranked event cards found by fetching Luma / Eventbrite / Meetup pages (web_fetch only; Aside in local mode). Reply `approve 5` to get an RSVP brief that stops before the final submit.

3. **Post**
   Type: `post about the meetup`
   Expect: one draft per community as cards; approve one to get a copy-ready post brief (local: Aside prepares it and pauses before posting).

4. **Health, then recap**
   Type: `slept 5h`
   Expect: one card with a lighter plan for tomorrow; approve it, then `recap`: alignment before -> after, decisions with your overrides, briefs issued, providers used. Hub mode keeps only what you typed.

5. **The phone beat (local mode with WhatsApp + Calendar)**
   After step 1 a poll "Approve this week's plan?" lands on WhatsApp. Vote on two or three slots; skipped ones come back as a second poll with alternative times. Aside then opens Google Calendar and creates the approved events; WhatsApp says "Added N events to your calendar". From the phone send `/events` (poll), `/slept 5h`, `/status`, `/recap`, `/stop`. Show the calendar reveal, then the recap's "Done for you" section.

## Fallbacks

- No keys (Hub): flower provider plus a no-download scorer; the reply says `model: flower` / `scorer: ngram-hash` (or `rule-based` if the runtime model is unavailable). This is by design.
- Provider error or timeout: the router falls through kimi -> minimax -> flower -> rule-based defaults; the chat never goes silent (it prints "Working on it..." immediately).
- web_fetch returns nothing: events fall back to communities from the profile; continue with step 3.
- WhatsApp poll flaky or Aside unavailable: the app falls back to numbered text, or to deciding in chat and printing `.ics` files.
- Flower Chat unavailable: `uv run python scripts/run_local.py --once "..." "..."`.

## 60-second talk track

"Everyone has goals and a calendar that ignores them. Second Brain is a Flower AgentApp published on the Hub: you state a goal, Kimi from the hackathon endpoints breaks it into milestones, and embeddings score your routine against it, so you see an alignment number. (15s)
It never acts on its own: every suggestion is a decision card with alternatives. I say 'approve 1, 3, pick 2b, skip 4' and that is its only authority. (15s)
Events come from fetched pages, ranked against the goal. Approved ones become a brief that stops before the final click, run through Aside or any browser agent. (15s)
'Slept 5h' changes tomorrow's plan, and the recap shows alignment before and after. Health text stays what I typed on the Hub, and on my machine in local mode. (15s)"
