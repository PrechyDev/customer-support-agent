-- Voice page rating and console resolve (FRONTEND_PLAN §6). Safe to run more than once.

-- "Did this help?" on the voice page: saved once per call.
alter table conversations add column if not exists rating text check (rating in ('yes', 'no'));
alter table conversations add column if not exists rated_at timestamptz;

-- Resolving a case in the console needs a note.
alter table support_tickets add column if not exists resolved_at timestamptz;
alter table support_tickets add column if not exists resolution_note text;
alter table escalations add column if not exists resolved_at timestamptz;
alter table escalations add column if not exists resolution_note text;
