-- ReceiptAI application error/event logging.
-- Run once in Supabase SQL Editor to enable future ops error dashboards.
-- Backend writes through the service role; clients should not access directly.

create table if not exists public.app_error_events (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  severity text not null default 'error',
  source text not null,
  message text not null,
  request_id text null,
  user_id uuid null,
  customer_id uuid null,
  error_type text null,
  stack text null,
  metadata jsonb not null default '{}'::jsonb
);

create index if not exists app_error_events_created_at_idx
  on public.app_error_events(created_at desc);

create index if not exists app_error_events_source_created_idx
  on public.app_error_events(source, created_at desc);

create index if not exists app_error_events_customer_created_idx
  on public.app_error_events(customer_id, created_at desc);

alter table public.app_error_events enable row level security;

revoke all on table public.app_error_events from anon;
revoke all on table public.app_error_events from authenticated;

