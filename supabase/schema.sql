create table if not exists public.tradingbuddy_scan_runs (
  run_id text primary key,
  run_started_at timestamptz not null,
  run_completed_at timestamptz,
  scan_date date not null,
  history_start_date date,
  refresh_mode text,
  symbols_scanned integer not null default 0,
  symbols_updated integer not null default 0,
  symbols_failed integer not null default 0,
  minervini_pass_count integer not null default 0,
  weekly_buy_sell_count integer not null default 0,
  latest_candle_date date,
  created_at timestamptz not null default now()
);

create table if not exists public.tradingbuddy_minervini_shortlists (
  id bigserial primary key,
  run_id text not null references public.tradingbuddy_scan_runs(run_id) on delete cascade,
  run_started_at timestamptz not null,
  shortlist_date date not null,
  exchange text not null,
  symbol text not null,
  tradingview_symbol text not null,
  name text,
  shortlisted_price numeric,
  current_price numeric,
  gain_loss_pct numeric,
  price_source text,
  as_of_date date,
  relative_strength_rank numeric,
  relative_strength_return_pct numeric,
  minervini_pass_count integer,
  rule_1_price_above_150_200_sma boolean,
  rule_2_sma150_above_sma200 boolean,
  rule_3_sma200_trending_up boolean,
  rule_4_sma50_above_150_200 boolean,
  rule_5_price_above_sma50 boolean,
  rule_6_price_30pct_above_52w_low boolean,
  rule_7_price_within_25pct_of_52w_high boolean,
  rule_8_relative_strength_rank_70 boolean,
  latest_weekly_signal text,
  latest_weekly_signal_date date,
  created_at timestamptz not null default now()
);

create table if not exists public.tradingbuddy_weekly_buy_sell_shortlists (
  id bigserial primary key,
  run_id text not null references public.tradingbuddy_scan_runs(run_id) on delete cascade,
  run_started_at timestamptz not null,
  shortlist_date date not null,
  exchange text not null,
  symbol text not null,
  tradingview_symbol text not null,
  name text,
  signal text not null,
  signal_date date,
  signal_price numeric,
  current_price numeric,
  gain_loss_pct numeric,
  price_source text,
  bars_since_weekly_signal integer,
  weekly_volume_confirmation boolean,
  weekly_volume_confirmation_ratio numeric,
  weekly_trend_confirmation boolean,
  weekly_demand_zone numeric,
  weekly_supply_zone numeric,
  minervini_pass_count integer,
  passes_minervini boolean,
  created_at timestamptz not null default now()
);

create index if not exists tradingbuddy_minervini_run_idx
  on public.tradingbuddy_minervini_shortlists(run_id);

create index if not exists tradingbuddy_minervini_symbol_idx
  on public.tradingbuddy_minervini_shortlists(symbol, shortlist_date desc);

create index if not exists tradingbuddy_weekly_run_idx
  on public.tradingbuddy_weekly_buy_sell_shortlists(run_id);

create index if not exists tradingbuddy_weekly_symbol_idx
  on public.tradingbuddy_weekly_buy_sell_shortlists(symbol, shortlist_date desc);

create table if not exists public.tradingbuddy_kite_tokens (
  token_name text primary key,
  access_token text not null,
  profile jsonb not null default '{}'::jsonb,
  generated_at timestamptz not null,
  expires_at timestamptz not null,
  updated_at timestamptz not null default now()
);

alter table public.tradingbuddy_kite_tokens enable row level security;

create index if not exists tradingbuddy_kite_tokens_expires_idx
  on public.tradingbuddy_kite_tokens(expires_at);
