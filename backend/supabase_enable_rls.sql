-- ReceiptAI Supabase RLS hardening.
-- Run this in Supabase SQL Editor for project okzsqmoxdzrbhhdrsazy.
--
-- Goal:
-- 1. Enable Row-Level Security on public receipt tables.
-- 2. Let authenticated users access only rows where user_id = auth.uid().
-- 3. Keep guest receipt access server-side only through the FastAPI backend.
--
-- Important:
-- The FastAPI backend should use the Supabase service-role key on the server only.
-- Do not put the service-role key in the Expo mobile app.

alter table if exists public.receipts enable row level security;
alter table if exists public.receipt_items enable row level security;

-- Optional but recommended: make sure anon has no direct table access.
-- Authenticated policies below still allow signed-in users to access only their rows.
revoke all on table public.receipts from anon;
revoke all on table public.receipt_items from anon;

-- The authenticated role can attempt table operations, but RLS policies below decide
-- which rows are actually visible or writable.
grant select, insert, update, delete on table public.receipts to authenticated;
grant select, insert, update, delete on table public.receipt_items to authenticated;

-- Clean up old policy names so the script is safe to rerun.
drop policy if exists "ReceiptAI users can read own receipts" on public.receipts;
drop policy if exists "ReceiptAI users can insert own receipts" on public.receipts;
drop policy if exists "ReceiptAI users can update own receipts" on public.receipts;
drop policy if exists "ReceiptAI users can delete own receipts" on public.receipts;

drop policy if exists "ReceiptAI users can read own receipt items" on public.receipt_items;
drop policy if exists "ReceiptAI users can insert own receipt items" on public.receipt_items;
drop policy if exists "ReceiptAI users can update own receipt items" on public.receipt_items;
drop policy if exists "ReceiptAI users can delete own receipt items" on public.receipt_items;

-- Receipts: permanent signed-in user rows only.
create policy "ReceiptAI users can read own receipts"
on public.receipts
for select
to authenticated
using (
    (select auth.uid()) is not null
    and user_id = (select auth.uid())
    and coalesce(is_guest, false) = false
);

create policy "ReceiptAI users can insert own receipts"
on public.receipts
for insert
to authenticated
with check (
    (select auth.uid()) is not null
    and user_id = (select auth.uid())
    and coalesce(is_guest, false) = false
);

create policy "ReceiptAI users can update own receipts"
on public.receipts
for update
to authenticated
using (
    (select auth.uid()) is not null
    and user_id = (select auth.uid())
    and coalesce(is_guest, false) = false
)
with check (
    (select auth.uid()) is not null
    and user_id = (select auth.uid())
    and coalesce(is_guest, false) = false
);

create policy "ReceiptAI users can delete own receipts"
on public.receipts
for delete
to authenticated
using (
    (select auth.uid()) is not null
    and user_id = (select auth.uid())
    and coalesce(is_guest, false) = false
);

-- Normalized receipt items: permanent signed-in user rows only.
create policy "ReceiptAI users can read own receipt items"
on public.receipt_items
for select
to authenticated
using (
    (select auth.uid()) is not null
    and user_id = (select auth.uid())
    and coalesce(is_guest, false) = false
);

create policy "ReceiptAI users can insert own receipt items"
on public.receipt_items
for insert
to authenticated
with check (
    (select auth.uid()) is not null
    and user_id = (select auth.uid())
    and coalesce(is_guest, false) = false
);

create policy "ReceiptAI users can update own receipt items"
on public.receipt_items
for update
to authenticated
using (
    (select auth.uid()) is not null
    and user_id = (select auth.uid())
    and coalesce(is_guest, false) = false
)
with check (
    (select auth.uid()) is not null
    and user_id = (select auth.uid())
    and coalesce(is_guest, false) = false
);

create policy "ReceiptAI users can delete own receipt items"
on public.receipt_items
for delete
to authenticated
using (
    (select auth.uid()) is not null
    and user_id = (select auth.uid())
    and coalesce(is_guest, false) = false
);

-- Verification query. Run after the policy statements if you want to confirm.
select
    schemaname,
    tablename,
    rowsecurity
from pg_tables
where schemaname = 'public'
  and tablename in ('receipts', 'receipt_items')
order by tablename;
