"""Env-driven configuration for social-intel-mcp.

Social Trends Intelligence: trending topics, sentiment, viral content, community
pulse, and brand mentions across Reddit, Hacker News, Google Trends (pytrends),
and best-effort Twitter/X public trends — in its own standalone Supabase project.
6 tools + free mint_info, x402 metered. Part of the FoundryNet Data Network.

Required to be useful:
  SUPABASE_URL, SUPABASE_SERVICE_KEY   the standalone social-intel project.
Optional:
  REDDIT_USER_AGENT    polite UA for Reddit's public JSON endpoints
  GOOGLE_TRENDS_ENABLED  enable pytrends (off if the lib is missing)
  PORT, REQUEST_TIMEOUT
  X402_ENABLED, SOLANA_WALLET, PAYMENT_RECIPIENT, PAYMENT_VERIFY_RPC,
  PAYMENT_USDC_MINT, PAYMENT_EXPIRY_SECONDS
  FREE_TIER_DAILY      default 25
  AGG_INTERVAL_HOURS   re-aggregation cadence, default 4
  PRICE_*              per-tool USDC prices
"""
from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _flag(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").strip().lower() in ("1", "true", "yes", "on")


SUPABASE_URL         = _env("SUPABASE_URL", "https://twbxvcjxnlxatchapcbg.supabase.co").rstrip("/")
SUPABASE_SERVICE_KEY = _env("SUPABASE_SERVICE_KEY")

PORT            = int(_env("PORT", "8080"))
REQUEST_TIMEOUT = int(_env("REQUEST_TIMEOUT", "30"))

# ── Sources (all free / keyless) ─────────────────────────────────────────────
REDDIT_API        = "https://www.reddit.com"
HN_API            = "https://hacker-news.firebaseio.com/v0"
HN_ALGOLIA_API    = "https://hn.algolia.com/api/v1"
TWITTER_TRENDS_API = _env("TWITTER_TRENDS_API", "https://trends24.in")  # best-effort public source
SOURCE_USER_AGENT = _env("SOURCE_USER_AGENT", "FoundryNet Data Network hello@foundrynet.io")
REDDIT_USER_AGENT = _env("REDDIT_USER_AGENT", SOURCE_USER_AGENT)
# Google Trends (pytrends) is optional: off when the lib isn't installed or the flag is false.
GOOGLE_TRENDS_ENABLED = _flag("GOOGLE_TRENDS_ENABLED", True)

# Default subreddits + HN sampled for the trending snapshot.
DEFAULT_SUBREDDITS = [s.strip() for s in _env(
    "DEFAULT_SUBREDDITS",
    "technology,worldnews,news,programming,science,business,stocks,artificial,futurology,gaming").split(",")
    if s.strip()]

AGG_INTERVAL_HOURS = int(_env("AGG_INTERVAL_HOURS", "4"))

# ── x402 per-tool pricing ────────────────────────────────────────────────────
X402_ENABLED      = _flag("X402_ENABLED", True)
SOLANA_WALLET     = _env("SOLANA_WALLET", "wUumjWWvtFEr69qkTw3wHNVQVxLA8DTyJSyVgGmLThd")
PAYMENT_RECIPIENT = _env("PAYMENT_RECIPIENT", SOLANA_WALLET).strip()
PAYMENT_VERIFY_RPC = _env("PAYMENT_VERIFY_RPC", "https://api.mainnet-beta.solana.com").rstrip("/")
PAYMENT_USDC_MINT  = _env("PAYMENT_USDC_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v").strip()
PAYMENT_EXPIRY_SECONDS = int(_env("PAYMENT_EXPIRY_SECONDS", "300"))

FREE_TIER_DAILY = int(_env("FREE_TIER_DAILY", "25"))

PRICE_TRENDING_TOPICS = float(_env("PRICE_TRENDING_TOPICS", "0.01"))
PRICE_TOPIC_SENTIMENT = float(_env("PRICE_TOPIC_SENTIMENT", "0.01"))
PRICE_VIRAL_CONTENT   = float(_env("PRICE_VIRAL_CONTENT", "0.01"))
PRICE_COMMUNITY_PULSE = float(_env("PRICE_COMMUNITY_PULSE", "0.01"))
PRICE_BRAND_MENTIONS  = float(_env("PRICE_BRAND_MENTIONS", "0.02"))
PRICE_DAILY_BRIEF     = float(_env("PRICE_DAILY_BRIEF", "5"))

# Per-tool price table (also consulted by payment_gate._price_for).
TOOL_PRICES = {
    "trending_topics": PRICE_TRENDING_TOPICS,
    "topic_sentiment": PRICE_TOPIC_SENTIMENT,
    "viral_content":   PRICE_VIRAL_CONTENT,
    "community_pulse": PRICE_COMMUNITY_PULSE,
    "brand_mentions":  PRICE_BRAND_MENTIONS,
    "daily_brief":     PRICE_DAILY_BRIEF,
}

# ── Daily curated brief ──────────────────────────────────────────────────────
BRIEF_HOUR_UTC = int(_env("BRIEF_HOUR_UTC", "5"))   # curator runs at 05:00 UTC
SERVER_SLUG    = "social-intel"
# Cross-network brief catalog (server -> price + tool) for related_briefs.
NETWORK_BRIEFS = {
    "financial-signals": "$25", "cyber-intel": "$15", "patent-intel": "$10",
    "gov-contracts": "$10", "compliance": "$10", "brand-intel": "$5", "weather-intel": "$5",
    "fact-check": "$5", "oss-intel": "$5", "social-intel": "$5",
}

# ── FoundryNet Data Network cross-promo ──────────────────────────────────────
MINT_MCP_URL  = _env("MINT_MCP_URL", "https://mint-mcp-production.up.railway.app/mcp")
MINT_INFO_URL = _env("MINT_INFO_URL", "https://mint.foundrynet.io")
SISTER_SERVERS = {
    "mint-mcp":                "https://mint-mcp-production.up.railway.app/mcp",
    "foundrynet-mcp":          "https://foundrynet-mcp-production.up.railway.app/mcp",
    "gov-contracts-mcp":       "https://gov-contracts-mcp-production.up.railway.app/mcp",
    "brand-intel-mcp":         "https://brand-intel-mcp-production.up.railway.app/mcp",
    "patent-intel-mcp":        "https://patent-intel-mcp-production.up.railway.app/mcp",
    "financial-signals-mcp":   "https://financial-signals-mcp-production.up.railway.app/mcp",
    "weather-intel-mcp":       "https://weather-intel-mcp-production.up.railway.app/mcp",
    "cyber-intel-mcp":         "https://cyber-intel-mcp-production.up.railway.app/mcp",
    "compliance-mcp":          "https://compliance-mcp-production.up.railway.app/mcp",
    "academic-intel-mcp":      "https://academic-intel-mcp-production.up.railway.app/mcp",
    "fact-check-mcp":          "https://fact-check-mcp-production.up.railway.app/mcp",
    "oss-intel-mcp":           "https://oss-intel-mcp-production.up.railway.app/mcp",
    "crypto-intel-mcp":        "https://crypto-intel-mcp-production.up.railway.app/mcp",
    "market-data-mcp":         "https://market-data-mcp-production.up.railway.app/mcp",
    "email-verify-mcp":        "https://email-verify-mcp-production.up.railway.app/mcp",
    "currency-intel-mcp":      "https://currency-intel-mcp-production.up.railway.app/mcp",
}

PUBLIC_MCP_URL = _env("PUBLIC_MCP_URL", "https://social-intel-mcp-production.up.railway.app/mcp")
