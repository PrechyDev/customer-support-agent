-- Support console: team members with roles, invites, case ownership and an activity timeline (docs/CONSOLE_API.md).
-- Safe to run more than once.

create table if not exists team_members (
    member_id          uuid primary key default gen_random_uuid(),
    email              text not null unique,          -- stored lowercase
    name               text,
    role               text not null check (role in ('superadmin', 'admin', 'support')),
    status             text not null default 'pending' check (status in ('pending', 'active', 'disabled')),
    password_hash      text,                          -- scrypt, never the password
    session_version    integer not null default 1,    -- bumped to sign someone out everywhere
    invite_token_hash  text,                          -- sha256 of the one-time link token, never the token
    invite_kind        text check (invite_kind in ('invite', 'reset')),
    invite_expires_at  timestamptz,
    invited_by         uuid references team_members (member_id),
    created_at         timestamptz not null default now(),
    activated_at       timestamptz,
    last_login_at      timestamptz
);
alter table team_members enable row level security;
create unique index if not exists idx_team_invite_token on team_members (invite_token_hash)
    where invite_token_hash is not null;
-- Only one superadmin can ever exist.
create unique index if not exists idx_team_one_superadmin on team_members (role) where role = 'superadmin';

alter table support_tickets add column if not exists owner_id uuid references team_members (member_id);
alter table escalations add column if not exists owner_id uuid references team_members (member_id);

create table if not exists case_events (
    id          bigint generated always as identity primary key,
    case_type   text not null check (case_type in ('ticket', 'escalation')),
    case_id     text not null,
    member_id   uuid references team_members (member_id),   -- null: the assistant or the system
    kind        text not null check (kind in ('note', 'take', 'assign', 'resolve', 'reopen')),
    text        text not null,
    created_at  timestamptz not null default now()
);
alter table case_events enable row level security;
create index if not exists idx_case_events_case on case_events (case_type, case_id);
create index if not exists idx_tickets_created on support_tickets (created_at);
create index if not exists idx_escalations_created on escalations (created_at);
create index if not exists idx_conversations_started on conversations (started_at);
