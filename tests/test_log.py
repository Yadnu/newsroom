import json

import pytest
import structlog

from app.config import Settings
from app.log import REDACTED, configure_logging, get_logger


def test_json_log_line_redacts_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(_env_file=None, log_json=True))  # type: ignore[call-arg]
    get_logger("t").info("call", component="reporter", api_key="sk-fake", briefing_id="b1")
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["event"] == "call"
    assert line["component"] == "reporter"
    assert line["briefing_id"] == "b1"
    assert line["api_key"] == REDACTED
    assert line["level"] == "info"
    structlog.reset_defaults()


def test_level_filtering(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings(_env_file=None, log_level="WARNING"))  # type: ignore[call-arg]
    get_logger("t").info("hidden")
    assert capsys.readouterr().out == ""
    structlog.reset_defaults()
