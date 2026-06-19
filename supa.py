"""Supabase PostgREST client for social-intel-mcp (standalone project)."""
from __future__ import annotations

import logging
import time
from typing import Optional

import config
from http_util import request_json

logger = logging.getLogger("social.supa")


def configured() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)


def _headers(extra: Optional[dict] = None) -> dict:
    h = {"apikey": config.SUPABASE_SERVICE_KEY,
         "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
         "Content-Type": "application/json", "Accept": "application/json"}
    if extra:
        h.update(extra)
    return h


def _url(path: str) -> str:
    return f"{config.SUPABASE_URL}/rest/v1/{path}"


async def select(table: str, params: dict) -> list:
    if not configured():
        return []
    r = await request_json("GET", _url(table), headers=_headers(), params=params,
                           timeout=config.REQUEST_TIMEOUT)
    return r if isinstance(r, list) else []


async def rpc(fn: str, body: dict):
    if not configured():
        return None
    return await request_json("POST", _url(f"rpc/{fn}"), headers=_headers(), body=body,
                              timeout=config.REQUEST_TIMEOUT)


async def upsert(table: str, rows: list, on_conflict: str) -> dict:
    if not configured() or not rows:
        return {"data": []}
    r = await request_json("POST", _url(table),
                           headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                           params={"on_conflict": on_conflict},
                           body=rows, timeout=max(config.REQUEST_TIMEOUT, 60))
    if isinstance(r, dict) and r.get("error"):
        return r
    return {"data": rows}


async def _bulk_upsert(table: str, rows: list, on_conflict: str) -> int:
    if not configured() or not rows:
        return 0
    seen, deduped = set(), []
    keys = on_conflict.split(",")
    for r in rows:
        k = tuple(r.get(c) for c in keys)
        if any(x is None for x in k) or k in seen:
            continue
        seen.add(k)
        deduped.append(r)
    allkeys = set()
    for r in deduped:
        allkeys.update(r.keys())
    deduped = [{k: r.get(k) for k in allkeys} for r in deduped]
    written = 0
    for i in range(0, len(deduped), 500):
        resp = await request_json("POST", _url(table),
                                  headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                                  params={"on_conflict": on_conflict},
                                  body=deduped[i:i + 500], timeout=max(config.REQUEST_TIMEOUT, 60))
        if isinstance(resp, dict) and resp.get("error"):
            logger.warning(f"upsert {table} chunk {i}: {str(resp)[:200]}")
        else:
            written += len(deduped[i:i + 500])
    return written


# ── writes (aggregator) ───────────────────────────────────────────────────────
async def upsert_content(rows: list) -> int:
    """Snapshot of individual content items (posts/stories). Keyed on source_id."""
    return await _bulk_upsert("content_items", rows, "source_id")


async def upsert_trending(rows: list) -> int:
    """Trending-topic snapshot rows. Keyed on (topic, platform, snapshot_at)."""
    return await _bulk_upsert("trending_snapshots", rows, "topic,platform,snapshot_at")


# ── reads ─────────────────────────────────────────────────────────────────────
_CFIELDS = ("platform,source_id,title,url,community,score,comments,created_utc,"
            "age_hours,velocity,sentiment,snapshot_at")
_TFIELDS = "topic,platform,velocity,rank,snapshot_at"


async def latest_trending(platform: Optional[str] = None, limit: int = 25) -> list:
    p = {"select": _TFIELDS, "order": "snapshot_at.desc,velocity.desc.nullslast",
         "limit": str(min(max(int(limit or 25), 1), 200))}
    if platform and platform != "all":
        p["platform"] = f"eq.{platform}"
    return await select("trending_snapshots", p)


async def content_for_topic(topic: str, limit: int = 50) -> list:
    kw = (topic or "").replace("*", "").replace(",", " ").strip()
    p = {"select": _CFIELDS, "order": "velocity.desc.nullslast", "limit": str(limit)}
    if kw:
        p["title"] = f"ilike.*{kw}*"
    return await select("content_items", p)


async def viral_content(*, since_utc=None, min_score=None, limit: int = 30) -> list:
    p = {"select": _CFIELDS, "order": "velocity.desc.nullslast", "limit": str(limit)}
    if since_utc is not None:
        p["created_utc"] = f"gte.{since_utc}"
    if min_score is not None:
        p["score"] = f"gte.{min_score}"
    return await select("content_items", p)


async def community_content(*, community=None, platform=None, limit: int = 40) -> list:
    p = {"select": _CFIELDS, "order": "velocity.desc.nullslast", "limit": str(limit)}
    if community:
        p["community"] = f"eq.{community}"
    if platform:
        p["platform"] = f"eq.{platform}"
    return await select("content_items", p)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


# ── free-tier + payments ──────────────────────────────────────────────────────
async def claim_free_query(agent_key: str, day: str, cap: int) -> Optional[dict]:
    r = await rpc("social_claim_free_query", {"p_agent_key": agent_key, "p_day": day, "p_cap": cap})
    if isinstance(r, dict) and "allowed" in r:
        return r
    if isinstance(r, list) and r and isinstance(r[0], dict):
        return r[0]
    return None


async def payment_tx_used(tx_signature: str) -> bool:
    rows = await select("social_payments", {"tx_signature": f"eq.{tx_signature}",
                                            "select": "tx_signature", "limit": "1"})
    return bool(rows)


async def insert_payment(row: dict) -> dict:
    if not configured():
        return {"error": "not_configured"}
    r = await request_json("POST", _url("social_payments"),
                           headers=_headers({"Prefer": "return=minimal"}),
                           body=row, timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, dict) and r.get("error"):
        return r
    return {"data": [row]}
