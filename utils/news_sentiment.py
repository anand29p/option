# utils/news_sentiment.py
# ─────────────────────────────────────────────────────────────────────────────
# Indian Market News Sentiment
#
# Sources (all FREE, no API key needed):
#   • Economic Times Markets RSS
#   • Moneycontrol Market Reports RSS
#   • Business Standard Markets RSS
#   • NSE India Press Releases RSS
#
# Sentiment engine: VADER (NLTK) — offline, runs locally, no LLM needed.
# Financial keyword boosting: keywords like "rally", "crash", "surge" weighted.
#
# Optional upgrade: Set ALPHA_VANTAGE_KEY in .env for their News Sentiment API
#   (25 free req/day → better accuracy on Indian stocks)
# ─────────────────────────────────────────────────────────────────────────────

import os
import time
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import feedparser
from loguru import logger

from config.settings import IST

# ── RSS Feeds (free, no auth) ────────────────────────────────────────────────
RSS_FEEDS = {
    "ET Markets":         "https://economictimes.indiatimes.com/markets/rss.cms",
    "Moneycontrol":       "https://www.moneycontrol.com/rss/marketreports.xml",
    "Business Standard":  "https://www.business-standard.com/rss/markets-106.rss",
    "NSE India":          "https://www.nseindia.com/api/rss",
}

# ── Financial keyword sentiment boosters ─────────────────────────────────────
BULLISH_KEYWORDS = {
    "rally", "surge", "gain", "bull", "bullish", "breakout", "uptrend",
    "recovery", "positive", "outperform", "buy", "upgrade", "strong",
    "record high", "all-time high", "beat estimates", "better than expected",
}
BEARISH_KEYWORDS = {
    "crash", "fall", "drop", "bear", "bearish", "selloff", "sell-off",
    "breakdown", "downtrend", "negative", "underperform", "sell", "downgrade",
    "weak", "record low", "miss estimates", "worse than expected", "recession",
    "rate hike", "inflation", "concern", "risk", "volatility spike",
}


@dataclass
class SentimentScore:
    """Aggregated market sentiment from news headlines."""
    timestamp:   datetime     = field(default_factory=lambda: datetime.now(IST))
    score:       float        = 0.0    # -1.0 (very bearish) to +1.0 (very bullish)
    label:       str          = "NEUTRAL"   # BULLISH | BEARISH | NEUTRAL
    confidence:  float        = 0.0   # 0-1 (how many headlines agree)
    headline_count: int       = 0
    top_headlines: list       = field(default_factory=list)   # Top 5 headlines

    def to_dict(self) -> dict:
        return {
            "timestamp":      self.timestamp.strftime("%H:%M IST"),
            "score":          round(self.score, 3),
            "label":          self.label,
            "confidence":     round(self.confidence, 2),
            "headline_count": self.headline_count,
            "top_headlines":  self.top_headlines[:5],
        }


class NewsSentimentAnalyzer:
    """
    Fetches Indian financial news and computes a market sentiment score.
    Uses VADER + keyword boosting (no API key needed, fully offline).
    Caches results to avoid hammering RSS feeds.
    """

    def __init__(self, cache_minutes: int = 15):
        self._cache_minutes = cache_minutes
        self._cached:    Optional[SentimentScore] = None
        self._cached_at: Optional[datetime]       = None
        self._seen_ids:  set = set()   # Dedup headlines by hash

        # Lazy-load VADER (nltk download on first run)
        self._vader = None

    def _load_vader(self):
        if self._vader is not None:
            return
        try:
            from nltk.sentiment.vader import SentimentIntensityAnalyzer
            self._vader = SentimentIntensityAnalyzer()
        except LookupError:
            import nltk
            nltk.download("vader_lexicon", quiet=True)
            from nltk.sentiment.vader import SentimentIntensityAnalyzer
            self._vader = SentimentIntensityAnalyzer()

    def get_sentiment(self, force: bool = False) -> SentimentScore:
        """Return sentiment score (cached for cache_minutes, never raises)."""
        now = datetime.now(IST)
        if (not force
                and self._cached is not None
                and self._cached_at is not None
                and (now - self._cached_at).total_seconds() < self._cache_minutes * 60):
            return self._cached

        try:
            result = self._analyze()
            self._cached    = result
            self._cached_at = now
            logger.info(
                f"📰 Sentiment: {result.label} (score={result.score:+.2f} "
                f"confidence={result.confidence:.0%} n={result.headline_count})"
            )
            return result
        except Exception as e:
            logger.warning(f"News sentiment fetch failed: {e}")
            return self._cached or SentimentScore()

    def _analyze(self) -> SentimentScore:
        self._load_vader()

        headlines = self._fetch_headlines()
        if not headlines:
            return SentimentScore()

        scores     = []
        top_hl     = []
        seen_today = set()

        for hl in headlines:
            # Dedup
            h = hashlib.md5(hl.encode()).hexdigest()
            if h in seen_today:
                continue
            seen_today.add(h)

            vader_raw = self._vader.polarity_scores(hl)["compound"]
            boost     = self._keyword_boost(hl)
            final     = max(-1.0, min(1.0, vader_raw + boost))
            scores.append(final)
            top_hl.append({"headline": hl[:120], "score": round(final, 3)})

        if not scores:
            return SentimentScore()

        avg   = sum(scores) / len(scores)
        agree = sum(1 for s in scores if (s > 0.05) == (avg > 0.05))
        conf  = agree / len(scores)
        label = "BULLISH" if avg > 0.05 else ("BEARISH" if avg < -0.05 else "NEUTRAL")

        # Sort top headlines by absolute score
        top_hl.sort(key=lambda x: abs(x["score"]), reverse=True)

        return SentimentScore(
            score=round(avg, 3),
            label=label,
            confidence=round(conf, 3),
            headline_count=len(scores),
            top_headlines=top_hl[:5],
        )

    def _fetch_headlines(self) -> list[str]:
        import requests
        headlines = []
        for source, url in RSS_FEEDS.items():
            try:
                # Use requests to fetch with a strict timeout to prevent hanging
                resp = requests.get(url, timeout=5)
                feed = feedparser.parse(resp.content)
                for entry in feed.entries[:15]:
                    title = getattr(entry, "title", "")
                    if title:
                        headlines.append(title)
            except Exception as e:
                logger.debug(f"RSS fetch failed for {source}: {e}")
        return headlines

    def _keyword_boost(self, text: str, boost: float = 0.15) -> float:
        lower = text.lower()
        score = 0.0
        for kw in BULLISH_KEYWORDS:
            if kw in lower:
                score += boost
        for kw in BEARISH_KEYWORDS:
            if kw in lower:
                score -= boost
        return max(-0.5, min(0.5, score))


# Module-level singleton
_analyzer = NewsSentimentAnalyzer(cache_minutes=15)


def get_news_sentiment(force: bool = False) -> SentimentScore:
    """Convenience function — call this from strategies."""
    return _analyzer.get_sentiment(force=force)
