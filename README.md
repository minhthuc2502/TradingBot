# TradingBot

A personal AI trading assistant that discovers stocks, runs deep multi-agent analysis, and delivers results to Discord — with a natural language chatbot you can ask anything.

---

## The Idea

Most trading tools give you raw data and leave interpretation to you. TradingBot flips that: it runs a full team of AI analysts (market, news, fundamentals, bull/bear researchers, risk managers) on each stock — the same multi-agent pipeline as [TradingAgents](https://github.com/TauricResearch/TradingAgents) — and synthesises a clear BUY / HOLD / SELL decision with reasoning.

Three things it does:

1. **Daily scheduled analysis** — at a configured time it analyses your watchlist (and optionally auto-discovers trending stocks) and posts rich embed cards to Discord.
2. **Stock discovery** — screens S&P 500 or NASDAQ 100 for volume spikes, news activity, and technical breakouts to surface opportunities you might miss.
3. **Natural language chatbot** — ask anything in Discord: *"Should I buy NVIDIA?"*, *"What's trending on NASDAQ today?"*, *"Analyse the technicals for Amazon"*. The bot maintains per-user conversation history so follow-up questions work naturally.

---

## How to Run

### 1. Prerequisites

- Python 3.11+
- A [Google AI Studio](https://aistudio.google.com/) API key (Gemini 2.5 Pro)
- A Discord bot token ([Discord Developer Portal](https://discord.com/developers/applications))
- *(Optional)* Twilio account for WhatsApp notifications

### 2. Clone and install

```bash
git clone <this-repo>
cd TradingBot

# Install TradingAgents (required dependency)
pip install -e TradingAgents/

# Install bot dependencies
pip install -r tradingbot/requirements.txt
```

### 3. Configure

Copy the example env file and fill in your keys:

```bash
cp .env.example tradingbot/.env
```

Key variables:

```env
# LLM — required
GOOGLE_API_KEY=your_gemini_key
ANALYSIS_MODEL=gemini-2.5-pro        # or gemini-2.0-flash for lower cost

# Discord — required for chatbot
DISCORD_BOT_TOKEN=your_bot_token
DISCORD_CHANNEL_ID=123456789         # channel for daily broadcast
DISCORD_AUTHORIZED_USER_IDS=111,222  # leave empty to allow all users

# Watchlist (seeded on first run)
DEFAULT_WATCHLIST=AAPL,MSFT,NVDA,GOOGL

# Daily analysis time (UTC)
ANALYSIS_TIME=12:00

# Stock discovery (optional)
DISCOVERY_ENABLED=false
DISCOVERY_UNIVERSE=sp500             # sp500 | nasdaq100 | custom
DISCOVERY_MAX_TICKERS=10

# WhatsApp (optional)
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
AUTHORIZED_NUMBERS=+12025551234
```

### 4. Discord bot setup

In the [Discord Developer Portal](https://discord.com/developers/applications):
1. Create an application → Bot
2. Enable **Message Content Intent** under Privileged Gateway Intents
3. Invite with scopes: `bot` + permissions: `Send Messages`, `Read Message History`, `View Channels`

### 5. Run

```bash
cd tradingbot
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Or with auto-reload during development:

```bash
DEBUG=true uvicorn app.main:app --reload
```

---

## Acknowledgements

Built on top of [TradingAgents](https://github.com/TauricResearch/TradingAgents) by Tauric Research — the multi-agent financial analysis framework that powers the core analysis pipeline.
