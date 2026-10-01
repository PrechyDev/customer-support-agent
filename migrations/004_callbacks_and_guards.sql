-- Callbacks by phone, reference-guessing guard, unverified tickets (SPECS §5, §6). Safe to run more than once.

-- A callback needs a number: from the pre-call form (optional field) or said on the call.
alter table conversations add column if not exists caller_phone text;
alter table escalations add column if not exists callback_phone text;
alter table escalations add column if not exists contact_method text not null default 'email';
do $$ begin
    alter table escalations add constraint escalations_contact_method_check check (contact_method in ('email', 'call'));
exception when duplicate_object then null; end $$;

-- References not found on this call: after 3, lookups stop (someone may be guessing references).
alter table conversations add column if not exists lookup_misses integer not null default 0;

-- Staff can see when a ticket came from a caller who wasn't verified (e.g. a reference someone else gave).
alter table support_tickets add column if not exists caller_verified boolean not null default false;
