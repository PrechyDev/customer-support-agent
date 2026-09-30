-- RelayPay support agent schema (SPECS §10). Safe to run more than once.
-- Access: only our server, through DATABASE_URL. RLS is on for every table with NO policies,
-- so Supabase's public REST API (anon/authenticated keys) can read or write nothing.

-- ---------------------------------------------------------------------------
-- Seed data (loaded from data/seed/*.csv)
-- ---------------------------------------------------------------------------

create table if not exists customers (
    customer_id     text primary key,
    company_name    text not null,
    contact_name    text not null,
    contact_email   text not null unique,
    plan            text not null check (plan in ('Starter', 'Growth', 'Scale')),
    account_status  text not null check (account_status in ('active', 'restricted', 'pending verification')),
    region          text not null,
    kyc_status      text not null check (kyc_status in ('pending', 'approved', 'review required')),
    support_notes   text not null default ''
);

create table if not exists transactions (
    transaction_id      text primary key,
    customer_id         text not null references customers (customer_id),
    transaction_type    text not null check (transaction_type in ('incoming transfer', 'outgoing payout', 'invoice payment')),
    amount              numeric(14, 2) not null check (amount >= 0),
    currency            text not null check (char_length(currency) = 3),
    destination_country text,
    status              text not null check (status in ('processing', 'completed', 'delayed', 'failed', 'review required')),
    created_at          date not null,
    estimated_arrival   date,  -- null for failed / review required
    support_summary     text not null default ''
);

create table if not exists payouts (
    payout_id       text primary key,
    transaction_id  text not null references transactions (transaction_id),
    customer_id     text not null references customers (customer_id),
    recipient_name  text not null,
    amount          numeric(14, 2) not null check (amount >= 0),
    currency        text not null check (char_length(currency) = 3),
    status          text not null check (status in ('scheduled', 'processing', 'completed', 'failed', 'review required')),
    scheduled_for   date,
    failure_reason  text  -- customer-safe reason; never spoken (SPECS §5)
);

-- ---------------------------------------------------------------------------
-- Runtime records (written by the backend and MCP tools)
-- ---------------------------------------------------------------------------

create table if not exists conversations (
    conversation_id       text primary key,  -- Vapi call ID
    channel               text not null default 'voice',
    caller_identifier     text,
    verified_customer_id  text references customers (customer_id),
    model                 text,
    started_at            timestamptz not null default now(),
    ended_at              timestamptz,
    final_status          text not null default 'in_progress'
                          check (final_status in ('in_progress', 'answered', 'clarified', 'escalated', 'declined', 'ended', 'abandoned')),
    summary               text
);

create table if not exists conversation_turns (
    id                   bigint generated always as identity primary key,
    conversation_id      text not null references conversations (conversation_id),
    user_transcript      text not null,
    assistant_response   text not null,
    answer_type          text not null check (answer_type in ('answer', 'clarify', 'escalate', 'decline', 'fallback')),
    confidence_note      text,
    first_text_ms        integer,
    total_ms             integer,
    created_at           timestamptz not null default now()
);

create table if not exists retrieval_logs (
    id               bigint generated always as identity primary key,
    conversation_id  text not null,
    query            text not null,
    chunk_ids        text[] not null default '{}',
    titles           text[] not null default '{}',
    scores           numeric[] not null default '{}',
    duration_ms      numeric,
    created_at       timestamptz not null default now()
);

create table if not exists tool_calls (
    id               bigint generated always as identity primary key,
    conversation_id  text not null,
    tool_name        text not null,
    purpose          text,
    input_summary    text,
    result_summary   text,
    status           text not null check (status in ('ok', 'error')),
    error_message    text,
    created_at       timestamptz not null default now()
);

-- Speakable references for callers: T-1001, E-1001 (SPECS §6)
create sequence if not exists ticket_number_seq start 1001;
create sequence if not exists escalation_number_seq start 1001;

create table if not exists support_tickets (
    ticket_id        text primary key default ('T-' || nextval('ticket_number_seq')),
    conversation_id  text not null,
    customer_id      text references customers (customer_id),
    category         text not null check (category in ('compliance', 'account', 'dispute', 'payment', 'other')),
    priority         text not null check (priority in ('high', 'medium', 'low')),
    summary          text not null,
    reference        text not null default '',  -- transaction / payout ID if any ('' = none)
    status           text not null default 'open' check (status in ('open', 'in progress', 'closed')),
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    -- one ticket per conversation, category and reference: a repeat or a retry returns the existing one
    unique (conversation_id, category, reference)
);

create table if not exists escalations (
    escalation_id       text primary key default ('E-' || nextval('escalation_number_seq')),
    ticket_id           text references support_tickets (ticket_id),
    conversation_id     text not null,
    customer_id         text references customers (customer_id),
    user_name           text not null,
    user_email          text not null,
    category            text not null check (category in ('compliance', 'account', 'dispute', 'payment', 'other')),
    reason              text not null,
    verified            boolean not null default false,
    call_booked         boolean not null default false,  -- a callback window was captured (a request, not a booking)
    preferred_time_raw  text,                            -- as the caller said it ("tomorrow afternoon, Lagos")
    callback_timezone   text,
    callback_start_utc  timestamptz,
    callback_end_utc    timestamptz,
    status              text not null default 'open' check (status in ('open', 'in progress', 'closed')),
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    unique (conversation_id, category)
);

create table if not exists evaluations (
    id                 bigint generated always as identity primary key,
    run_id             text not null,
    scenario           text not null,
    expected_behavior  text not null,
    actual_behavior    text not null,
    passed             boolean not null,
    notes              text,
    created_at         timestamptz not null default now()
);

-- Indexes for the lookups the console and logs need
create index if not exists idx_turns_conversation on conversation_turns (conversation_id);
create index if not exists idx_tool_calls_conversation on tool_calls (conversation_id);
create index if not exists idx_retrieval_conversation on retrieval_logs (conversation_id);
create index if not exists idx_transactions_customer on transactions (customer_id);

-- Row Level Security: on everywhere, no policies => no access through Supabase's public API.
alter table customers enable row level security;
alter table transactions enable row level security;
alter table payouts enable row level security;
alter table conversations enable row level security;
alter table conversation_turns enable row level security;
alter table retrieval_logs enable row level security;
alter table tool_calls enable row level security;
alter table support_tickets enable row level security;
alter table escalations enable row level security;
alter table evaluations enable row level security;
