from __future__ import annotations

from typing import List, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "TradingBot"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str = "sqlite:///./data/tradingbot.db"

    # LLM Provider settings
    llm_provider: str = "openai"
    deep_think_llm: str = "gpt-4o"
    quick_think_llm: str = "gpt-4o-mini"
    analysis_model: str = "gemini-2.5-pro"   # single model used for all analysis runs
    max_debate_rounds: int = 1
    online_tools: bool = True

    # LLM API Keys (set at least one)
    openai_api_key: str = ""
    google_api_key: str = ""
    anthropic_api_key: str = ""
    xai_api_key: str = ""
    alpha_vantage_api_key: str = ""

    # Twilio WhatsApp
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"  # Twilio sandbox default

    # Comma-separated authorized WhatsApp numbers (include country code, e.g. +12025551234)
    # Leave empty to allow all numbers – NOT recommended for production.
    authorized_numbers: str = ""

    # Discord bot
    discord_bot_token: str = ""
    discord_channel_id: int = 0  # channel ID for broadcast notifications
    # Comma-separated Discord user IDs allowed to send commands; empty = allow all
    discord_authorized_user_ids: str = ""

    # Scheduler (24h HH:MM, UTC by default)
    analysis_time: str = "12:00"
    analysis_timezone: str = "UTC"

    # Default watchlist (comma-separated tickers, seeded on first run)
    default_watchlist: str = "AAPL,MSFT,NVDA,GOOGL"

    # Max concurrent stock analyses (LLM API quota guard)
    max_concurrent_analyses: int = 2

    # Discovery
    discovery_enabled: bool = False
    discovery_universe: Literal["sp500", "nasdaq100", "custom"] = "sp500"
    discovery_custom_universe: str = ""         # comma-separated tickers if custom
    discovery_max_tickers: int = 10             # max auto-discovered per day
    discovery_time: str = "23:00"              # UTC HH:MM — runs evening before analysis

    @property
    def discovery_custom_universe_list(self) -> List[str]:
        if not self.discovery_custom_universe:
            return []
        return [t.strip().upper() for t in self.discovery_custom_universe.split(",") if t.strip()]

    @property
    def authorized_number_list(self) -> List[str]:
        if not self.authorized_numbers:
            return []
        return [n.strip() for n in self.authorized_numbers.split(",") if n.strip()]

    @property
    def discord_authorized_user_id_list(self) -> List[str]:
        if not self.discord_authorized_user_ids:
            return []
        return [u.strip() for u in self.discord_authorized_user_ids.split(",") if u.strip()]

    @property
    def default_watchlist_list(self) -> List[str]:
        if not self.default_watchlist:
            return []
        return [t.strip().upper() for t in self.default_watchlist.split(",") if t.strip()]


settings = Settings()
