-- ReceiptAI AI token usage logging for the operations dashboard.
-- Run this once in Supabase SQL Editor before expecting live token analytics.

create table if not exists public.ai_token_usage (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  feature text not null,
  operation text not null,
  model text not null,
  user_id uuid null,
  guest_session_id text null,
  customer_id uuid null,
  receipt_id bigint null,
  filename text null,
  file_type text null,
  file_bytes bigint null default 0,
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  cached_input_tokens integer not null default 0,
  total_tokens integer not null default 0,
  estimated_cost_usd numeric(12,6) null,
  optimized boolean not null default false,
  optimization text null,
  metadata jsonb not null default '{}'::jsonb
);

create index if not exists ai_token_usage_created_at_idx
  on public.ai_token_usage(created_at desc);

create index if not exists ai_token_usage_customer_created_idx
  on public.ai_token_usage(customer_id, created_at desc);

create index if not exists ai_token_usage_user_created_idx
  on public.ai_token_usage(user_id, created_at desc);

create index if not exists ai_token_usage_receipt_idx
  on public.ai_token_usage(receipt_id);

alter table public.ai_token_usage enable row level security;

revoke all on table public.ai_token_usage from anon;
revoke all on table public.ai_token_usage from authenticated;

-- Backend uses the Supabase service role key, which bypasses RLS.
-- Do not expose direct client access; read this table through /rbac/token-usage.
