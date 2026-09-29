import logging

from customer_support_agent.logging_setup import configure_logging


def test_calling_twice_leaves_one_handler_of_ours():
    root = logging.getLogger()
    configure_logging("INFO")
    after_first = len(root.handlers)
    configure_logging("DEBUG")
    assert len(root.handlers) == after_first
    assert root.level == logging.DEBUG


def test_other_handlers_are_kept(caplog):
    configure_logging("INFO")
    logging.getLogger("x").warning("still captured")
    assert "still captured" in caplog.text
