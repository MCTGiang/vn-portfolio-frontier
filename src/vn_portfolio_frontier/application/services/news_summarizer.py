"""Stub for Phase A - F1-only live tracking. Real impl Sprint 13."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TickerSummary:
    ticker: str
    action: str = "N_A"
    confidence: float = 0.0
    n_articles: int = 0
    event_types: list = field(default_factory=list)
    sentiment_score: float = 0.0
    rationale: str = ""
    sources: list = field(default_factory=list)
    price_now: float = 0.0


class ClaudeNewsSummarizer:
    """Phase A stub returning empty dict (F1-only tracking).
    Full Claude integration deferred to Sprint 13 Day 2+."""

    def __init__(self, api_key: str, model_id: str = "claude-sonnet-5-5-20260801"):
        self._api_key = api_key
        self._model_id = model_id

    def summarize_by_ticker(self, tickers, date_range):
        return {}
