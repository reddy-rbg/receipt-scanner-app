-- Persistent, owner-scoped agent chat history.
create table if not exists public.agent_conversation_messages (
  id bigint generated always as identity primary key,
  user_id uuid null references auth.users(id) on delete cascade,
  guest_session_id text null,
  session_id text not null,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  created_at timestamptz not null default now(),
  check (user_id is not null or guest_session_id is not null)
);

create index if not exists agent_conversation_user_session_idx
  on public.agent_conversation_messages(user_id, session_id, created_at desc)
  where user_id is not null;

create index if not exists agent_conversation_guest_session_idx
  on public.agent_conversation_messages(guest_session_id, session_id, created_at desc)
  where guest_session_id is not null;

alter table public.agent_conversation_messages enable row level security;
revoke all on table public.agent_conversation_messages from anon;
grant select, insert, delete on table public.agent_conversation_messages to authenticated;

drop policy if exists "Users manage own agent messages" on public.agent_conversation_messages;
create policy "Users manage own agent messages"
  on public.agent_conversation_messages
  for all
  to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
