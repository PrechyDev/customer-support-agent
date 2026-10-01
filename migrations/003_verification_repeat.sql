-- A repeated verification with the same details doesn't count as a new attempt (SPECS §3).
-- Stores a SHA-256 fingerprint of the last email + company tried, never the values themselves.
alter table conversations add column if not exists last_verification_try text;
