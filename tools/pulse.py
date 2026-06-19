from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def community_pulse(
        subreddit: Optional[str] = None,
        hn_topic: Optional[str] = None,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Current pulse of a community — its hot topics, aggregate sentiment, and
        activity level (high/moderate/low by total engagement). Point it at a
        subreddit, a Hacker News topic, or both.

        PAID: $0.01 USDC per query after the daily free allowance (25/day). On a
        402, pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. An Authorization: Bearer fnet_ key bypasses it.

        Args:
            subreddit: a subreddit name, e.g. "technology" (no r/ needed).
            hn_topic: a keyword to pulse on Hacker News.
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_community_pulse(
            subreddit, hn_topic, agent_key=identity.resolve_agent_key(agent_id),
            payment_tx=payment_tx, api_key=identity.bearer())
