# Project Doom

**Autonomous geopolitical & financial risk intelligence platform.**

Project Doom is an executive-grade adversarial threat simulator. It runs a multi-agent
"Fracture Swarm" tribunal that stress-tests company valuations against chaos scenarios —
export controls, geopolitical flashpoints, supply-chain shocks — and surfaces IC-ready
verdicts with a human review gate. An autonomous watchtower scans your watchlist on a
schedule and emails you the moment a risk crosses your threshold.

> Built for the India Runs (RedRob) hackathon — Track 2, "AI Systems Architect."

---

## What it does

1. **Dynamic grounding** — resolves any ticker (live `yfinance`), pulls macro state
   (VIX, Brent, gold, 10Y, fear regime), and synthesizes grounded risk vectors.
2. **Fracture Swarm tribunal** — adversarial Bull vs. Bear advocates, moderated by a
   Black Swan Judge, debate each risk and return a severity verdict.
3. **Stressed valuation waterfall** — a multi-model engine (DCF / EV-Revenue / P-BV /
   normalized-EBITDA by company type) computes a base fair value and a distressed value
   under the chaos coefficient, rendered as a waterfall bridge.
4. **Geopolitical threat map** — risks are geolocated and drawn as convergence arcs onto
   the asset's HQ.
5. **Autonomous watchtower** — subscribe an email + watchlist; a scheduled job scans for
   breaches and alerts you, with the full tribunal a click away.

---

## Architecture

```
public/                 Single-page cockpit (vanilla JS + Plotly, no framework)
  index.html / .css / .js
api/
  index.py              FastAPI app — all routes + market/valuation helpers
  app_helpers.py        Shared dataclasses, DoomsdayAI (Gemini→NVIDIA→Fireworks), fallbacks
  store.py              Subscription store — Upstash Redis (REST) + local-file fallback
  notify.py             Email — Resend (HTTP) + console-log fallback, HTML templates
agent_swarm.py          Fracture Swarm orchestration (adversarial tribunal)
valuation_engine.py     Multi-model valuation library
arize_mcp_client.py     OTLP telemetry tracing (Arize Phoenix)
elastic_mcp_client.py   Risk-vector grounding
```

Deployed as Vercel Python serverless functions; the frontend is served statically. No
database is required for the core app — alert subscriptions live in Upstash Redis.

The app **degrades gracefully**: with no API keys it runs entirely on built-in fallbacks
(deterministic risk engine, local-file subscription store, emails logged to the console).

---

## Quickstart (local)

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in at least one LLM key (optional — runs without)
python -m uvicorn api.index:app --reload --port 8000
# open http://localhost:8000
```

---

## Environment variables

See [`.env.example`](.env.example). At minimum, one LLM key (`GOOGLE_API_KEY`,
`NVIDIA_API_KEY`, or `FIREWORKS_API_KEY`) enables the live swarm; without one the app uses
its fallback engine. The alert system additionally uses `RESEND_API_KEY` (email) and
`KV_REST_API_URL` / `KV_REST_API_TOKEN` (Upstash Redis).

---

## Deploy to Vercel

Standard import-and-deploy (framework preset: **Other**). Then, for the **alert system**:

1. **Storage** → Marketplace → **Upstash for Redis** → create & connect. This injects
   `KV_REST_API_URL` and `KV_REST_API_TOKEN` automatically.
2. Add **`RESEND_API_KEY`** (and optionally `ALERT_FROM_EMAIL`, `CRON_SECRET`) plus your
   LLM keys as project environment variables.
3. The daily watchtower cron is declared in `vercel.json` (`/api/cron_scan`) and registers
   automatically on deploy.

---

## Partner integrations

NVIDIA NIM (Llama 3.3 70B) · Google Gemini · Tavily (live news grounding) ·
Arize Phoenix (telemetry) · Resend (email) · Upstash Redis (subscriptions) · yfinance.

---

*Human oversight is a first-class feature, not an afterthought.*
