-- Optional labeled receipt identifiers. Never store full card numbers or auth codes.
alter table public.receipts
  add column if not exists transaction_number text,
  add column if not exists receipt_number text,
  add column if not exists invoice_number text,
  add column if not exists order_number text;

create index if not exists receipts_transaction_number_idx
  on public.receipts(user_id, transaction_number)
  where transaction_number is not null;

create index if not exists receipts_receipt_number_idx
  on public.receipts(user_id, receipt_number)
  where receipt_number is not null;
