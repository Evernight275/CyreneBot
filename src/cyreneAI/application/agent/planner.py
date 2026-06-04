from __future__ import annotations

from typing import cast

from cyreneAI.core.schema.agent import (
    AgentMemoryRetrievalConfig,
    AgentPlan,
    AgentPlanConstraints,
    AgentPlanningConfig,
    AgentPlanStep,
    AgentRunRequest,
)
from cyreneAI.core.schema.message import ContentPart, ContentPartType, Message
from cyreneAI.core.schema.skill import SkillInstructionBundle
from cyreneAI.core.schema.tool import ToolDefinition


class AgentPlanner:
    """
    Builds an auditable plan before the agent loop starts.
    """

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
    if memory_query is not None and "memory" in lowered and "search_memory" in selected_tool_names:
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
        return [name for name in cast(list[object], names) if isinstance(name, str) and name]
    return [instruction.name for instruction in skill_bundle.instructions]


__all__ = ["AgentPlanner", "plan_enabled"]
