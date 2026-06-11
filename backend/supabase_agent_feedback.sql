-- ReceiptAI agent feedback and correction memory.
-- Run once in Supabase SQL Editor.
-- Stores bad-answer examples so they can be reviewed, measured, and converted into durable fixes.

create table if not exists public.agent_feedback (
  id uuid primary key default gen_random_uuid(),
  user_id uuid null,
  guest_session_id text null,
  session_id text null,
  message text not null,
  response text null,
  expected_response text null,
  rating text null,
  correction_note text null,
  alias_term text null,
  alias_value text null,
  status text not null default 'new',
  created_at timestamptz not null default now(),
  resolved_at timestamptz null,
  constraint agent_feedback_owner_check
    check (user_id is not null or guest_session_id is not null)
);

create index if not exists agent_feedback_user_idx
  on public.agent_feedback (user_id, created_at desc);

create index if not exists agent_feedback_guest_idx
  on public.agent_feedback (guest_session_id, created_at desc);

create index if not exists agent_feedback_status_idx
  on public.agent_feedback (status, created_at desc);

alter table public.agent_feedback enable row level security;

drop policy if exists "Users can read own agent feedback" on public.agent_feedback;
create policy "Users can read own agent feedback"
  on public.agent_feedback
  for select
  using (auth.uid() = user_id);

drop policy if exists "Users can insert own agent feedback" on public.agent_feedback;
create policy "Users can insert own agent feedback"
  on public.agent_feedback
  for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users can update own agent feedback" on public.agent_feedback;
create policy "Users can update own agent feedback"
  on public.agent_feedback
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
