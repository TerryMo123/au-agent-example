from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """LangGraph 状态."""

    messages: list[BaseMessage]
    question: str
    route: Literal["sql", "rag", "hybrid", ""]
    route_via: Literal["rule", "llm", "fallback", ""]
    route_reason: str
    route_sql_hits: list[str]
    route_rag_hits: list[str]
    route_hybrid_hits: list[str]
    route_llm_invoked: bool
    user_role: Literal["manager", "user", ""]
    metrics_context: str
    sql_result: str
    sql_rows: list[dict[str, Any]]
    rag_context: str
    sources: list[dict[str, Any]]
    answer: str
    visualizations: list[dict[str, Any]]
    # admin 执行轨迹细粒度行动线（逐步追加）
    trace_actions: list[dict[str, Any]]


def append_trace_action(
    state: AgentState | dict[str, Any], action: dict[str, Any]
) -> list[dict[str, Any]]:
    actions = list(state.get("trace_actions") or [])
    actions.append(action)
    return actions


def to_langchain_messages(
    history: list[dict[str, str]], user_message: str
) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for item in history:
        role = item.get("role", "user")
        content = item.get("content", "")
        if role == "assistant":
            messages.append(AIMessage(content=content))
        elif role == "system":
            messages.append(SystemMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))
    messages.append(HumanMessage(content=user_message))
    return messages
