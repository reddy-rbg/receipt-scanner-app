-- ReceiptAI normalized receipt item table.
-- Run this once in Supabase SQL Editor before/after deploying the backend.

create table if not exists public.receipt_items (
    id bigserial primary key,
    receipt_id bigint not null references public.receipts(id) on delete cascade,
    line_index integer not null default 0,
    user_id uuid null,
    is_guest boolean not null default false,
    guest_session_id text null,
    expires_at timestamptz null,
    store text null,
    purchase_date text null,
    receipt_created_at timestamptz null,
    code text null,
    item_name_original text not null,
    item_name_normalized text not null,
    product_size text null,
    quantity numeric not null default 1,
    raw_quantity numeric null,
    unit text null default 'each',
    unit_price numeric null,
    line_price numeric null,
    source text null default 'printed',
    confidence numeric null,
    explicit_quantity boolean not null default false,
    metadata jsonb null,
    created_at timestamptz not null default now()
);

create index if not exists idx_receipt_items_user_date
    on public.receipt_items(user_id, receipt_created_at desc);

create index if not exists idx_receipt_items_guest_date
    on public.receipt_items(guest_session_id, receipt_created_at desc)
    where is_guest = true;

create index if not exists idx_receipt_items_name
    on public.receipt_items(item_name_normalized);

create index if not exists idx_receipt_items_price
    on public.receipt_items(line_price);

create index if not exists idx_receipt_items_store
    on public.receipt_items(store);

-- Optional one-time backfill from existing receipt JSON.
-- Safe to run repeatedly because it avoids duplicate receipt_id + line_index rows.
insert into public.receipt_items (
    receipt_id,
    line_index,
    user_id,
    is_guest,
    guest_session_id,
    expires_at,
    store,
    purchase_date,
    receipt_created_at,
    code,
    item_name_original,
    item_name_normalized,
    product_size,
    quantity,
    raw_quantity,
    unit,
    unit_price,
    line_price,
    source,
    confidence,
    explicit_quantity,
    metadata
)
select
    r.id,
    item.ordinality - 1,
    r.user_id,
    coalesce(r.is_guest, false),
    r.guest_session_id,
    r.expires_at,
    r.store,
    r.date,
    r.created_at,
    item.value ->> 'code',
    coalesce(item.value ->> 'name', item.value ->> 'item', 'Unknown item'),
    lower(regexp_replace(coalesce(item.value ->> 'normalized_name', item.value ->> 'name', item.value ->> 'item', ''), '[^a-zA-Z0-9\.]+', ' ', 'g')),
    item.value ->> 'product_size',
    coalesce(nullif(regexp_replace(coalesce(item.value ->> 'quantity', ''), '[^0-9\.-]', '', 'g'), '')::numeric, 1),
    coalesce(nullif(regexp_replace(coalesce(item.value ->> 'quantity', ''), '[^0-9\.-]', '', 'g'), '')::numeric, 1),
    coalesce(item.value ->> 'unit', 'each'),
    nullif(regexp_replace(coalesce(item.value ->> 'unit_price', ''), '[^0-9\.-]', '', 'g'), '')::numeric,
    nullif(regexp_replace(coalesce(item.value ->> 'price', ''), '[^0-9\.-]', '', 'g'), '')::numeric,
    coalesce(item.value ->> 'source', 'printed'),
    nullif(regexp_replace(coalesce(item.value ->> 'confidence', ''), '[^0-9\.-]', '', 'g'), '')::numeric,
    case
        when item.value ? 'explicit_quantity' and nullif(item.value ->> 'explicit_quantity', '') is not null
            then (item.value ->> 'explicit_quantity')::boolean
        else false
    end,
    item.value
from public.receipts r
cross join lateral jsonb_array_elements(coalesce(r.items::jsonb, '[]'::jsonb)) with ordinality as item(value, ordinality)
where not exists (
    select 1
    from public.receipt_items ri
    where ri.receipt_id = r.id
      and ri.line_index = item.ordinality - 1
);
