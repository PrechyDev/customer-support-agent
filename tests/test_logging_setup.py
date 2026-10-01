import json
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


def test_log_file_gets_a_copy_of_the_log(tmp_path):
    log_file = tmp_path / "logs" / "backend.log"  # folder doesn't exist yet
    configure_logging("INFO", log_file)
    logging.getLogger("x").info("written to the file too")
    configure_logging("INFO")  # closes the file handler
    assert "written to the file too" in log_file.read_text(encoding="utf-8")


def test_json_format_writes_one_object_per_line(tmp_path):
    log_file = tmp_path / "backend.log"
    configure_logging("INFO", log_file, "json")
    logging.getLogger("relaypay.x").warning("disk at %s%%", 91)
    configure_logging("INFO")
    entry = json.loads(log_file.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert entry["severity"] == "WARNING" and entry["message"] == "disk at 91%" and entry["logger"] == "relaypay.x"
