from customer_support_agent.agent.phrase_check import flag_phrases


def test_flags_forbidden_phrases_but_not_correct_refusals():
    assert flag_phrases("I can't guarantee when it will arrive.") == []  # the right answer
    assert flag_phrases("Don't worry, we guarantee it will arrive by 9am.") == ["guarantee", "promised timing"]
    assert flag_phrases("It's on hold because of a compliance review.") == ["compliance reason"]
    assert flag_phrases("I have amara at lagosledger dot example on file.") == ["email read aloud"]
    assert flag_phrases("A specialist will follow up with you by email.") == []
