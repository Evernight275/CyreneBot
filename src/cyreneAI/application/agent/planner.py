from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

from cyreneAI.core.errors.base import ValidationError
from cyreneAI.core.schema.agent import (
    AgentMemoryRetrievalConfig,
    AgentPlan,
    AgentPlanConstraints,
    AgentPlanningConfig,
    AgentPlanningMode,
    AgentPlanStep,
    AgentRunRequest,
)
from cyreneAI.core.schema.chat import ChatRequest, ChatResponse
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.skill import SkillInstructionBundle
from cyreneAI.core.schema.tool import ToolDefinition

PlannerChatCallable = Callable[[ChatRequest], Awaitable[ChatResponse]]


class AgentPlanner:
    """
    Builds an auditable plan before the agent loop starts.
    """

    async def build_plan_with_model(
        self,
        *,
        request: AgentRunRequest,
        tools: list[ToolDefinition],
        skill_bundle: SkillInstructionBundle | None,
        chat: PlannerChatCallable,
    ) -> AgentPlan | None:
        planning = request.planning
        if not plan_enabled(planning):
            return None
        if planning.mode != AgentPlanningMode.LLM:
            return self.build_plan(
                request=request,
                tools=tools,
                skill_bundle=skill_bundle,
            )

        planner_provider_id = planning.planner_provider_id or request.provider_id
        planner_model = planning.planner_model or request.model
        planner_request = _build_llm_planner_request(
            request=request,
            tools=tools,
            skill_bundle=skill_bundle,
            planner_provider_id=planner_provider_id,
            planner_model=planner_model,
        )
        try:
            response = await chat(planner_request)
            return _llm_response_to_plan(
                request=request,
                tools=tools,
                skill_bundle=skill_bundle,
                response=response,
                planner_provider_id=planner_provider_id,
                planner_model=planner_model,
            )
        except Exception as exc:
            fallback = self.build_plan(
                request=request,
                tools=tools,
                skill_bundle=skill_bundle,
            )
            if fallback is None:
                return None
            fallback.metadata.update(
                {
                    "planning_fallback": True,
                    "planning_fallback_from": AgentPlanningMode.LLM.value,
                    "planning_error_type": exc.__class__.__name__,
                    "planning_error": str(exc),
                    "requested_planning_mode": AgentPlanningMode.LLM.value,
                    "planner_provider_id": planner_provider_id,
                    "planner_model": planner_model,
                }
            )
            return fallback

    def build_plan(
        self,
        *,
        request: AgentRunRequest,
        tools: list[ToolDefinition],
        skill_bundle: SkillInstructionBundle | None,
    ) -> AgentPlan | None:
        planning = request.planning
        if not plan_enabled(planning):
            return None
        if planning.mode == AgentPlanningMode.LLM:
            planning = planning.model_copy(
                update={"mode": AgentPlanningMode.RULE_BASED}
            )

        selected_tool_names = [tool.name for tool in tools]
        selected_skill_names = _selected_skill_names(skill_bundle)
        goal = request.goal or _messages_to_text(request.messages)
        memory_query = _memory_query(
            request=request,
            config=request.memory_retrieval,
        )
        objectives = _build_plan_objectives(
            goal=goal,
            planning=planning,
        )
        constraints = AgentPlanConstraints(
            selected_tool_names=selected_tool_names,
            denied_tool_names=(
                list(request.tool_selection.denied_tool_names)
                if request.tool_selection is not None
                else []
            ),
            required_skill_names=list(request.required_skill_names),
            selected_skill_names=selected_skill_names,
            max_skills=request.max_skills,
            metadata={
                "allowed_tool_count": len(selected_tool_names),
                "selected_skill_count": len(selected_skill_names),
            },
        )
        return AgentPlan(
            goal=goal or None,
            objectives=objectives,
            steps=_build_plan_steps(
                objectives=objectives,
                selected_tool_names=selected_tool_names,
                selected_skill_names=selected_skill_names,
                memory_query=memory_query,
            ),
            selected_tool_names=selected_tool_names,
            constraints=constraints,
            memory_query=memory_query,
            instructions=planning.instructions if planning is not None else None,
            metadata={
                "planning_enabled": True,
                "planning_mode": "planner_step",
                "selected_tool_count": len(selected_tool_names),
                "selected_skill_count": len(selected_skill_names),
            },
        )


def plan_enabled(planning: AgentPlanningConfig | None) -> bool:
    return planning is not None and planning.enabled


def _build_llm_planner_request(
    *,
    request: AgentRunRequest,
    tools: list[ToolDefinition],
    skill_bundle: SkillInstructionBundle | None,
    planner_provider_id: str,
    planner_model: str,
) -> ChatRequest:
    planning = request.planning
    payload = {
        "goal": request.goal,
        "messages": _messages_to_text(request.messages),
        "instructions": planning.instructions if planning is not None else None,
        "max_objectives": planning.max_objectives if planning is not None else 4,
        "max_plan_steps": planning.max_plan_steps if planning is not None else 6,
        "memory_query": _memory_query(
            request=request,
            config=request.memory_retrieval,
        ),
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
            }
            for tool in tools
        ],
        "constraints": {
            "selected_tool_names": [tool.name for tool in tools],
            "denied_tool_names": (
                list(request.tool_selection.denied_tool_names)
                if request.tool_selection is not None
                else []
            ),
            "required_skill_names": list(request.required_skill_names),
            "selected_skill_names": _selected_skill_names(skill_bundle),
            "max_skills": request.max_skills,
        },
    }
    replan_context = request.metadata.get("agent_replan_context")
    if isinstance(replan_context, dict):
        payload["replan_context"] = cast(dict[str, Any], replan_context)
    return ChatRequest(
        provider_id=planner_provider_id,
        model=planner_model,
        messages=[
            Message(
                role=MessageRole.SYSTEM,
                name="agent_planner",
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text=_LLM_PLANNER_SYSTEM_PROMPT,
                    )
                ],
            ),
            Message(
                role=MessageRole.USER,
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text=json.dumps(
                            payload,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    )
                ],
            ),
        ],
        temperature=0.0,
        stream=False,
        metadata={
            **request.metadata,
            "session_id": request.session_id,
            "agent_loop": "planner",
            "agent_planner": True,
            "agent_planner_mode": AgentPlanningMode.LLM.value,
        },
    )


_LLM_PLANNER_SYSTEM_PROMPT = (
    "You are the CyreneAI agent planner. Return only one JSON object. "
    "Use this shape: "
    '{"objectives":["..."],"steps":[{"objective":"...",'
    '"action":"...","tool_names":["tool"],"skill_names":["skill"]}]}. '
    "Use only tool_names and skill_names from the provided constraints. "
    "Keep objectives and actions concise. Do not call tools."
)


def _llm_response_to_plan(
    *,
    request: AgentRunRequest,
    tools: list[ToolDefinition],
    skill_bundle: SkillInstructionBundle | None,
    response: ChatResponse,
    planner_provider_id: str,
    planner_model: str,
) -> AgentPlan:
    payload = _parse_llm_plan_payload(response)
    planning = request.planning
    selected_tool_names = [tool.name for tool in tools]
    selected_skill_names = _selected_skill_names(skill_bundle)
    memory_query = _memory_query(
        request=request,
        config=request.memory_retrieval,
    )
    max_objectives = planning.max_objectives if planning is not None else 4
    max_plan_steps = planning.max_plan_steps if planning is not None else 6
    objectives = _payload_string_list(payload.get("objectives"))[:max_objectives]
    raw_steps = payload.get("steps")
    steps = _payload_plan_steps(
        raw_steps,
        selected_tool_names=selected_tool_names,
        selected_skill_names=selected_skill_names,
        max_plan_steps=max_plan_steps,
    )
    if not objectives:
        objectives = [
            step.objective
            for step in steps
            if step.objective and step.objective not in objectives
        ][:max_objectives]
    if not objectives:
        raise ValidationError("LLM planner response must include objectives or steps")
    if not steps:
        steps = _build_plan_steps(
            objectives=objectives,
            selected_tool_names=selected_tool_names,
            selected_skill_names=selected_skill_names,
            memory_query=memory_query,
        )[:max_plan_steps]

    constraints = AgentPlanConstraints(
        selected_tool_names=selected_tool_names,
        denied_tool_names=(
            list(request.tool_selection.denied_tool_names)
            if request.tool_selection is not None
            else []
        ),
        required_skill_names=list(request.required_skill_names),
        selected_skill_names=selected_skill_names,
        max_skills=request.max_skills,
        metadata={
            "allowed_tool_count": len(selected_tool_names),
            "selected_skill_count": len(selected_skill_names),
        },
    )
    return AgentPlan(
        goal=_payload_string(payload.get("goal")) or request.goal,
        objectives=objectives,
        steps=steps,
        selected_tool_names=selected_tool_names,
        constraints=constraints,
        memory_query=_payload_string(payload.get("memory_query")) or memory_query,
        instructions=planning.instructions if planning is not None else None,
        metadata={
            "planning_enabled": True,
            "planning_mode": AgentPlanningMode.LLM.value,
            "selected_tool_count": len(selected_tool_names),
            "selected_skill_count": len(selected_skill_names),
            "planner_provider_id": planner_provider_id,
            "planner_model": planner_model,
            "planner_finish_reason": response.finish_reason.value,
            "planner_response_had_message": response.message is not None,
        },
    )


def _parse_llm_plan_payload(response: ChatResponse) -> dict[str, Any]:
    text = _chat_response_text(response)
    if not text:
        raise ValidationError("LLM planner response is empty")
    try:
        payload = json.loads(_strip_json_markdown_fence(text))
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "LLM planner response must be valid JSON",
            cause=exc,
        ) from exc
    if not isinstance(payload, dict):
        raise ValidationError("LLM planner response must be a JSON object")
    return cast(dict[str, Any], payload)


def _chat_response_text(response: ChatResponse) -> str:
    message = response.message
    if message is None or not message.content:
        return ""
    return "".join(
        part.text or "" for part in message.content if part.type == ContentPartType.TEXT
    ).strip()


def _strip_json_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 3 or not lines[-1].strip().startswith("```"):
        return stripped
    return "\n".join(lines[1:-1]).strip()


def _payload_plan_steps(
    value: object,
    *,
    selected_tool_names: list[str],
    selected_skill_names: list[str],
    max_plan_steps: int,
) -> list[AgentPlanStep]:
    if not isinstance(value, list):
        return []
    raw_steps = cast(list[object], value)
    steps: list[AgentPlanStep] = []
    for raw_step in raw_steps[:max_plan_steps]:
        if not isinstance(raw_step, dict):
            continue
        step = cast(dict[str, object], raw_step)
        objective = _payload_string(step.get("objective"))
        action = _payload_string(step.get("action"))
        if not objective and not action:
            continue
        if not objective:
            objective = action
        if not action:
            action = "Reason over the current context before the next loop step."
        steps.append(
            AgentPlanStep(
                index=len(steps),
                objective=objective,
                action=action,
                tool_names=_filter_names(
                    _payload_string_list(step.get("tool_names")),
                    allowed=selected_tool_names,
                ),
                skill_names=_filter_names(
                    _payload_string_list(step.get("skill_names")),
                    allowed=selected_skill_names,
                ),
                status=_payload_string(step.get("status")) or "pending",
                metadata=(
                    cast(dict[str, Any], step["metadata"])
                    if isinstance(step.get("metadata"), dict)
                    else {}
                ),
            )
        )
    return steps


def _payload_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _payload_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item.strip()
        for item in cast(list[object], value)
        if isinstance(item, str) and item.strip()
    ]


def _filter_names(names: list[str], *, allowed: list[str]) -> list[str]:
    allowed_names = set(allowed)
    return [name for name in names if name in allowed_names]


def _build_plan_objectives(
    *,
    goal: str,
    planning: AgentPlanningConfig | None,
) -> list[str]:
    max_objectives = planning.max_objectives if planning is not None else 4
    objectives = [
        "Understand the goal and relevant constraints.",
        "Use only selected tools when they reduce uncertainty or perform required work.",
        "Incorporate retrieved memory before deciding on a final answer.",
        "Return a concise final response when the goal is satisfied.",
    ]
    if goal:
        objectives.insert(0, f"Complete the user goal: {goal}")
    return objectives[:max_objectives]


def _build_plan_steps(
    *,
    objectives: list[str],
    selected_tool_names: list[str],
    selected_skill_names: list[str],
    memory_query: str | None,
) -> list[AgentPlanStep]:
    steps: list[AgentPlanStep] = []
    for index, objective in enumerate(objectives):
        tool_names = _step_tool_names(
            objective=objective,
            selected_tool_names=selected_tool_names,
            memory_query=memory_query,
        )
        steps.append(
            AgentPlanStep(
                index=index,
                objective=objective,
                action=_step_action(
                    objective=objective,
                    tool_names=tool_names,
                    memory_query=memory_query,
                ),
                tool_names=tool_names,
                skill_names=selected_skill_names,
            )
        )
    return steps


def _step_tool_names(
    *,
    objective: str,
    selected_tool_names: list[str],
    memory_query: str | None,
) -> list[str]:
    lowered = objective.lower()
    if (
        memory_query is not None
        and "memory" in lowered
        and "search_memory" in selected_tool_names
    ):
        return ["search_memory"]
    if "tool" in lowered:
        return selected_tool_names
    return []


def _step_action(
    *,
    objective: str,
    tool_names: list[str],
    memory_query: str | None,
) -> str:
    lowered = objective.lower()
    if memory_query is not None and "memory" in lowered:
        return f"Retrieve memory using query: {memory_query}"
    if tool_names:
        return "Call selected tools only when needed, then inspect the results."
    if "final" in lowered or "response" in lowered:
        return "Write the final answer from the accumulated evidence."
    return "Reason over the current context before the next loop step."


def _memory_query(
    *,
    request: AgentRunRequest,
    config: AgentMemoryRetrievalConfig | None,
) -> str | None:
    if config is None or not config.enabled:
        return None
    if config.query:
        return config.query
    goal = request.goal or _messages_to_text(request.messages)
    if not goal:
        return None
    return goal


def _messages_to_text(messages: list[Message]) -> str:
    chunks: list[str] = []
    for message in messages:
        for part in message.content or []:
            if part.type == ContentPartType.TEXT and part.text:
                chunks.append(part.text)
    return "\n".join(chunks)


def _selected_skill_names(skill_bundle: SkillInstructionBundle | None) -> list[str]:
    if skill_bundle is None:
        return []
    names = skill_bundle.metadata.get("skills")
    if isinstance(names, list):
        return [
            name for name in cast(list[object], names) if isinstance(name, str) and name
        ]
    return [instruction.name for instruction in skill_bundle.instructions]


__all__ = ["AgentPlanner", "plan_enabled"]
