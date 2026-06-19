"""social-intel-mcp — social trends intelligence for autonomous agents.

Part of the FoundryNet Data Network. Trending topics, cross-platform sentiment,
viral content, community pulse, and brand mentions across Reddit, Hacker News,
Google Trends (pytrends), and best-effort Twitter/X. 6 tools + free mint_info.
Free tier 25/day, then x402 (USDC on Solana). Re-aggregates every 4h. Transport:
Streamable HTTP at /mcp (+ /sse).
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

import config
import core
import daily_curator
import identity
import payment_gate
import social_aggregator as agg
import social_sources as src
import supa
import tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("social.mcp")

if not supa.configured():
    logger.warning("SUPABASE_SERVICE_KEY not set — dataset disabled until configured.")

mcp = FastMCP("social-intel")

if payment_gate.is_active():
    logger.info(f"pay-per-query ARMED → {config.PAYMENT_RECIPIENT} after {config.FREE_TIER_DAILY}/day free")
else:
    logger.info("pay-per-query INERT — all tools free")

tools.register_all(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok", "service": "social-intel-mcp", "transport": "streamable-http",
        "network": "FoundryNet Data Network",
        "tools": ["trending_topics", "topic_sentiment", "viral_content", "community_pulse",
                  "brand_mentions", "daily_brief", "mint_info"],
        "dataset": "supabase:content_items+trending_snapshots" if supa.configured() else "unconfigured",
        "sources": "reddit + hackernews + google_trends + twitter(best-effort)",
        "google_trends": "on" if src.google_trends_available() else "off",
        "x402_enabled": config.X402_ENABLED,
        "query_payment": "armed" if payment_gate.is_active() else "free",
        "free_tier_daily": config.FREE_TIER_DAILY,
        "agg_interval_hours": config.AGG_INTERVAL_HOURS,
        "payment_recipient": config.PAYMENT_RECIPIENT,
    })


@mcp.custom_route("/ping", methods=["GET"])
async def ping(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ── REST surface ─────────────────────────────────────────────────────────────
_ERR = {"bad_request": 400, "not_configured": 503, "not_found": 404, "payment_required": 402}


def _resp(d: dict) -> JSONResponse:
    if "error" not in d:
        return JSONResponse(d, status_code=200)
    err = str(d.get("error") or "")
    code = _ERR.get(err, 502 if err in ("network", "non_json_response", "unreachable") else 400)
    if err.startswith("http_") and err[5:].isdigit():
        code = int(err[5:])
    return JSONResponse(d, status_code=code)


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


def _akey(request: Request, body: dict) -> str:
    return identity.resolve_agent_key(body.get("agent_id"), request=request)


@mcp.custom_route("/v1/trending", methods=["POST"])
async def rest_trending(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_trending_topics(b.get("platform", "all"), b.get("category"),
                                               agent_key=_akey(request, b),
                                               payment_tx=b.get("payment_tx"),
                                               api_key=identity.bearer(request)))


@mcp.custom_route("/v1/sentiment", methods=["POST"])
async def rest_sentiment(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_topic_sentiment(b.get("topic", ""), agent_key=_akey(request, b),
                                               payment_tx=b.get("payment_tx"),
                                               api_key=identity.bearer(request)))


@mcp.custom_route("/v1/viral", methods=["POST"])
async def rest_viral(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_viral_content(b.get("hours_back"), b.get("min_score"),
                                             agent_key=_akey(request, b),
                                             payment_tx=b.get("payment_tx"),
                                             api_key=identity.bearer(request)))


@mcp.custom_route("/v1/pulse", methods=["POST"])
async def rest_pulse(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_community_pulse(b.get("subreddit"), b.get("hn_topic"),
                                               agent_key=_akey(request, b),
                                               payment_tx=b.get("payment_tx"),
                                               api_key=identity.bearer(request)))


@mcp.custom_route("/v1/brand", methods=["POST"])
async def rest_brand(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_brand_mentions(b.get("brand", ""), b.get("days_back"),
                                              agent_key=_akey(request, b),
                                              payment_tx=b.get("payment_tx"),
                                              api_key=identity.bearer(request)))


@mcp.custom_route("/v1/daily-brief", methods=["POST"])
async def rest_daily_brief(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_daily_brief(b.get("date"), agent_key=_akey(request, b),
                                           payment_tx=b.get("payment_tx"),
                                           api_key=identity.bearer(request)))


@mcp.custom_route("/v1/mint-info", methods=["GET", "POST"])
async def rest_mint(request: Request) -> JSONResponse:
    return JSONResponse(core.mint_info())


@mcp.custom_route("/admin/aggregate", methods=["POST"])
async def admin_aggregate(request: Request) -> JSONResponse:
    import os
    tok = os.environ.get("ADMIN_TOKEN", "")
    if not tok or request.headers.get("x-admin-token") != tok:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if request.query_params.get("wait") == "1":
        return JSONResponse(await agg.run_aggregation())
    asyncio.create_task(agg.run_aggregation())
    return JSONResponse({"started": True})


# ── Discovery ────────────────────────────────────────────────────────────────
_TAGLINE = "Social trends intelligence for agents — trending topics, sentiment, viral content."
_DESC = ("Social trends intelligence for agents: trending topics with velocity, cross-platform "
         "sentiment, fastest-rising viral content, community pulse, and brand mentions across "
         "Reddit, Hacker News, and Google Trends. Part of the FoundryNet Data Network — attest "
         "analysis with MINT Protocol; see also gov-contracts, brand-intel, patent-intel, "
         "financial-signals, weather-intel, cyber-intel, compliance, fact-check, oss-intel.")
_KEYWORDS = ["social trends", "trending topics", "sentiment analysis", "viral content",
             "community pulse", "brand monitoring", "reddit", "hacker news"]

_AGENT_CARD = {
    "name": "Social Trends Intelligence MCP", "description": _DESC,
    "url": "https://github.com/FoundryNet/social-intel-mcp",
    "capabilities": ["social_trends", "trending_topics", "sentiment_analysis",
                     "viral_content", "community_pulse", "brand_monitoring"],
    "network": "FoundryNet Data Network",
    "protocols": {"mcp": {"endpoint": config.PUBLIC_MCP_URL, "transport": "streamable-http", "tools_count": 6},
                  "x402": {"supported": True, "currency": "USDC", "network": "solana"}},
    "see_also": config.SISTER_SERVERS, "mint_protocol": config.MINT_MCP_URL,
    "contact": "hello@foundrynet.io",
}


@mcp.custom_route("/.well-known/agent-card.json", methods=["GET"])
async def agent_card(request: Request) -> JSONResponse:
    return JSONResponse(_AGENT_CARD, headers={"Cache-Control": "public, max-age=300"})


@mcp.custom_route("/.well-known/mcp", methods=["GET"])
async def mcp_endpoints(request: Request) -> JSONResponse:
    return JSONResponse({"endpoints": [{"url": config.PUBLIC_MCP_URL, "transport": "streamable-http",
                                        "name": "Social Trends Intelligence MCP"}]},
                        headers={"Cache-Control": "public, max-age=300"})


async def _live_tools() -> list:
    res = mcp.list_tools()
    if inspect.iscoroutine(res):
        res = await res
    return [{"name": t.name, "description": (getattr(t, "description", "") or "").strip(),
             "inputSchema": getattr(t, "parameters", None) or {"type": "object"}} for t in res]


@mcp.custom_route("/.well-known/mcp/server-card.json", methods=["GET"])
async def server_card(request: Request) -> JSONResponse:
    live = await _live_tools()
    return JSONResponse({
        "serverInfo": {"name": "Social Trends Intelligence MCP", "version": "1.0.0"},
        "authentication": {"type": "http", "scheme": "bearer",
                           "description": ("mint_info is free; other tools give 25 free queries/day "
                                           "then take an fnet_ Bearer key OR x402 USDC.")},
        "tools": live, "version": "1.0", "name": "Social Trends Intelligence MCP",
        "tagline": _TAGLINE, "description": _DESC,
        "serverUrl": config.PUBLIC_MCP_URL, "transport": "streamable-http",
        "tools_count": len(live),
        "categories": ["social", "trends", "data", "sentiment", "monitoring"],
        "keywords": _KEYWORDS, "network": "FoundryNet Data Network",
        "see_also": config.SISTER_SERVERS,
        "pricing": {"model": "metered",
                    "free_tier": f"{config.FREE_TIER_DAILY} queries/day + free mint_info",
                    "paid_from": f"{config.PRICE_TRENDING_TOPICS} USDC per query (x402)"},
    }, headers={"Cache-Control": "public, max-age=300"})


# ── Background: re-aggregate every AGG_INTERVAL_HOURS (default 4h) ────────────
async def _agg_loop():
    while True:
        await asyncio.sleep(max(config.AGG_INTERVAL_HOURS, 1) * 3600)
        try:
            if supa.configured():
                await agg.run_aggregation()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"agg loop: {e}")


def build_dual_app():
    main_app = mcp.http_app(transport="http", path="/mcp")
    sse_app = mcp.http_app(transport="sse", path="/sse")
    for r in sse_app.routes:
        if getattr(r, "path", None) in ("/sse", "/messages"):
            main_app.router.routes.append(r)
    main_life, sse_life = main_app.router.lifespan_context, sse_app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def _dual_lifespan(app):
        async with main_life(app):
            async with sse_life(app):
                task = asyncio.create_task(_agg_loop())
                brief_task = asyncio.create_task(daily_curator.curator_loop())
                try:
                    yield
                finally:
                    for t in (task, brief_task):
                        t.cancel()
                        with contextlib.suppress(Exception):
                            await t
    main_app.router.lifespan_context = _dual_lifespan
    return main_app


if __name__ == "__main__":
    import uvicorn
    logger.info(f"social-intel-mcp starting on 0.0.0.0:{config.PORT} "
                f"(dataset={'supabase' if supa.configured() else 'off'}, x402={config.X402_ENABLED})")
    uvicorn.run(build_dual_app(), host="0.0.0.0", port=config.PORT, log_level="warning")
