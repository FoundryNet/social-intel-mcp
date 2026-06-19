"""social-intel-mcp tools — one per file.

  trending_topics   ($0.01)  top trending topics w/ velocity (Reddit/HN/Trends)
  topic_sentiment   ($0.01)  cross-platform sentiment + volume trend + threads
  viral_content     ($0.01)  content gaining traction fastest, by velocity
  community_pulse   ($0.01)  a community's hot topics, sentiment, activity level
  brand_mentions    ($0.02)  brand/product mentions w/ sentiment + context (premium)
  daily_brief       ($5)     curated daily social-trends brief (premium, attested)
  mint_info         (free)   FoundryNet Data Network + MINT cross-promo
"""
from . import trending as trending_tool
from . import sentiment as sentiment_tool
from . import viral as viral_tool
from . import pulse as pulse_tool
from . import mentions as mentions_tool
from . import daily_brief as daily_brief_tool
from . import mint as mint_tool


def register_all(mcp) -> None:
    for m in (trending_tool, sentiment_tool, viral_tool, pulse_tool, mentions_tool,
              daily_brief_tool, mint_tool):
        m.register(mcp)
