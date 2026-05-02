# TradingBot 🤖📈

An AI-powered stock trading assistant that runs daily market analysis using the 
[TradingAgents](https://github.com/TauricResearch/TradingAgents) multi-agent LLM 
framework and delivers results – and interactive queries – via **WhatsApp**.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        TradingBot                        │
│                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────┐  │
│  │  APScheduler │    │   FastAPI    │    │  SQLite   │  │
│  │  (daily job) │    │  (webhook)   │    │    DB     │  │
│  └──────┬───────┘    └──────┬───────┘    └───────────┘  │
│         │                  │                             │
│  ┌──────▼──────────────────▼──────┐                     │
│  │       Command Handler          │                     │
│  └──────────────┬─────────────────┘                     │
│                 │                                        │
│  ┌──────────────▼─────────────────┐                     │
│  │   TradingAgents Service        │                     │
│  │  (ThreadPoolExecutor wrapper)  │                     │
│  └──────────────┬─────────────────┘                     │
│                 │                                        │
│  ┌──────────────▼─────────────────┐                     │
│  │  TradingAgentsGraph.propagate()│  ← LangGraph agents │
│  │  Analyst · Researcher · Trader │                     │
│  │  Risk Manager · Portfolio Mgr  │                     │
│  └───────────────────────────────┘                     │
└─────────────────────────────────────────────────────────┘
         │                          │
   WhatsApp push              WhatsApp replies
   (Twilio client)            (Twilio client)
```

### Key design decisions

| Concern | Choice | Rationale |
|---|---|---|
| Web framework | FastAPI | Async-native, BackgroundTasks, auto-docs |
| Scheduling | APScheduler `AsyncIOScheduler` | In-process, cron trigger, survives reschedule commands |
| Agent execution | `ThreadPoolExecutor` | TradingAgents is synchronous; pool prevents event-loop blocking |
| Concurrency guard | `asyncio.Semaphore` | Caps parallel LLM calls to protect API quota |
| Database | SQLite + SQLAlchemy | Zero-ops for a single-user bot; swap for Postgres in production |
| WhatsApp | Twilio | Reliable, well-documented Python SDK |
| Config | Pydantic-settings | Type-safe, `.env` + env-var override, no secrets in code |

---

## Features

- **Daily push** – At a configurable time (default 12:00 UTC) the bot analyses every
  stock on your watchlist and sends a WhatsApp card + digest summary.
- **On-demand analysis** – Message `analyze NVDA` anytime.
- **Watchlist management** – `add`, `remove`, `list` commands via WhatsApp.
- **Persistent results** – Every analysis is stored in SQLite so you can query the
  latest report without re-running the agents.
- **Rescheduling** – Change the daily analysis time with `schedule 14:30` without
  restarting the bot.
- **Secure webhook** – All inbound Twilio requests are validated via signature to
  prevent spoofing.

---

## WhatsApp Commands

| Command | Description |
|---|---|
| `help` | Show all commands |
| `list` | Show current watchlist |
| `add TICKER` | Add a stock (e.g. `add TSLA`) |
| `remove TICKER` | Remove a stock |
| `analyze TICKER` | Run analysis now for today |
| `analyze TICKER YYYY-MM-DD` | Run analysis for a specific date |
| `report` | Show the latest cached results for all watchlist stocks |
| `schedule HH:MM` | Change the daily analysis time (UTC) |
| `next` | Show when the next daily run is scheduled |
| `status` | Bot health summary |

---

## Prerequisites

| Service | Purpose | Free tier available |
|---|---|---|
| [Twilio](https://www.twilio.com) | WhatsApp messaging | ✅ Sandbox |
| OpenAI / Gemini / Anthropic / … | LLM backbone | ✅ varies |
| [Alpha Vantage](https://www.alphavantage.co) | Fundamental data | ✅ 25 req/day |

---

## Setup

### 1. Clone & configure

```bash
git clone <this-repo>
cd tradingbot
cp .env.example .env
```

Edit `.env` and fill in:

- `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_WHATSAPP_FROM`
- At least one LLM API key (`OPENAI_API_KEY`, `GOOGLE_API_KEY`, …)
- `ALPHA_VANTAGE_API_KEY` (for fundamental data)
- `AUTHORIZED_NUMBERS` – your WhatsApp number with country code (e.g. `+12025551234`)

### 2. Twilio WhatsApp sandbox

1. In the Twilio Console → Messaging → Try it out → Send a WhatsApp message.
2. Follow the sandbox join instructions (send a one-time code from your phone).
3. Set the **"When a message comes in"** webhook URL to:
   ```
   https://<your-public-host>/api/webhook/whatsapp
   ```
   Method: `HTTP POST`

> **Local development** – use [ngrok](https://ngrok.com) to create a public tunnel:
> ```bash
> ngrok http 8000
> # copy the https://xxxx.ngrok.io URL into Twilio's webhook field
> ```

### 3a. Run locally (venv)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload      # or:  python -m app.main
```

### 3b. Run with Docker

```bash
docker compose up --build
```

The SQLite database is mounted to `./data/` so it persists across container restarts.

---

## Configuration reference

All settings can be overridden via environment variables or `.env`.

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` · `google` · `anthropic` · `xai` · `openrouter` · `ollama` |
| `DEEP_THINK_LLM` | `gpt-4o` | Model for complex reasoning (analyst/researcher agents) |
| `QUICK_THINK_LLM` | `gpt-4o-mini` | Model for simple tasks |
| `MAX_DEBATE_ROUNDS` | `1` | Bull/bear researcher debate rounds (higher = better, slower) |
| `ANALYSIS_TIME` | `12:00` | Daily cron time in HH:MM (UTC) |
| `ANALYSIS_TIMEZONE` | `UTC` | Timezone for the cron trigger |
| `MAX_CONCURRENT_ANALYSES` | `2` | Max parallel TradingAgents runs |
| `DEFAULT_WATCHLIST` | `AAPL,MSFT,NVDA,GOOGL` | Seeded once on first startup |
| `AUTHORIZED_NUMBERS` | _(empty = open)_ | Comma-separated E.164 numbers allowed to use the bot |
| `DEBUG` | `false` | Enables verbose logging + Swagger UI at `/docs` |

---

## Project structure

```
tradingbot/
├── app/
│   ├── main.py                     # FastAPI app factory + lifespan
│   ├── config.py                   # Pydantic-settings
│   ├── db/
│   │   ├── models.py               # SQLAlchemy ORM models
│   │   └── session.py              # Engine, session factory, CRUD helpers
│   ├── services/
│   │   ├── trading_agent.py        # Async wrapper for TradingAgentsGraph
│   │   ├── whatsapp.py             # Twilio client + message formatters
│   │   └── scheduler.py            # APScheduler daily job
│   ├── handlers/
│   │   └── command_handler.py      # WhatsApp command router
│   └── api/
│       └── webhook.py              # POST /api/webhook/whatsapp
├── data/                           # SQLite DB lives here (git-ignored)
├── .env.example
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## Disclaimer

This bot is for **research and informational purposes only**. It does not constitute
financial, investment, or trading advice. Always do your own research before making
any investment decisions. The underlying TradingAgents framework is subject to the
same disclaimer by Tauric Research.
