import logging

from customer_support_agent.logging_setup import configure_logging


def test_repeat_calls_keep_one_handler_and_preserve_others(caplog):
    root = logging.getLogger()
    configure_logging("INFO")
    count = len(root.handlers)
    configure_logging("DEBUG")
    assert len(root.handlers) == count and root.level == logging.DEBUG
    logging.getLogger("x").warning("still captured")  # pytest's handler survived
    assert "still captured" in caplog.text
