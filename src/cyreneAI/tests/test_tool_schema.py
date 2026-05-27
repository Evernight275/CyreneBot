from __future__ import annotations

from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.core.schema.tool import ToolResult


def test_tool_result_defaults_are_isolated() -> None:
    first = ToolResult(
        call_id="call-1",
        name="lookup",
        content="ok",
    )
    second = ToolResult(
        call_id="call-2",
        name="lookup",
    )

    first.metadata["key"] = "value"

    assert first.success is True
    assert first.error is None
    assert second.metadata == {}


def test_provider_config_repr_hides_api_key() -> None:
    config = ProviderConfig(
        provider_id="provider-1",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        api_key="secret-key",
    )

    assert "secret-key" not in repr(config)
