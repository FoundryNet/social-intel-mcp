from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def topic_sentiment(
        topic: str,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Analyze cross-platform sentiment for a topic on Reddit and Hacker News —
        an overall score + per-platform breakdown, volume trend (rising/steady/new),
        and key discussion threads. Deterministic lexicon heuristic (no LLM).

        PAID: $0.01 USDC per query after the daily free allowance (25/day). On a
        402, pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. An Authorization: Bearer fnet_ key bypasses it.

        Args:
            topic: the topic/keyword to gauge sentiment for.
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_topic_sentiment(
            topic, agent_key=identity.resolve_agent_key(agent_id),
            payment_tx=payment_tx, api_key=identity.bearer())
