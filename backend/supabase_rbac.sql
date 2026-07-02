-- ReceiptAI role-based and scoped access control.
-- Safe to run repeatedly. Apply with the service role in the Supabase SQL editor.
create extension if not exists pgcrypto;

create table if not exists public.customers (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  kind text not null default 'personal' check (kind in ('personal', 'organization')),
  created_by uuid null references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);
alter table public.customers add column if not exists slug text null;
create unique index if not exists customers_slug_idx on public.customers(slug) where slug is not null;
create unique index if not exists customers_personal_owner_idx
  on public.customers(created_by) where kind = 'personal' and created_by is not null;

create table if not exists public.rbac_roles (
  role_key text primary key,
  display_name text not null,
  description text not null default '',
  is_system boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.rbac_permissions (
  permission_key text primary key,
  description text not null default ''
);

create table if not exists public.rbac_role_permissions (
  role_key text not null references public.rbac_roles(role_key) on delete cascade,
  permission_key text not null references public.rbac_permissions(permission_key) on delete cascade,
  primary key (role_key, permission_key)
);

create table if not exists public.rbac_user_roles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  role_key text not null references public.rbac_roles(role_key) on delete cascade,
  customer_id uuid null references public.customers(id) on delete cascade,
  assigned_by uuid null references auth.users(id) on delete set null,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  unique nulls not distinct (user_id, role_key, customer_id)
);
create index if not exists rbac_user_roles_user_idx on public.rbac_user_roles(user_id, active);
create index if not exists rbac_user_roles_customer_idx on public.rbac_user_roles(customer_id, role_key, active);

create table if not exists public.support_access_grants (
  id uuid primary key default gen_random_uuid(),
  support_user_id uuid not null references auth.users(id) on delete cascade,
  customer_id uuid null references public.customers(id) on delete cascade,
  receipt_id bigint null references public.receipts(id) on delete cascade,
  case_id text not null,
  reason text not null,
  permissions text[] not null default array['receipts.read']::text[],
  approved_by uuid not null references auth.users(id) on delete restrict,
  starts_at timestamptz not null default now(),
  expires_at timestamptz not null,
  revoked_at timestamptz null,
  revoked_by uuid null references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  check (customer_id is not null or receipt_id is not null),
  check (expires_at > starts_at)
);
create index if not exists support_access_active_idx
  on public.support_access_grants(support_user_id, expires_at)
  where revoked_at is null;

create table if not exists public.receipt_assignments (
  id uuid primary key default gen_random_uuid(),
  assignee_user_id uuid not null references auth.users(id) on delete cascade,
  receipt_id bigint not null references public.receipts(id) on delete cascade,
  permissions text[] not null default array['receipts.read','receipts.correct_items']::text[],
  assigned_by uuid not null references auth.users(id) on delete restrict,
  expires_at timestamptz null,
  revoked_at timestamptz null,
  created_at timestamptz not null default now(),
  unique (assignee_user_id, receipt_id)
);
create index if not exists receipt_assignments_active_idx
  on public.receipt_assignments(assignee_user_id, receipt_id)
  where revoked_at is null;

create table if not exists public.access_audit_log (
  id bigint generated always as identity primary key,
  actor_user_id uuid null references auth.users(id) on delete set null,
  action text not null,
  resource_type text not null,
  resource_id text null,
  customer_id uuid null references public.customers(id) on delete set null,
  reason text null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists access_audit_actor_idx on public.access_audit_log(actor_user_id, created_at desc);
create index if not exists access_audit_customer_idx on public.access_audit_log(customer_id, created_at desc);

alter table public.receipts add column if not exists customer_id uuid null references public.customers(id) on delete cascade;
alter table public.receipt_items add column if not exists customer_id uuid null references public.customers(id) on delete cascade;
alter table public.support_access_grants add column if not exists revoked_by uuid null references auth.users(id) on delete set null;
create index if not exists receipts_customer_idx on public.receipts(customer_id, created_at desc);
create index if not exists receipt_items_customer_idx on public.receipt_items(customer_id, receipt_created_at desc);

insert into public.rbac_roles(role_key, display_name, description) values
  ('platform_admin', 'Platform Admin', 'Full platform administration and audited customer-data access.'),
  ('master_user', 'Master User', 'Cross-customer receipt, report, and analytics access.'),
  ('customer_owner', 'Customer Owner', 'Manages one customer workspace and its members.'),
  ('customer_user', 'Customer User', 'Manages only personally owned receipts.'),
  ('support_agent', 'Support Agent', 'Accesses only explicitly approved support cases.'),
  ('receipt_editor', 'Receipt Editor', 'Corrects only assigned receipts or customers.'),
  ('auditor', 'Read-only Auditor', 'Reads assigned records and audit history.'),
  ('service_account', 'Service Account', 'Runs explicitly authorized API/background operations.')
on conflict (role_key) do update set display_name=excluded.display_name, description=excluded.description;

insert into public.rbac_permissions(permission_key, description) values
  ('users.read','Read users and memberships'), ('users.manage','Create, update, disable, and assign users'),
  ('roles.manage','Manage role permission mappings'), ('settings.manage','Manage platform settings'),
  ('receipts.upload','Upload and scan receipts'), ('receipts.read','Read receipt data'),
  ('receipts.update','Update receipt metadata'), ('receipts.delete','Delete receipts'),
  ('receipts.correct_items','Correct extracted receipt items'), ('receipts.reprocess','Reprocess receipt extraction'),
  ('receipts.view_image','View private receipt evidence'),
  ('analytics.read_own','Read personal analytics'), ('analytics.read_customer','Read customer analytics'),
  ('analytics.read_global','Read cross-customer analytics'), ('reports.export','Export reports'),
  ('support.request_access','Request scoped support access'), ('support.approve_access','Approve scoped support access'),
  ('audit.read','Read access and correction audit history')
on conflict (permission_key) do update set description=excluded.description;

-- System role grants. Custom roles may be created and mapped later.
insert into public.rbac_role_permissions(role_key, permission_key)
select 'platform_admin', permission_key from public.rbac_permissions on conflict do nothing;
insert into public.rbac_role_permissions(role_key, permission_key) values
  ('master_user','users.read'),('master_user','receipts.read'),('master_user','receipts.update'),
  ('master_user','receipts.delete'),('master_user','receipts.correct_items'),('master_user','receipts.view_image'),
  ('master_user','analytics.read_customer'),('master_user','analytics.read_global'),('master_user','reports.export'),
  ('master_user','support.approve_access'),('master_user','audit.read'),
  ('customer_owner','users.read'),('customer_owner','users.manage'),('customer_owner','receipts.upload'),
  ('customer_owner','receipts.read'),('customer_owner','receipts.update'),('customer_owner','receipts.delete'),
  ('customer_owner','receipts.correct_items'),('customer_owner','receipts.view_image'),
  ('customer_owner','analytics.read_own'),('customer_owner','analytics.read_customer'),
  ('customer_owner','support.approve_access'),('customer_owner','audit.read'),
  ('customer_user','receipts.upload'),('customer_user','receipts.read'),('customer_user','receipts.update'),
  ('customer_user','receipts.delete'),('customer_user','receipts.correct_items'),
  ('customer_user','receipts.view_image'),('customer_user','analytics.read_own'),
  ('support_agent','support.request_access'),
  ('receipt_editor','receipts.read'),('receipt_editor','receipts.update'),('receipt_editor','receipts.correct_items'),
  ('auditor','receipts.read'),('auditor','audit.read'),
  ('service_account','receipts.upload'),('service_account','receipts.read'),('service_account','receipts.reprocess')
on conflict do nothing;

-- Personal customer workspace for every existing account.
insert into public.customers(name, kind, created_by)
select coalesce(nullif(raw_user_meta_data->>'name',''), split_part(email,'@',1), 'Personal') || '''s receipts', 'personal', id
from auth.users
on conflict (created_by) where kind='personal' and created_by is not null do nothing;

insert into public.rbac_user_roles(user_id, role_key, customer_id, assigned_by)
select c.created_by, 'customer_user', c.id, c.created_by from public.customers c
where c.kind='personal' and c.created_by is not null
on conflict (user_id, role_key, customer_id) do nothing;

update public.receipts r set customer_id=c.id
from public.customers c where r.customer_id is null and r.user_id=c.created_by and c.kind='personal';
update public.receipt_items ri set customer_id=r.customer_id
from public.receipts r where ri.customer_id is null and ri.receipt_id=r.id;

create or replace function public.receiptai_create_personal_workspace()
returns trigger language plpgsql security definer set search_path=public as $$
declare cid uuid;
begin
  insert into public.customers(name,kind,created_by)
  values (coalesce(nullif(new.raw_user_meta_data->>'name',''),split_part(new.email,'@',1),'Personal') || '''s receipts','personal',new.id)
  on conflict (created_by) where kind='personal' and created_by is not null do update set name=excluded.name
  returning id into cid;
  insert into public.rbac_user_roles(user_id,role_key,customer_id,assigned_by)
  values(new.id,'customer_user',cid,new.id) on conflict do nothing;
  return new;
end $$;
drop trigger if exists receiptai_auth_user_workspace on auth.users;
create trigger receiptai_auth_user_workspace after insert on auth.users
for each row execute function public.receiptai_create_personal_workspace();

alter table public.customers enable row level security;
alter table public.rbac_roles enable row level security;
alter table public.rbac_permissions enable row level security;
alter table public.rbac_role_permissions enable row level security;
alter table public.rbac_user_roles enable row level security;
alter table public.support_access_grants enable row level security;
alter table public.receipt_assignments enable row level security;
alter table public.access_audit_log enable row level security;

drop policy if exists "Users read own role assignments" on public.rbac_user_roles;
create policy "Users read own role assignments" on public.rbac_user_roles for select to authenticated
using (user_id=auth.uid());
drop policy if exists "Users read assigned support grants" on public.support_access_grants;
create policy "Users read assigned support grants" on public.support_access_grants for select to authenticated
using (support_user_id=auth.uid() or approved_by=auth.uid());
drop policy if exists "Users read own receipt assignments" on public.receipt_assignments;
create policy "Users read own receipt assignments" on public.receipt_assignments for select to authenticated
using (assignee_user_id=auth.uid() or assigned_by=auth.uid());

-- Bootstrap the first platform administrator after replacing the UUID:
-- insert into public.rbac_user_roles(user_id,role_key,customer_id,assigned_by)
-- values ('USER_UUID','platform_admin',null,'USER_UUID') on conflict do nothing;
