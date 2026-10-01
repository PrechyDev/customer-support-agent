-- Phase 3 additions (SPECS §9, §10). Safe to run more than once.

-- Verification attempts per call (max 2), and what the caller typed in the pre-call form.
alter table conversations add column if not exists verification_attempts integer not null default 0;
alter table conversations add column if not exists caller_name text;
alter table conversations add column if not exists caller_email text;
alter table conversations add column if not exists caller_company text;

-- Judgement calls the agent records (log_conversation_event), plus escalation_created from the tool.
create table if not exists conversation_events (
    id               bigint generated always as identity primary key,
    conversation_id  text not null,
    event_type       text not null check (event_type in ('sensitive_request', 'injection_attempt', 'verification_failed',
                                                         'caller_frustrated', 'escalation_created', 'other')),
    summary          text not null,
    metadata         jsonb not null default '{}',
    created_at       timestamptz not null default now()
);
alter table conversation_events enable row level security;
create index if not exists idx_events_conversation on conversation_events (conversation_id);

-- PRD "source summary" for retrieval records; tool latency for the evidence.
alter table retrieval_logs add column if not exists summaries text[] not null default '{}';
alter table tool_calls add column if not exists duration_ms integer;

create index if not exists idx_tickets_conversation on support_tickets (conversation_id);
create index if not exists idx_escalations_conversation on escalations (conversation_id);
