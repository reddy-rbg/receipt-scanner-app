-- ReceiptAI adaptive ML retrieval layer.
-- Run after supabase_receipt_items.sql if you want local vector boosts.
-- The app works without this table/function; retrieval falls back safely.

create extension if not exists vector;

create table if not exists public.receipt_item_embeddings (
  id uuid primary key default gen_random_uuid(),
  user_id uuid null,
  guest_session_id text null,
  receipt_id bigint not null references public.receipts(id) on delete cascade,
  line_index integer not null,
  item_name text not null,
  item_text text not null,
  embedding vector(1536) not null,
  model text not null default 'receiptai-contextual-local-hash-v2',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint receipt_item_embeddings_owner_check
    check (user_id is not null or guest_session_id is not null)
);

alter table public.receipt_item_embeddings
  alter column model set default 'receiptai-contextual-local-hash-v2';

create unique index if not exists receipt_item_embeddings_unique_user
  on public.receipt_item_embeddings (user_id, receipt_id, line_index, model)
  where user_id is not null;

create unique index if not exists receipt_item_embeddings_unique_guest
  on public.receipt_item_embeddings (guest_session_id, receipt_id, line_index, model)
  where guest_session_id is not null;

create index if not exists receipt_item_embeddings_vector_idx
  on public.receipt_item_embeddings
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

drop function if exists public.match_receipt_item_embeddings(vector(1536), integer, uuid, text);

create or replace function public.match_receipt_item_embeddings(
  query_embedding vector(1536),
  match_count integer default 50,
  p_user_id uuid default null,
  p_guest_session_id text default null
)
returns table (
  receipt_id bigint,
  line_index integer,
  item_name text,
  item_text text,
  model text,
  similarity double precision
)
language sql
stable
as $$
  select
    e.receipt_id,
    e.line_index,
    e.item_name,
    e.item_text,
    e.model,
    1 - (e.embedding <=> query_embedding) as similarity
  from public.receipt_item_embeddings e
  where
    (p_user_id is not null and e.user_id = p_user_id)
    or (p_user_id is null and p_guest_session_id is not null and e.guest_session_id = p_guest_session_id)
  order by e.embedding <=> query_embedding
  limit match_count;
$$;

alter table public.receipt_item_embeddings enable row level security;

drop policy if exists "Users can read own receipt item embeddings" on public.receipt_item_embeddings;
create policy "Users can read own receipt item embeddings"
  on public.receipt_item_embeddings
  for select
  using (auth.uid() = user_id);

drop policy if exists "Users can insert own receipt item embeddings" on public.receipt_item_embeddings;
create policy "Users can insert own receipt item embeddings"
  on public.receipt_item_embeddings
  for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users can update own receipt item embeddings" on public.receipt_item_embeddings;
create policy "Users can update own receipt item embeddings"
  on public.receipt_item_embeddings
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
