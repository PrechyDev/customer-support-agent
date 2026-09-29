"""Fixed lines the caller hears when the agent can't give a normal answer (SPECS §11).

Kept in one place so they're easy to review. All are short, promise nothing and give no timelines.
Every line either asks the caller to do something now, or ends the call, so nobody is left in silence.
"""

# Vapi's assistant has both phrases in `endCallPhrases`: when the assistant says one, Vapi hangs up.
# END_CALL_PHRASE ends a call after a failure; GOODBYE is the normal end, said by the agent when the
# caller is done (the prompt tells it the exact words). Neither may appear in any other line.
END_CALL_PHRASE = "This call will now end."
# Warm and complete, with the trigger phrase as the LAST words: Vapi hangs up as soon as it's spoken.
GOODBYE = (
    "You're welcome, I'm glad I could help. If anything else comes up, you can reach us any time "
    "through your RelayPay dashboard. Have a great day, and thanks for calling RelayPay."
)

# Waiting ladder (SPECS §2b): spoken by the backend, not the model, only while no reply text has arrived.
FILLERS = ("One moment, please.", "Let me check on that.", "Just a second.")  # one, at random, at 2 s
FILLER_AFTER_SECONDS = 2.0
REASSURANCE = "Thanks for bearing with me, I'm still on it."
REASSURANCE_AFTER_SECONDS = 8.0
# The turn itself times out at AGENT_TURN_TIMEOUT_SECONDS (default 15, under Vapi's 20 s limit).

MAX_TURNS_FIRST = "Sorry, I didn't manage to finish that. Could you say it another way?"
MAX_TURNS_REPEAT = "I'm having trouble with this one. A specialist will need to help you."
TECHNICAL_PROBLEM = "Sorry, I had a technical problem. Could you say that again?"
TECHNICAL_GOODBYE = (
    "I'm sorry, I'm having technical problems and can't help right now. Please try again later, "
    f"or reach our support team through your RelayPay dashboard. {END_CALL_PHRASE}"
)
BUSY_GOODBYE = f"Sorry, we're very busy right now. Please call back in a few minutes. {END_CALL_PHRASE}"
EMPTY_REPLY = "Sorry, could you say that again?"

# Technical failures in a row before the call is ended (the first one asks the caller to repeat).
MAX_TECHNICAL_FAILURES = 2
