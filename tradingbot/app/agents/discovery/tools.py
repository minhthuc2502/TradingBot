from __future__ import annotations

import io
import logging
from typing import List, Optional

import pandas as pd
import requests
import yfinance as yf

from app.config import settings

logger = logging.getLogger(__name__)

_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
_HEADERS = {"User-Agent": "Mozilla/5.0 (TradingBot/1.0; research use)"}

_universe_cache: dict[str, List[str]] = {}


def _read_html_wiki(url: str) -> list:
    """Fetch Wikipedia page with a browser User-Agent and parse tables."""
    resp = requests.get(url, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text))


def load_universe() -> List[str]:
    """Load the configured stock universe (S&P500, NASDAQ100, or custom list)."""
    universe_type = settings.discovery_universe.lower()

    if universe_type in _universe_cache:
        return _universe_cache[universe_type]

    if universe_type == "custom":
        result = settings.discovery_custom_universe_list or []
    elif universe_type == "nasdaq100":
        try:
            tables = _read_html_wiki(_NASDAQ100_URL)
            result = tables[3]["Ticker"].tolist()
        except Exception as exc:
            logger.warning("Failed to load NASDAQ100 universe: %s", exc)
            result = []
    else:  # default: sp500
        try:
            tables = _read_html_wiki(_SP500_URL)
            result = tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
        except Exception as exc:
            logger.warning("Failed to load S&P500 universe: %s", exc)
            result = []

    _universe_cache[universe_type] = result
    logger.info("Loaded %d tickers for universe '%s'", len(result), universe_type)
    return result


def screen_volume_anomalies(
    universe: List[str],
    threshold: float = 2.0,
    date: str | None = None,
) -> List[dict]:
    """Return tickers where today's volume > threshold × 30-day average."""
    if not universe:
        return []
    try:
        data = yf.download(universe, period="31d", progress=False, auto_adjust=True)
        volume: pd.DataFrame = data["Volume"]

        if isinstance(volume, pd.Series):
            volume = volume.to_frame(name=universe[0])

        avg_30d = volume.iloc[:-1].mean()
        today_vol = volume.iloc[-1]
        ratio = (today_vol / avg_30d).dropna()
        flagged = ratio[ratio >= threshold].sort_values(ascending=False)

        return [
            {
                "ticker": str(ticker),
                "volume_ratio": float(ratio_val),
                "signal": "volume_spike",
            }
            for ticker, ratio_val in flagged.items()
        ]
    except Exception as exc:
        logger.warning("screen_volume_anomalies failed: %s", exc)
        return []


def get_news_active_tickers(
    universe: List[str],
    sample_size: int = 80,
    min_articles: int = 2,
) -> List[dict]:
    """Return tickers with recent news activity (proxy for trending)."""
    sample = universe[:sample_size]
    results = []
    for ticker in sample:
        try:
            news = yf.Ticker(ticker).news or []
            if len(news) >= min_articles:
                results.append({
                    "ticker": ticker,
                    "news_count": len(news),
                    "signal": "news_active",
                })
        except Exception:
            continue
    return sorted(results, key=lambda x: x["news_count"], reverse=True)[:30]


def detect_breakout(ticker: str, date: str | None = None) -> Optional[dict]:
    """Return breakout signal dict if ticker meets technical criteria, else None."""
    try:
        data = yf.download(ticker, period="60d", progress=False, auto_adjust=True)
        close = data["Close"]
        if hasattr(close, "squeeze"):
            close = close.squeeze()
        if len(close) < 20:
            return None

        sma20 = close.rolling(20).mean()
        current_close = float(close.iloc[-1])
        current_sma20 = float(sma20.iloc[-1])

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        rsi = float((100 - (100 / (1 + rs))).iloc[-1])

        signals = []
        if current_close > current_sma20 * 1.015:
            signals.append("above_sma20")
        if rsi < 35:
            signals.append("oversold_bounce")
        elif rsi > 65:
            signals.append("momentum_strong")

        if not signals:
            return None

        return {"ticker": ticker, "signals": signals, "rsi": round(rsi, 1), "signal": "technical_setup"}
    except Exception as exc:
        logger.debug("detect_breakout(%s) failed: %s", ticker, exc)
        return None
