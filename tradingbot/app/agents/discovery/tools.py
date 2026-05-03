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


def get_technical_snapshot(ticker: str, period: str = "6mo") -> Optional[dict]:
    """Return current price and indicator levels for entry/exit decisions."""
    try:
        data = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        if data.empty:
            return None

        close = data["Close"]
        high = data["High"]
        low = data["Low"]

        if hasattr(close, "squeeze"):
            close = close.squeeze()
        if hasattr(high, "squeeze"):
            high = high.squeeze()
        if hasattr(low, "squeeze"):
            low = low.squeeze()

        if len(close) < 20:
            return None

        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(50).mean() if len(close) >= 50 else None

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi_series = 100 - (100 / (1 + rs))

        tr_components = pd.concat(
            [
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ],
            axis=1,
        )
        atr14 = tr_components.max(axis=1).rolling(14).mean()

        current_close = float(close.iloc[-1])
        prev_close = float(close.iloc[-2]) if len(close) > 1 else current_close
        current_sma20 = float(sma20.iloc[-1])
        current_sma50 = float(sma50.iloc[-1]) if sma50 is not None and not pd.isna(sma50.iloc[-1]) else None
        rsi14 = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None
        atr_value = float(atr14.iloc[-1]) if not pd.isna(atr14.iloc[-1]) else None

        support_20d = float(low.tail(20).min())
        resistance_20d = float(high.tail(20).max())
        pct_from_sma20 = ((current_close / current_sma20) - 1) * 100
        day_change_pct = ((current_close - prev_close) / prev_close) * 100 if prev_close else 0.0

        return {
            "ticker": ticker,
            "current_price": round(current_close, 2),
            "previous_close": round(prev_close, 2),
            "day_change_pct": round(day_change_pct, 2),
            "sma20": round(current_sma20, 2),
            "sma50": round(current_sma50, 2) if current_sma50 is not None else None,
            "rsi14": round(rsi14, 1) if rsi14 is not None else None,
            "atr14": round(atr_value, 2) if atr_value is not None else None,
            "support_20d": round(support_20d, 2),
            "resistance_20d": round(resistance_20d, 2),
            "pct_from_sma20": round(pct_from_sma20, 2),
            "entry_watch_price": round(current_sma20, 2),
            "entry_zone_low": round(current_sma20 * 0.995, 2),
            "entry_zone_high": round(current_sma20 * 1.005, 2),
        }
    except Exception as exc:
        logger.debug("get_technical_snapshot(%s) failed: %s", ticker, exc)
        return None


def detect_breakout(ticker: str, date: str | None = None) -> Optional[dict]:
    """Return breakout signal dict if ticker meets technical criteria, else None."""
    snapshot = get_technical_snapshot(ticker, period="6mo")
    if not snapshot:
        return None

    current_close = snapshot["current_price"]
    current_sma20 = snapshot["sma20"]
    rsi = snapshot["rsi14"]

    signals = []
    if current_close > current_sma20 * 1.015:
        signals.append("above_sma20")
    if rsi is not None and rsi < 35:
        signals.append("oversold_bounce")
    elif rsi is not None and rsi > 65:
        signals.append("momentum_strong")

    if not signals:
        return None

    return {
        "ticker": ticker,
        "signals": signals,
        "rsi": rsi,
        "signal": "technical_setup",
        "current_price": current_close,
        "sma20": current_sma20,
        "entry_watch_price": snapshot["entry_watch_price"],
        "entry_zone_low": snapshot["entry_zone_low"],
        "entry_zone_high": snapshot["entry_zone_high"],
        "support_20d": snapshot["support_20d"],
        "resistance_20d": snapshot["resistance_20d"],
    }
