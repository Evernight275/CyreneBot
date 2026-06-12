from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from typing import Any

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from cyreneAI.application.bootstrap import build_cyrene_ai_runtime
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.application.tools.execution_context import use_tool_execution_context
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.core.schema.skill import SkillDefinition
from cyreneAI.core.schema.tool import ToolCall
from cyreneAI.core.skill.manager import SkillManager
from cyreneAI.core.skill.registry import SkillRegistry
from cyreneAI.infra.adapters.vector_stores.memory.store import InMemoryVectorStore
from cyreneAI.infra.bootstrap.registrations.openai_compatible import (
    register_openai_compatible_provider,
)
from cyreneAI.infra.bootstrap.registrations.openai_responses import (
    register_openai_responses_provider,
)
from cyreneAI.server import create_app
from cyreneAI.server.config import ServerSettings

_SESSION_ID = "real-agent-smoke"
_SKILL_NAME = "agent_smoke_skill"
_MEMORY_NAMESPACE = "real-agent-smoke"
_SKIPPABLE_HTTP_STATUSES = {400, 422, 502, 503, 504}


def _skip(reason: str) -> None:
    print(f"openai-compatible real agent smoke skipped: {reason}")
    pytest.skip(reason)


def _skip_if_configured_endpoint_rejected(response) -> None:
    if response.status_code not in _SKIPPABLE_HTTP_STATUSES:
        return
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = response.text
    _skip(
        "configured endpoint rejected or could not complete the real Agent "
        f"smoke request: {detail}"
    )


def _load_real_agent_config() -> ProviderConfig:
    load_dotenv()

    compatible_api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY") or os.getenv(
        "OPENAI_API_KEY"
    )
    compatible_model = os.getenv("OPENAI_COMPATIBLE_MODEL") or os.getenv("OPENAI_MODEL")
    if compatible_api_key and compatible_model:
        return ProviderConfig(
            provider_id=os.getenv(
                "OPENAI_COMPATIBLE_PROVIDER_ID",
                "real-openai-compatible-agent-smoke",
            ),
            provider_type=ProviderType.OPENAI_COMPATIBLE,
            api_key=compatible_api_key,
            base_url=os.getenv("OPENAI_COMPATIBLE_BASE_URL")
            or os.getenv("OPENAI_BASE_URL"),
            timeout=timedelta(seconds=45),
            metadata={"model": compatible_model},
        )

    responses_api_key = os.getenv("OPENAI_RESPONSES_API_KEY") or os.getenv(
        "OPENAI_API_KEY"
    )
    responses_model = os.getenv("OPENAI_RESPONSES_MODEL") or os.getenv("OPENAI_MODEL")
    if responses_api_key and responses_model:
        return ProviderConfig(
            provider_id=os.getenv(
                "OPENAI_RESPONSES_PROVIDER_ID",
                "real-openai-responses-agent-smoke",
            ),
            provider_type=ProviderType.OPENAI_RESPONSES,
            api_key=responses_api_key,
            base_url=os.getenv("OPENAI_RESPONSES_BASE_URL")
            or os.getenv("OPENAI_BASE_URL"),
            timeout=timedelta(seconds=45),
            metadata={"model": responses_model},
        )

    _skip(
        "OPENAI_COMPATIBLE_API_KEY/OPENAI_RESPONSES_API_KEY or OPENAI_API_KEY "
        "and a matching model are required"
    )


async def _build_runtime(
    *,
    config: ProviderConfig,
) -> CyreneAIRuntime:
    registry = ProviderRegistry()
    factory = ProviderFactory()
    if config.provider_type == ProviderType.OPENAI_RESPONSES:
        register_openai_responses_provider(registry, factory)
    else:
        register_openai_compatible_provider(registry, factory)

    manager = ProviderManager(factory)
    await manager.add(config)

    skill_registry = SkillRegistry()
    skill_registry.register(
        SkillDefinition(
            name=_SKILL_NAME,
            description="Guide the real Agent smoke test.",
            instructions=(
                "Use the requested tools when available. Mention the phrase "
                "agent smoke skill when summarizing."
            ),
            allowed_tools=["get_current_time", "search_memory"],
        )
    )

    return await build_cyrene_ai_runtime(
        provider_manager=manager,
        skill_manager=SkillManager(skill_registry),
        vector_store=InMemoryVectorStore(),
        register_builtin_plugins=False,
    )


async def _store_smoke_memory(
    runtime: CyreneAIRuntime,
    *,
    provider_id: str,
    model: str,
) -> None:
    assert runtime.tool_manager is not None
    with use_tool_execution_context(
        session_id=_SESSION_ID,
        provider_id=provider_id,
        model=model,
    ):
        result = await runtime.tool_manager.execute(
            ToolCall(
                id="remember-real-agent-smoke",
                name="remember_fact",
                arguments=json.dumps(
                    {
                        "content": (
                            "CyreneAI real agent smoke memory marker is amber."
                        ),
                        "namespace": _MEMORY_NAMESPACE,
                        "memory_id": "memory:real-agent-smoke:amber",
                    }
                ),
            )
        )
    assert result.success is True


def test_openai_compatible_real_agent_http_smoke() -> None:
    config = _load_real_agent_config()
    model = str(config.metadata["model"])
    runtime = asyncio.run(_build_runtime(config=config))
    try:
        asyncio.run(
            _store_smoke_memory(
                runtime,
                provider_id=config.provider_id,
                model=model,
            )
        )
        client = TestClient(
            create_app(
                runtime,
                settings=ServerSettings(auth_enabled=False),
            )
        )
        with client:
            response = client.post(
                "/agents/run",
                json={
                    "provider_id": config.provider_id,
                    "model": model,
                    "goal": (
                        "Use get_current_time, then answer from the retrieved "
                        "memory marker. Mention agent smoke skill."
                    ),
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "Run the real Agent smoke check. Use the time "
                                "tool and the memory marker."
                            ),
                        }
                    ],
                    "max_steps": 1,
                    "required_skill_names": [_SKILL_NAME],
                    "max_skills": 1,
                    "planning": {
                        "enabled": True,
                        "instructions": (
                            "planner_step: use selected skill, tool, and memory."
                        ),
                    },
                    "tool_selection": {
                        "allowed_tool_names": [
                            "get_current_time",
                            "search_memory",
                        ]
                    },
                    "memory_retrieval": {
                        "enabled": True,
                        "query": "CyreneAI real agent smoke memory marker amber",
                        "namespace": _MEMORY_NAMESPACE,
                        "top_k": 1,
                    },
                    "tool_choice": {
                        "mode": "tool",
                        "name": "get_current_time",
                    },
                    "temperature": 0,
                    "max_tokens": 192,
                    "metadata": {"session_id": _SESSION_ID},
                },
            )

        _skip_if_configured_endpoint_rejected(response)
        assert response.status_code == 200

        payload: dict[str, Any] = response.json()
        first_step = payload["steps"][0]
        if not first_step["tool_calls"]:
            pytest.skip(f"{model} did not return tool_calls for the real Agent smoke")
        if not any(
            result["name"] == "get_current_time"
            for result in first_step["tool_results"]
        ):
            pytest.skip(f"{model} did not execute get_current_time for the smoke")

        assert payload["stop_reason"] == "max_steps"
        assert (
            payload["steps"][1]["request"]["metadata"]["agent_max_steps_finalization"]
            is True
        )
        assert payload["plan"]["metadata"]["planning_mode"] == "planner_step"
        assert payload["plan"]["steps"]
        assert payload["plan"]["metadata"]["memory_match_count"] >= 1
        assert payload["skill_bundle"]["metadata"]["skills"] == [_SKILL_NAME]

        memory_segments = [
            segment
            for segment in payload["context_snapshot"]["window"]["segments"]
            if segment["role"] == "memory"
        ]
        assert memory_segments
        assert "amber" in memory_segments[0]["items"][0]["content"]

        message = payload["response"]["message"]
        assert message is not None
        assert message["content"][0]["text"]
    finally:
        asyncio.run(runtime.close())
