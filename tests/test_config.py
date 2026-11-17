import pytest

from app.config import Settings


def test_defaults_without_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEWSROOM_ENV", raising=False)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.env == "dev"
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.deepgram_api_key is None


def test_reads_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWSROOM_ENV", "test")
    monkeypatch.setenv("NEWSROOM_TAVILY_API_KEY", "tvly-fake-123")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.env == "test"
    assert s.tavily_api_key is not None
    assert s.tavily_api_key.get_secret_value() == "tvly-fake-123"


def test_empty_secret_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWSROOM_EXA_API_KEY", "")
    assert Settings(_env_file=None).exa_api_key is None  # type: ignore[call-arg]


def test_secrets_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWSROOM_CARTESIA_API_KEY", "sk-fake-secret")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert "sk-fake-secret" not in repr(s)
    assert "sk-fake-secret" not in s.model_dump_json()
