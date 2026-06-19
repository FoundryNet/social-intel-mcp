"""Free social-trends sources + light enrichment.

Trending topics / viral content / community pulse from:
  - Reddit public JSON endpoints (reddit.com/r/<sub>/hot.json, /search.json) — keyless,
    polite User-Agent.
  - Hacker News Firebase API (topstories/newstories/item) — keyless. HN Algolia search
    for keyword/brand lookups.
  - Google Trends via pytrends — OPTIONAL: imported lazily inside a try/except so a
    missing pytrends package (or GOOGLE_TRENDS_ENABLED=false) degrades gracefully.
  - Twitter/X public trends — best-effort; degrades to [] when unavailable.

Sentiment is a deterministic lexicon heuristic (no paid LLM). All async via
request_json; defensive — every source returns [] rather than raising.
"""
from __future__ import annotations

import logging
import re
from collections import Counter

import config
from http_util import request_json

logger = logging.getLogger("social.src")

_UA = {"User-Agent": config.REDDIT_USER_AGENT}

# ── pytrends is optional ──────────────────────────────────────────────────────
# Import lazily so the module (and `import server`) works even when pytrends isn't
# installed. _PYTRENDS_AVAILABLE gates the Google Trends source.
_PYTRENDS_AVAILABLE = False
_TrendReq = None
if config.GOOGLE_TRENDS_ENABLED:
    try:
        from pytrends.request import TrendReq as _TrendReq  # type: ignore
        _PYTRENDS_AVAILABLE = True
    except Exception as e:  # noqa: BLE001 — missing dep / version skew → feature off
        logger.info(f"pytrends unavailable — Google Trends source disabled: {e}")
        _PYTRENDS_AVAILABLE = False


def google_trends_available() -> bool:
    return bool(config.GOOGLE_TRENDS_ENABLED and _PYTRENDS_AVAILABLE)


# ── sentiment (deterministic lexicon heuristic — no LLM) ─────────────────────
_POS = {
    "good", "great", "love", "loved", "awesome", "amazing", "excellent", "best",
    "win", "wins", "winning", "happy", "excited", "exciting", "incredible", "huge",
    "bullish", "breakthrough", "success", "successful", "impressive", "beautiful",
    "perfect", "wonderful", "fantastic", "brilliant", "gain", "gains", "up", "boom",
    "strong", "solid", "promising", "innovative", "helpful", "recommend", "fun",
}
_NEG = {
    "bad", "worse", "worst", "hate", "hated", "terrible", "awful", "broken", "bug",
    "fail", "failed", "failure", "crash", "scam", "fraud", "angry", "sad", "fear",
    "bearish", "crash", "dump", "decline", "down", "loss", "losses", "lawsuit",
    "ban", "banned", "outage", "disappointing", "disappointed", "useless", "wrong",
    "concern", "concerned", "problem", "issue", "issues", "risk", "warning", "weak",
}
_WORD_RE = re.compile(r"[a-z']+")


def score_sentiment(text: str) -> float:
    """Return a sentiment score in [-1, 1] from a token lexicon. Deterministic."""
    if not text:
        return 0.0
    words = _WORD_RE.findall(text.lower())
    if not words:
        return 0.0
    pos = sum(1 for w in words if w in _POS)
    neg = sum(1 for w in words if w in _NEG)
    if pos + neg == 0:
        return 0.0
    return round((pos - neg) / (pos + neg), 4)


def sentiment_label(score: float) -> str:
    if score > 0.15:
        return "positive"
    if score < -0.15:
        return "negative"
    return "neutral"


def _velocity(score, comments, age_hours) -> float:
    """A simple traction/velocity score: engagement per hour since posting."""
    age = max(float(age_hours or 0), 0.5)
    engagement = float(score or 0) + 2.0 * float(comments or 0)
    return round(engagement / age, 3)


# ── Reddit (public JSON) ──────────────────────────────────────────────────────
async def reddit_hot(subreddit: str, limit: int = 25) -> list:
    """Hot posts for a subreddit via the public .json endpoint."""
    url = f"{config.REDDIT_API}/r/{subreddit.strip().lstrip('r/')}/hot.json"
    r = await request_json("GET", url, headers=_UA, params={"limit": str(limit), "raw_json": "1"},
                           timeout=config.REQUEST_TIMEOUT)
    return _map_reddit(r, subreddit)


async def reddit_search(query: str, limit: int = 25, sort: str = "relevance",
                        time_filter: str = "week") -> list:
    url = f"{config.REDDIT_API}/search.json"
    r = await request_json("GET", url, headers=_UA,
                           params={"q": query, "limit": str(limit), "sort": sort,
                                   "t": time_filter, "raw_json": "1"},
                           timeout=config.REQUEST_TIMEOUT)
    return _map_reddit(r, None)


def _map_reddit(r, subreddit) -> list:
    import time as _t
    now = _t.time()
    rows = []
    children = ((r or {}).get("data") or {}).get("children") if isinstance(r, dict) else None
    for c in (children or []):
        d = c.get("data") or {}
        created = d.get("created_utc") or 0
        age_h = max((now - float(created)) / 3600.0, 0.1) if created else None
        score = d.get("score")
        comments = d.get("num_comments")
        title = d.get("title") or ""
        rows.append({
            "platform": "reddit",
            "source_id": f"reddit:{d.get('id')}",
            "title": title,
            "url": f"https://reddit.com{d.get('permalink')}" if d.get("permalink") else d.get("url"),
            "community": f"r/{d.get('subreddit') or subreddit}",
            "score": score,
            "comments": comments,
            "created_utc": created,
            "age_hours": round(age_h, 2) if age_h is not None else None,
            "velocity": _velocity(score, comments, age_h),
            "sentiment": score_sentiment(title),
        })
    return rows


# ── Hacker News (Firebase + Algolia) ──────────────────────────────────────────
async def hn_top(limit: int = 30, kind: str = "topstories") -> list:
    """Top/new HN stories via the Firebase API (keyless)."""
    ids = await request_json("GET", f"{config.HN_API}/{kind}.json", headers=_UA,
                             timeout=config.REQUEST_TIMEOUT)
    if not isinstance(ids, list):
        return []
    import asyncio
    import time as _t
    now = _t.time()
    sem = asyncio.Semaphore(8)

    async def _item(i):
        async with sem:
            it = await request_json("GET", f"{config.HN_API}/item/{i}.json", headers=_UA,
                                    timeout=config.REQUEST_TIMEOUT)
        if not isinstance(it, dict) or it.get("type") != "story":
            return None
        created = it.get("time") or 0
        age_h = max((now - float(created)) / 3600.0, 0.1) if created else None
        score, comments = it.get("score"), it.get("descendants")
        title = it.get("title") or ""
        return {
            "platform": "hackernews",
            "source_id": f"hn:{it.get('id')}",
            "title": title,
            "url": it.get("url") or f"https://news.ycombinator.com/item?id={it.get('id')}",
            "community": "hackernews",
            "score": score,
            "comments": comments,
            "created_utc": created,
            "age_hours": round(age_h, 2) if age_h is not None else None,
            "velocity": _velocity(score, comments, age_h),
            "sentiment": score_sentiment(title),
        }

    results = await asyncio.gather(*[_item(i) for i in ids[:limit]], return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


async def hn_search(query: str, limit: int = 25) -> list:
    """Keyword search across HN via Algolia (keyless)."""
    r = await request_json("GET", f"{config.HN_ALGOLIA_API}/search", headers=_UA,
                           params={"query": query, "tags": "story",
                                   "hitsPerPage": str(limit)},
                           timeout=config.REQUEST_TIMEOUT)
    import time as _t
    now = _t.time()
    rows = []
    for h in ((r or {}).get("hits") or []) if isinstance(r, dict) else []:
        created = h.get("created_at_i") or 0
        age_h = max((now - float(created)) / 3600.0, 0.1) if created else None
        score, comments = h.get("points"), h.get("num_comments")
        title = h.get("title") or h.get("story_title") or ""
        rows.append({
            "platform": "hackernews",
            "source_id": f"hn:{h.get('objectID')}",
            "title": title,
            "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            "community": "hackernews",
            "score": score,
            "comments": comments,
            "created_utc": created,
            "age_hours": round(age_h, 2) if age_h is not None else None,
            "velocity": _velocity(score, comments, age_h),
            "sentiment": score_sentiment(title),
        })
    return rows


# ── Google Trends (pytrends — optional) ──────────────────────────────────────
async def google_trending(geo: str = "US") -> list:
    """Daily trending searches via pytrends. Returns [] if pytrends is unavailable.
    pytrends is sync + blocking → run off the event loop."""
    if not google_trends_available():
        return []
    import asyncio

    def _pull():
        try:
            tr = _TrendReq(hl="en-US", tz=0)
            df = tr.trending_searches(pn="united_states")
            terms = [str(x) for x in df[0].tolist()] if df is not None and not df.empty else []
            return terms[:25]
        except Exception as e:  # noqa: BLE001
            logger.info(f"pytrends trending pull failed: {e}")
            return []

    terms = await asyncio.to_thread(_pull)
    rows = []
    for rank, term in enumerate(terms):
        rows.append({
            "platform": "google_trends",
            "source_id": f"gt:{geo}:{term}",
            "title": term,
            "url": f"https://trends.google.com/trends/explore?q={term}&geo={geo}",
            "community": "google_trends",
            "score": max(25 - rank, 1),
            "comments": None,
            "created_utc": None,
            "age_hours": None,
            "velocity": float(max(25 - rank, 1)),
            "sentiment": 0.0,
        })
    return rows


# ── Twitter/X public trends (best-effort) ────────────────────────────────────
async def twitter_trends() -> list:
    """Best-effort public X/Twitter trend list. Degrades to [] on any failure
    (no API key, source unreachable, or unparseable response)."""
    try:
        r = await request_json("GET", config.TWITTER_TRENDS_API, headers=_UA,
                               timeout=config.REQUEST_TIMEOUT)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(r, str):
        # request_json returns dicts; non-HTML/non-JSON public source → skip.
        return []
    return []


# ── aggregate helpers ─────────────────────────────────────────────────────────
async def collect_trending(subreddits=None, hn_limit: int = 30) -> list:
    """Pull + merge trending content across the free sources for the snapshot."""
    import asyncio
    subs = subreddits or config.DEFAULT_SUBREDDITS
    tasks = [reddit_hot(s, limit=15) for s in subs]
    tasks.append(hn_top(limit=hn_limit))
    tasks.append(google_trending())
    results = await asyncio.gather(*tasks, return_exceptions=True)
    rows = []
    for res in results:
        if isinstance(res, list):
            rows.extend(res)
    return rows


def topic_keywords(rows: list, top_n: int = 25) -> list:
    """Derive trending topic terms from a set of content rows by frequency-weighted
    velocity. Deterministic."""
    stop = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
            "is", "are", "be", "this", "that", "it", "as", "at", "by", "from",
            "how", "why", "what", "new", "i", "you", "we", "my", "your", "his",
            "her", "but", "not", "can", "will", "has", "have", "was", "were",
            "they", "their", "about", "into", "out", "up", "do", "does", "vs"}
    weights: Counter = Counter()
    for r in rows:
        vel = float(r.get("velocity") or 0) + 1.0
        for w in _WORD_RE.findall((r.get("title") or "").lower()):
            if len(w) < 4 or w in stop:
                continue
            weights[w] += vel
    out = []
    for term, weight in weights.most_common(top_n):
        out.append({"topic": term, "velocity": round(weight, 2)})
    return out
