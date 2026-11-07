from app.models.ai.llm import LlmModel
from app.services.run.options import _settings_with_thinking, _supported_thinking_level


def _model(levels: list[str]) -> LlmModel:
    return LlmModel(
        name="thinking-test",
        provider="openai",
        model_name="mock",
        thinking_levels=levels,
    )


def test_thinking_level_must_be_declared_by_model() -> None:
    model = _model(["low", "high"])
    assert _supported_thinking_level(model, "high") == "high"
    assert _supported_thinking_level(model, "medium") is None
    assert _supported_thinking_level(model, None) is None


def test_thinking_level_is_written_into_model_settings() -> None:
    assert _settings_with_thinking({"timeout": 3}, "medium") == {
        "timeout": 3,
        "thinking": "medium",
    }
    assert _settings_with_thinking({"timeout": 3}, None) == {"timeout": 3}
