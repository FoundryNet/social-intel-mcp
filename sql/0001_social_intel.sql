-- Social Trends Intelligence — schema for social_aggregator + social-intel-mcp.
-- Standalone Supabase project. Idempotent.

create extension if not exists pg_trgm;

-- ── content_items (individual posts/stories snapshotted from sources) ────────
create table if not exists content_items (
  source_id     text primary key,         -- e.g. "reddit:abc123" | "hn:456" | "gt:US:term"
  platform      text,                      -- reddit | hackernews | google_trends | ...
  title         text,
  url           text,
  community     text,                      -- subreddit / hackernews / google_trends
  score         integer,                   -- upvotes / points
  comments      integer,                   -- comment count
  created_utc   bigint,                    -- epoch seconds the item was posted
  age_hours     numeric,
  velocity      numeric,                   -- engagement per hour since posting
  sentiment     numeric,                   -- deterministic lexicon score [-1, 1]
  snapshot_at   timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists idx_content_velocity on content_items (velocity desc nulls last);
create index if not exists idx_content_platform on content_items (platform);
create index if not exists idx_content_community on content_items (community);
create index if not exists idx_content_created on content_items (created_utc desc nulls last);
create index if not exists idx_content_score on content_items (score desc nulls last);
create index if not exists idx_content_title_trgm on content_items using gin (title gin_trgm_ops);

-- ── trending_snapshots (derived trending topics per snapshot) ────────────────
create table if not exists trending_snapshots (
  id            uuid not null default gen_random_uuid(),
  topic         text not null,
  platform      text not null,             -- all | reddit | hackernews | google_trends | ...
  velocity      numeric,                   -- frequency-weighted velocity
  rank          integer,
  snapshot_at   timestamptz not null,
  created_at    timestamptz not null default now(),
  primary key (topic, platform, snapshot_at)
);
create index if not exists idx_trend_snapshot on trending_snapshots (snapshot_at desc);
create index if not exists idx_trend_velocity on trending_snapshots (velocity desc nulls last);
create index if not exists idx_trend_platform on trending_snapshots (platform);

-- ── brand_mentions (optional cached mentions snapshot) ───────────────────────
create table if not exists brand_mention_snapshots (
  id            uuid primary key default gen_random_uuid(),
  brand         text not null,
  platform      text,
  title         text,
  url           text,
  community     text,
  score         integer,
  comments      integer,
  sentiment     numeric,
  snapshot_at   timestamptz not null default now(),
  unique (brand, url)
);
create index if not exists idx_brandmention_brand on brand_mention_snapshots (brand);
create index if not exists idx_brandmention_snapshot on brand_mention_snapshots (snapshot_at desc);

-- ── free-tier counter + payments ─────────────────────────────────────────────
create table if not exists social_query_usage (
  agent_key text not null, day date not null,
  count integer not null default 0, updated_at timestamptz not null default now(),
  primary key (agent_key, day)
);
create or replace function social_claim_free_query(p_agent_key text, p_day date, p_cap integer)
returns jsonb language plpgsql as $$
declare cur integer; ok boolean;
begin
  insert into social_query_usage (agent_key, day, count, updated_at)
  values (p_agent_key, p_day, 0, now())
  on conflict (agent_key, day) do nothing;
  select count into cur from social_query_usage
    where agent_key = p_agent_key and day = p_day for update;
  if cur < p_cap then
    update social_query_usage set count = count + 1, updated_at = now()
      where agent_key = p_agent_key and day = p_day;
    ok := true; cur := cur + 1;
  else ok := false; end if;
  return jsonb_build_object('allowed', ok, 'count', cur, 'cap', p_cap);
end; $$;

create table if not exists social_payments (
  tx_signature text primary key, intent text, agent_key text, tool text,
  amount_usdc numeric, payer_wallet text, recipient text, status text,
  block_time bigint, created_at timestamptz not null default now()
);
