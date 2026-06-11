-- ReceiptAI learned item aliases
-- Run once in Supabase SQL Editor.
-- Stores user-taught meanings like "goat = mutton" or "pitaya = dragon fruit".

create table if not exists public.receipt_item_aliases (
  id uuid primary key default gen_random_uuid(),
  user_id uuid null,
  guest_session_id text null,
  term text not null,
  alias text not null,
  created_at timestamptz not null default now(),
  constraint receipt_item_aliases_owner_check
    check (user_id is not null or guest_session_id is not null)
);

create unique index if not exists receipt_item_aliases_unique_user
  on public.receipt_item_aliases (user_id, term, alias)
  where user_id is not null;

create unique index if not exists receipt_item_aliases_unique_guest
  on public.receipt_item_aliases (guest_session_id, term, alias)
  where guest_session_id is not null;

create index if not exists receipt_item_aliases_user_idx
  on public.receipt_item_aliases (user_id);

create index if not exists receipt_item_aliases_guest_idx
  on public.receipt_item_aliases (guest_session_id);

alter table public.receipt_item_aliases enable row level security;

drop policy if exists "Users can read own aliases" on public.receipt_item_aliases;
create policy "Users can read own aliases"
  on public.receipt_item_aliases
  for select
  using (auth.uid() = user_id);

drop policy if exists "Users can insert own aliases" on public.receipt_item_aliases;
create policy "Users can insert own aliases"
  on public.receipt_item_aliases
  for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users can update own aliases" on public.receipt_item_aliases;
create policy "Users can update own aliases"
  on public.receipt_item_aliases
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "Users can delete own aliases" on public.receipt_item_aliases;
create policy "Users can delete own aliases"
  on public.receipt_item_aliases
  for delete
  using (auth.uid() = user_id);
