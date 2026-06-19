# Social Trends Intelligence MCP

**Social trends intelligence for AI agents** — trending topics with velocity
scores, cross-platform sentiment, the fastest-rising viral content, community
pulse, and brand mentions across Reddit, Hacker News, and Google Trends.

> Part of the **FoundryNet Data Network**. Attest your agent's social-trends
> analysis with [MINT Protocol](https://mint-mcp-production.up.railway.app/mcp).
> See also: **gov-contracts-mcp**, **brand-intel-mcp**, **patent-intel-mcp**,
> **financial-signals-mcp**, **weather-intel-mcp**, **cyber-intel-mcp**,
> **compliance-mcp**, **academic-intel-mcp**, **fact-check-mcp**, **oss-intel-mcp**.

Live MCP endpoint (Streamable HTTP):
`https://social-intel-mcp-production.up.railway.app/mcp`

## Tools

| Tool | Price | What it does |
|---|---|---|
| `trending_topics` | $0.01 | Top trending topics with **velocity** scores (Reddit / HN / Google Trends) |
| `topic_sentiment` | $0.01 | Cross-platform sentiment for a topic, volume trend, key discussion threads |
| `viral_content` | $0.01 | Content gaining traction **fastest**, ranked by velocity (engagement/hour) |
| `community_pulse` | $0.01 | A community's hot topics, sentiment, and activity level |
| `brand_mentions` | $0.02 | Brand/product mentions across platforms with sentiment + context |
| `daily_brief` | $5 | Curated daily social-trends brief (premium, MINT-attested) |
| `mint_info` | **free** | FoundryNet Data Network + MINT Protocol |

**Free tier:** 25 paid-tool queries/day per agent. Then x402: the tool returns an
HTTP-402 with a Solana USDC payment memo — pay it, re-call with the same args plus
`payment_tx=<signature>`. An `Authorization: Bearer fnet_…` key bypasses the paywall.

## The edge: velocity, not raw counts

Raw upvote counts are lagging. Every item here carries a **velocity** score —
engagement per hour since posting — so `viral_content` and `trending_topics`
surface what's *accelerating*, not just what's already big. Sentiment is a
deterministic lexicon heuristic (no LLM), so results are cheap and reproducible.

## Sources

Every 4 hours: **Reddit** (public JSON endpoints), **Hacker News** (Firebase API),
and **Google Trends** (via `pytrends`, optional). Live on demand: Reddit + HN
keyword search for sentiment, brand mentions, and community pulse. Twitter/X public
trends are folded in best-effort and degrade gracefully when unavailable. Stored in
a standalone Supabase project.

## Connect

Smithery: `@foundrynet/social-intel` · MCP registry: `io.github.FoundryNet/social-intel-mcp`

```json
{ "mcpServers": { "social-intel": { "url": "https://social-intel-mcp-production.up.railway.app/mcp" } } }
```

Built by [FoundryNet](https://foundrynet.io) · hello@foundrynet.io
