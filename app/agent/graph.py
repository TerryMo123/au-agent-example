"""LangGraph Agent 编排."""

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    enrich_sql_with_rag,
    generate_answer,
    retrieve_rag_context,
    retrieve_sql_context,
    route_question,
)
from app.agent.state import AgentState


def _after_route(state: AgentState) -> list[str]:
    route = state.get("route", "hybrid")
    if route == "sql":
        return ["retrieve_sql"]
    if route == "rag":
        return ["retrieve_rag"]
    # hybrid：专项 SQL 与 RAG 并行，汇合后用 RAG 补全 NL2SQL
    return ["retrieve_sql", "retrieve_rag"]


def _after_sql_retrieve(state: AgentState) -> str:
    if state.get("route") == "hybrid":
        return "enrich_sql"
    return "generate"


def _after_rag_retrieve(state: AgentState) -> str:
    if state.get("route") == "hybrid":
        return "enrich_sql"
    return "generate"


def build_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("route", route_question)
    graph.add_node("retrieve_sql", retrieve_sql_context)
    graph.add_node("retrieve_rag", retrieve_rag_context)
    graph.add_node("enrich_sql", enrich_sql_with_rag)
    graph.add_node("generate", generate_answer)

    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", _after_route, ["retrieve_sql", "retrieve_rag"])
    graph.add_conditional_edges(
        "retrieve_sql", _after_sql_retrieve, ["enrich_sql", "generate"]
    )
    graph.add_conditional_edges(
        "retrieve_rag", _after_rag_retrieve, ["enrich_sql", "generate"]
    )
    graph.add_edge("enrich_sql", "generate")
    graph.add_edge("generate", END)

    return graph.compile()


_agent_graph = None


def get_agent_graph():
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_agent_graph()
    return _agent_graph
