"""Fixed lines the caller hears when the agent can't give a normal answer (SPECS §11).

Kept in one place so they're easy to review. All are short, promise nothing and give no timelines.
Every line either asks the caller to do something now, or ends the call, so nobody is left in silence.
"""

# Vapi's assistant has endCallPhrases = ["goodbye"]: when the assistant says it, Vapi hangs up.
# One word, because Vapi splits text into pieces and a longer phrase can be split mid-way and not match.
# Every line that should end the call ends with it; no other line may contain it.
END_CALL_PHRASE = "Goodbye."
# Said by the backend (which has no context of how the call went), so no "glad I could help".
GOODBYE = (
    "If anything else comes up, you can reach us any time through your RelayPay dashboard. "
    f"Have a great day, and thanks for calling RelayPay. {END_CALL_PHRASE}"
)

# Waiting (SPECS §2b): no filler. Answers take 2-5 s, and a filler landed right before the answer
# anyway. Only a genuinely slow turn gets one line from the backend, while no reply text has arrived.
REASSURANCE = "Thanks for bearing with me, I'm still on it."
REASSURANCE_AFTER_SECONDS = 10.0
# The turn itself times out at AGENT_TURN_TIMEOUT_SECONDS (default 15, under Vapi's 20 s limit).

MAX_TURNS_FIRST = "Sorry, I didn't manage to finish that. Could you say it another way?"
# Second time in a call: the backend escalates automatically if it knows who to follow up with.
MAX_TURNS_ESCALATED = ("I'm having trouble with this one, so I've passed it to a specialist, "
                       "who will follow up with you by email.")
MAX_TURNS_REPEAT = ("I'm having trouble with this one. Please contact our support team through your "
                    "RelayPay dashboard, and they'll help you.")
TECHNICAL_PROBLEM = "Sorry, I had a technical problem. Could you say that again?"
TECHNICAL_GOODBYE = (
    "I'm sorry, I'm having technical problems and can't help right now. Please try again later, "
    f"or reach our support team through your RelayPay dashboard. {END_CALL_PHRASE}"
)
BUSY_GOODBYE = f"Sorry, we're very busy right now. Please call back in a few minutes. {END_CALL_PHRASE}"
EMPTY_REPLY = "Sorry, could you say that again?"

# A message that's only thinking sounds ("um, I"): held this long so Vapi can resend the full sentence;
# if it doesn't, this short line hands the turn back without talking over the caller.
FILLER_WAIT_SECONDS = 3.0
FILLER_ACK = "Mm-hm?"

# A caller message longer than this never reaches Claude (cost guard if the Vapi secret leaked).
# 2,000 characters is about 350 words, over two minutes of non-stop speech: real callers never get near it.
MAX_MESSAGE_CHARS = 2000
TOO_LONG = "Sorry, that was a lot to take in at once. Could you tell me the main thing you need help with?"

# Technical failures in a row before the call is ended (the first one asks the caller to repeat).
# These engine errors can't be fixed by repeating, so they end the call at once.
UNRECOVERABLE_API_ERRORS = ("billing_error", "authentication_failed")
MAX_TECHNICAL_FAILURES = 2
