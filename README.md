# Manas: a living brain for every customer

Manas (placeholder name) joins scattered customer tables into one brain per customer and decides who to contact, when, on which channel and in what tone. Every decision carries its receipts.

## How a brain is built

| Layer | What it is | Where |
|---|---|---|
| World | Per-customer graph of objects and links from your own tables | `backend/app/brain/build.py` |
| Memory | Notes and replies read in time (English, Hindi, Hinglish). "Kal" means the day after it was written | `backend/app/brain/memory.py` |
| Facts | About 25 answers computed in code, each with formula and cited rows | `backend/app/brain/facts.py` |
| Beliefs | Judgements citing facts. Too little evidence returns `insufficient_evidence`. Optional independent judge | `backend/app/brain/beliefs.py` |
| Persona | Agent profile of the person (MiroFish idea). The model only sees a pseudonym | `backend/app/brain/build.py` |
| Digital twin | Each channel x window x tone candidate scored on a metric ladder, then role-played on the persona (MiroFish idea) | `backend/app/twin.py` |
| Council | Outcome Analyst, Customer Advocate, Cost Strategist argue; a moderator decides (BettaFish ForumEngine idea) | `backend/app/council.py` |
| Guards | Consent, DND, RBI 08:00 to 19:00 recovery hours, frequency caps, open promises, disputes | `backend/app/decide.py` |
| Uplift guard | No message for people who convert anyway | `backend/app/decide.py` |
| Holdout | Fixed 10% never messaged, so uplift is measured, not claimed | `backend/app/decide.py` |

Goal packs (`backend/app/packs.py`): **EMI collection** and **Subscription renewal**. Add a pack to support a new goal.

## Run it

Backend (Python 3.11+, [uv](https://docs.astral.sh/uv/)):

```powershell
cd backend; uv sync; uv run uvicorn app.main:app --port 8000
```

Frontend (Node 20+):

```powershell
cd web; npm install; npm run dev
```

Open http://localhost:3000 and press **Load demo data and run everything**. Demo customers are fictional.

### Turn on Claude

Without credentials everything runs on deterministic rules. Set `ANTHROPIC_API_KEY` (or log in with `ant auth login` and set `MANAS_LLM=1`) before starting the backend to add: note extraction, the independent belief judge, persona narratives, twin role-play, the LLM council and open questions in Ask. Model: `MANAS_MODEL` (default `claude-opus-5-5`), effort: `MANAS_EFFORT` (default `medium`). All text is pseudonymised before it is sent (`backend/app/privacy.py`).

### Upload your own data

Open **Upload data** in the app (`/data`). Pick the goal pack, then for each file (customers, loans, payments, promises, communications, or subscriptions and usage) download the template or upload your own: CSV (comma, semicolon, tab, pipe), Excel `.xlsx`, JSON or NDJSON, with your own column names and DD/MM/YYYY dates. Each upload returns a report: rows loaded, rows skipped with the reason, matched and unrecognised columns. Then press **Build brains and decide**.

API: `GET /api/ingest/schema?pack=...`, `GET /api/ingest/template/{source}`, `POST /api/ingest/{source}` (multipart `file`, `mode` = append or replace, `pack`), `POST /api/data/reset` with `{"confirm": true}`.

### Tests

```powershell
cd backend; uv run pytest -q
```

## Licences of the reference projects

MiroFish is AGPL-3.0 and BettaFish is GPL-2.0. No code was copied from either; only the ideas (persona agents and simulation from MiroFish, the multi-agent forum from BettaFish) were re-implemented. Copying their code into a closed SaaS would oblige you to open-source the service.

## MCP, Mixpanel / PostHog and delivery planning

**MCP server.** `backend/app/mcp_server.py` exposes the brains to Claude or any MCP client: `list_users`, `get_user_brain`, `get_next_action`, `decide_now`, `explain_decision`, `ask_brain`, `ingest_events`, `sync_analytics`, `push_decisions`, `rebuild_and_decide`, `messaging_platforms`. Claude Code picks up `.mcp.json` in the repo root. For Claude Desktop, add the same block with the full path to `backend`:

```json
{"mcpServers": {"manas": {"command": "uv", "args": ["run", "--directory", "backend", "python", "-m", "app.mcp_server"]}}}
```

Tools never return phone numbers. On Windows, keep the repo in a short path (for example `C:\\code\\manas`): very long paths break a native dependency of the MCP SDK.

**Events in.** `POST /api/collect/{mixpanel|posthog|generic}` takes live events (one or a batch) in each vendor's own shape, maps their names (for example `payment_failed` to `abandoned_checkout`, `$pageview` to `viewed_screen`) and stores them. Set `MANAS_COLLECT_SECRET` to require an `X-Manas-Secret` header. `POST /api/integrations/{mixpanel|posthog}/sync` pulls recent raw events (Mixpanel Raw Event Export, PostHog HogQL query API). Override names with `MANAS_EVENT_MAP_JSON`.

**Decisions out.** `POST /api/integrations/{mixpanel|posthog}/push` writes each user's next action as `manas_*` user properties plus a `manas_decision` event (Mixpanel `/engage` + `/track`, PostHog `/batch/`). Never pushed: phone numbers, amounts owed, dispute or hardship signals or anything read from notes and replies.

Env vars: `MIXPANEL_PROJECT_ID`, `MIXPANEL_SERVICE_USER`, `MIXPANEL_SERVICE_SECRET`, `MIXPANEL_TOKEN`, `MIXPANEL_REGION` (`us`, `eu` or `in`; India projects use `data-in` / `api-in` hosts), `POSTHOG_HOST`, `POSTHOG_INGEST_HOST`, `POSTHOG_PROJECT_ID`, `POSTHOG_PERSONAL_API_KEY`, `POSTHOG_PROJECT_API_KEY`. Without them every sync and push is a dry run that returns the exact request.

**Channel, platform, language and message.** `backend/app/messaging.py` turns each decision into a delivery plan: the platform for the channel (WhatsApp Cloud API, Gupshup, Twilio, MSG91, Kaleyra, FCM, OneSignal, CleverTap, in-app inbox, Exotel, SendGrid), chosen by configured credentials, your measured delivery rate per platform and cost; a same-channel backup and a fallback channel; the language from the profile and the script from how the person actually writes (Devanagari Hindi, Hinglish in Roman letters, English); and the copy in each channel's shape (WhatsApp template name and language, SMS encoding, segments and DLT id, push title and body, in-app card). Hindi and Hinglish templates are built in; other languages fall back to the nearest template and are translated by Claude when it is on. Platform costs are illustrative: override the list with `MANAS_PROVIDERS_JSON`. Nothing is sent: the plan includes the request a sender would make.

## Not done yet

- Real message sending (WhatsApp Cloud API, SMS, voice): decisions are produced, nothing is sent.
- Templates are English only; Claude can translate when enabled.
- SQLite is fine for a demo; move to Postgres for production.
- Outcome numbers on the dashboard are simulated and labelled so.
