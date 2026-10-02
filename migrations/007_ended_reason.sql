-- Why a call ended, as Vapi reports it (endedReason), e.g. customer-ended-call, assistant-said-end-call-phrase.
-- A caller who hangs up mid-conversation is now closed as 'abandoned' (shown as "Caller hung up"), not 'ended'.
alter table conversations add column if not exists ended_reason text;
