from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cyreneAI.core.errors.tool import ToolInputError, ToolPolicyError
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolPermission,
    ToolResult,
    ToolRiskLevel,
    ToolSafetyProfile,
)
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry
from cyreneAI.core.tool.tool_protocol import ToolExecutorProtocol


class FakeToolExecutor:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def execute(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=f"executed:{call.arguments}",
        )


class FakeSandboxRunner:
    async def execute(
        self,
        *,
        call: ToolCall,
        definition: ToolDefinition,
        executor: ToolExecutorProtocol,
        policy: ToolExecutionPolicy,
    ) -> ToolResult:
        result = await executor.execute(call)
        return result.model_copy(
            update={
                "metadata": {
                    **result.metadata,
                    "sandbox": {
                        "mode": "fake",
                        "tool_name": definition.name,
                        "allow_sandbox_bypass": policy.allow_sandbox_bypass,
                    },
                }
            }
        )


async def _run_tool_manager_execution() -> None:
    registry = ToolRegistry()
    executor = FakeToolExecutor()
    registry.register(
        ToolDefinition(
            name="lookup",
            description="Lookup a value.",
        ),
        executor,
    )
    manager = ToolManager(registry)
    call = ToolCall(
        id="call-1",
        name="lookup",
        arguments="{\"key\":\"value\"}",
    )

    result = await manager.execute(call)

    assert manager.exists("lookup")
    assert executor.calls == [call]
    assert result.call_id == "call-1"
    assert result.name == "lookup"
    assert result.content == "executed:{\"key\":\"value\"}"
    assert result.metadata["tool_policy"]["policy_enforced"] is True
    assert result.metadata["tool_policy"]["risk_level"] == "trusted"


def test_tool_manager_executes_registered_tool() -> None:
    asyncio.run(_run_tool_manager_execution())


async def _run_tool_manager_rejects_invalid_arguments() -> None:
    registry = ToolRegistry()
    executor = FakeToolExecutor()
    registry.register(
        ToolDefinition(
            name="lookup",
            description="Lookup a value.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["key"],
                "additionalProperties": False,
            },
        ),
        executor,
    )
    manager = ToolManager(registry)

    invalid_calls = [
        ToolCall(id="call-1", name="lookup", arguments="{}"),
        ToolCall(id="call-2", name="lookup", arguments="{\"key\": 1}"),
        ToolCall(
            id="call-3",
            name="lookup",
            arguments="{\"key\":\"value\",\"extra\":true}",
        ),
    ]

    for call in invalid_calls:
        with pytest.raises(ToolInputError):
            await manager.execute(call)

    assert executor.calls == []


def test_tool_manager_validates_arguments_against_parameters_schema() -> None:
    asyncio.run(_run_tool_manager_rejects_invalid_arguments())


async def _run_tool_manager_enforces_allowed_tool_names() -> None:
    registry = ToolRegistry()
    executor = FakeToolExecutor()
    registry.register(
        ToolDefinition(
            name="delete",
            description="Delete a value.",
        ),
        executor,
    )
    manager = ToolManager(registry)

    with pytest.raises(ToolPolicyError):
        await manager.execute(
            ToolCall(id="call-1", name="delete", arguments="{}"),
            policy=ToolExecutionPolicy(allowed_tool_names=["lookup"]),
        )

    assert executor.calls == []


def test_tool_manager_enforces_allowed_tool_names() -> None:
    asyncio.run(_run_tool_manager_enforces_allowed_tool_names())


async def _run_tool_manager_enforces_permissions_and_risk() -> None:
    registry = ToolRegistry()
    executor = FakeToolExecutor()
    registry.register(
        ToolDefinition(
            name="write_memory",
            description="Write memory.",
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.WRITE,
                permissions=[ToolPermission.MEMORY_WRITE],
            ),
        ),
        executor,
    )
    manager = ToolManager(registry)

    with pytest.raises(ToolPolicyError):
        await manager.execute(
            ToolCall(id="call-1", name="write_memory", arguments="{}"),
            policy=ToolExecutionPolicy(
                allowed_permissions=[ToolPermission.MEMORY_READ],
            ),
        )

    with pytest.raises(ToolPolicyError):
        await manager.execute(
            ToolCall(id="call-2", name="write_memory", arguments="{}"),
            policy=ToolExecutionPolicy(max_risk_level=ToolRiskLevel.READ_ONLY),
        )

    assert executor.calls == []


def test_tool_manager_enforces_permissions_and_risk() -> None:
    asyncio.run(_run_tool_manager_enforces_permissions_and_risk())


async def _run_tool_manager_blocks_sandbox_required_tools() -> None:
    registry = ToolRegistry()
    executor = FakeToolExecutor()
    registry.register(
        ToolDefinition(
            name="run_process",
            description="Run a process.",
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.PROCESS,
                permissions=[ToolPermission.SUBPROCESS],
                sandbox_required=True,
            ),
        ),
        executor,
    )
    manager = ToolManager(registry)

    with pytest.raises(ToolPolicyError):
        await manager.execute(
            ToolCall(id="call-1", name="run_process", arguments="{}"),
        )

    result = await manager.execute(
        ToolCall(id="call-2", name="run_process", arguments="{}"),
        policy=ToolExecutionPolicy(allow_sandbox_bypass=True),
    )

    assert result.metadata["tool_policy"]["sandbox_required"] is True
    assert result.metadata["tool_policy"]["allow_sandbox_bypass"] is True
    assert executor.calls == [
        ToolCall(id="call-2", name="run_process", arguments="{}")
    ]


def test_tool_manager_blocks_sandbox_required_tools() -> None:
    asyncio.run(_run_tool_manager_blocks_sandbox_required_tools())


async def _run_tool_manager_delegates_sandbox_required_tools() -> None:
    registry = ToolRegistry()
    executor = FakeToolExecutor()
    registry.register(
        ToolDefinition(
            name="run_process",
            description="Run a process.",
            safety_profile=ToolSafetyProfile(
                risk_level=ToolRiskLevel.PROCESS,
                permissions=[ToolPermission.SUBPROCESS],
                sandbox_required=True,
            ),
        ),
        executor,
    )
    manager = ToolManager(registry, sandbox_runner=FakeSandboxRunner())

    result = await manager.execute(
        ToolCall(id="call-1", name="run_process", arguments="{}"),
    )

    assert result.metadata["sandbox"]["mode"] == "fake"
    assert result.metadata["tool_policy"]["sandbox_used"] is True
    assert result.metadata["tool_policy"]["sandbox_mode"] == "fake"
    assert executor.calls == [
        ToolCall(id="call-1", name="run_process", arguments="{}")
    ]


def test_tool_manager_delegates_sandbox_required_tools() -> None:
    asyncio.run(_run_tool_manager_delegates_sandbox_required_tools())


async def _run_tool_manager_truncates_oversized_result() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="lookup",
            description="Lookup a value.",
            safety_profile=ToolSafetyProfile(max_output_chars=5),
        ),
        FakeToolExecutor(),
    )
    manager = ToolManager(registry)

    result = await manager.execute(
        ToolCall(id="call-1", name="lookup", arguments="{\"key\":\"value\"}"),
    )

    assert result.content == "execu"
    assert result.metadata["truncated"] is True
    assert result.metadata["original_content_chars"] == 24
    assert result.metadata["max_output_chars"] == 5


def test_tool_manager_truncates_oversized_result() -> None:
    asyncio.run(_run_tool_manager_truncates_oversized_result())


def test_core_tools_does_not_import_infra_or_external_sdks() -> None:
    tools_dir = Path(__file__).parents[1] / "core" / "tool"
    forbidden_patterns = [
        "cyreneAI.infra",
        "openai",
        "anthropic",
        "google.genai",
        "httpx",
        "dotenv",
        "os.getenv",
    ]

    for path in tools_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            assert pattern not in text
