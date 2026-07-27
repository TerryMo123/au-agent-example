from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """LangGraph 状态."""

    messages: list[BaseMessage]
    question: str
    route: Literal["sql", "rag", "hybrid", ""]
    route_via: Literal["rule", "llm", "fallback", ""]
    user_role: Literal["manager", "user", ""]
    metrics_context: str
    sql_result: str
    sql_rows: list[dict[str, Any]]
    rag_context: str
    sources: list[dict[str, Any]]
    answer: str
    visualizations: list[dict[str, Any]]


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
