import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agent.routing import decide_route, scan_route_signals
from app.agent.state import AgentState, append_trace_action
from app.agent.skills import (
    get_ad_diagnosis_skill,
    get_inventory_alert_skill,
    get_metrics_dictionary_skill,
    get_nl2sql_skill,
    get_rag_skill,
    get_return_attribution_skill,
)
from app.llm import get_chat_llm
from app.llm_retry import LLMRetryExhaustedError, astream_llm_with_retry, invoke_llm_with_retry
from app.agent.viz import build_visualizations, merge_visualizations, parse_answer_visualizations

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是傲基（AoJi）企业级智能数据问答助手。
傲基是一家外贸家具公司，主营床、床头柜等家居产品。

你可以：
1. 查询 MySQL 中的结构化业务数据（产品、刊登、订单、库存、物流、退货、采购、广告等）
2. 检索向量库中的傲基内部知识（政策、流程、运营规范等）
3. 对库存预警类问题给出低于安全库存 / 高库龄 / 在途缺口与补货建议
4. 对广告诊断类问题给出 ACOS 超标 / 空耗投放与降出价建议
5. 对退货归因类问题给出原因分布、业务归因与处置建议

重要事实（必须遵守）：
- 本系统已在服务端自动生成并执行只读 SQL，结果会出现在【结构化数据查询结果】/【NL2SQL 查询成功】等上下文中
- 禁止声称「只能生成 SQL、不能执行查询、需要用户自行到数据库执行」
- 禁止以数据安全/隐私为由拒绝基于上下文中已有查询结果作答
- 若上下文出现【NL2SQL 查询失败】或「暂无结构化查询结果」，如实说明失败原因或缺少数据，不要编造数字，也不要改口说系统不能查库

回答要求：
- 使用简体中文
- 数据问题优先引用查询结果，不要编造数字
- 涉及趋势/对比/多行结果时，用 Markdown 表格归纳关键数字（前端会另外根据查询结果自动渲染曲线图/表格）
- 不要在回答中粘贴超长原始 JSON；用简洁表格或要点即可
- 若上下文含【指标口径】，回答中简要对齐口径（如「GMV 使用 gmv_usd」）
- 若上下文含【库存预警】，按预警条目归纳风险与建议，可售口径用 available_qty
- 若上下文含【广告诊断】，按条目说明 ACOS 相对目标与处置建议
- 若上下文含【退货归因】，先点明主因与归因方向，再给 Top 原因与 SKU
- 内部政策/流程问题优先引用检索到的文档，并尽量点名文档标题
- 若信息不足，明确说明缺少哪些数据
"""

FALLBACK_ANSWER = (
    "抱歉，当前模型服务暂时不稳定，已自动重试仍未成功。"
    "请稍后再试；若问题紧急，可换个问法或联系信息技术部。"
)


def _get_llm():
    return get_chat_llm(temperature=0.1)


def _content_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    return str(content)


def route_question(state: AgentState) -> AgentState:
    """规则优先路由；未命中再用小模型. 同步写入细粒度轨迹."""
    question = state["question"]
    signals = scan_route_signals(question)
    actions = append_trace_action(
        state,
        {
            "id": "route_rule_scan",
            "label": "规则信号扫描",
            "status": "ok",
            "detail": {
                "sql_hits": signals["sql_hits"][:12],
                "rag_hits": signals["rag_hits"][:12],
                "hybrid_hits": signals["hybrid_hits"][:8],
            },
        },
    )
    decision = decide_route(question)
    if decision.rule_matched:
        actions = append_trace_action(
            {**state, "trace_actions": actions},
            {
                "id": "route_rule_hit",
                "label": f"命中路由规则 → {decision.route}",
                "status": "ok",
                "detail": {
                    "route": decision.route,
                    "via": decision.via,
                    "reason": decision.reason,
                    "sql_hits": list(decision.sql_hits)[:12],
                    "rag_hits": list(decision.rag_hits)[:12],
                    "hybrid_hits": list(decision.hybrid_hits)[:8],
                    "llm_invoked": False,
                },
            },
        )
    else:
        llm_status = "ok" if decision.via == "llm" else "error"
        actions = append_trace_action(
            {**state, "trace_actions": actions},
            {
                "id": "route_llm_classify",
                "label": "小模型意图分类",
                "status": llm_status if decision.via != "fallback" else "error",
                "detail": {
                    "invoked": True,
                    "via": decision.via,
                    "route": decision.route,
                    "reason": decision.reason,
                    "raw_preview": (decision.llm_raw or "")[:240],
                },
            },
        )
        if decision.via == "fallback":
            actions = append_trace_action(
                {**state, "trace_actions": actions},
                {
                    "id": "route_fallback",
                    "label": "路由兜底 → hybrid",
                    "status": "error",
                    "detail": {
                        "reason": decision.reason,
                        "fallback_route": "hybrid",
                    },
                },
            )

    return {
        **state,
        "route": decision.route,
        "route_via": decision.via,
        "route_reason": decision.reason,
        "route_sql_hits": list(decision.sql_hits),
        "route_rag_hits": list(decision.rag_hits),
        "route_hybrid_hits": list(decision.hybrid_hits),
        "route_llm_invoked": bool(decision.llm_invoked),
        "trace_actions": actions,
    }


def _should_run_nl2sql(
    question: str,
    *,
    inventory_matched: bool,
    ad_matched: bool,
    return_matched: bool,
    used_specialized: bool,
) -> bool:
    """专项 Skill 已覆盖时，仅当问题还夹带其他结构化诉求才跑 NL2SQL."""
    if not used_specialized:
        return True
    q_lower = question.lower()
    extra_signals = ["gmv", "销量", "订单", "采购"]
    if not inventory_matched:
        extra_signals.extend(["库存", "可售", "库龄"])
    if not ad_matched:
        extra_signals.extend(["acos", "广告", "roas"])
    if not return_matched:
        extra_signals.extend(["退货", "退款"])
    return any(s in q_lower for s in extra_signals)


def _run_nl2sql_into_parts(
    question: str,
    parts: list[str],
    *,
    metric_prompt: str,
    knowledge_context: str = "",
    matched_keys: list[str] | None = None,
    user_role: str = "manager",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {
        "success": False,
        "repaired": False,
        "row_count": 0,
        "sql_preview": "",
        "error": None,
    }
    try:
        outcome = get_nl2sql_skill().run(
            question,
            metric_context=metric_prompt,
            knowledge_context=knowledge_context,
            role=user_role or "manager",
        )
        parts.append(outcome.as_context())
        meta["success"] = bool(outcome.success)
        meta["repaired"] = bool(outcome.repaired)
        meta["row_count"] = len(outcome.rows or [])
        meta["sql_preview"] = (outcome.sql or "")[:240]
        if outcome.sql:
            logger.info(
                "NL2SQL sql=%s success=%s repaired=%s metrics=%s knowledge=%s rows=%s",
                outcome.sql,
                outcome.success,
                outcome.repaired,
                matched_keys or [],
                bool(knowledge_context.strip()),
                len(outcome.rows),
            )
        return list(outcome.rows or []), meta
    except LLMRetryExhaustedError as exc:
        logger.warning("NL2SQL LLM 重试耗尽，降级跳过结构化查询: %s", exc)
        parts.append(
            "结构化查询暂不可用：模型服务多次重试仍失败，本次已跳过 SQL 检索。"
        )
        meta["error"] = f"llm_retry_exhausted:{exc}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("NL2SQL 失败，降级跳过: %s", exc)
        parts.append(f"结构化查询暂不可用：{exc}")
        meta["error"] = str(exc)
    return [], meta


def retrieve_sql_context(state: AgentState) -> AgentState:
    """指标口径 → 库存预警 / 广告诊断 / 退货归因 → 必要时 NL2SQL.

    hybrid 路由下推迟 NL2SQL，等 RAG 并行完成后由 enrich_sql_with_rag 注入知识再生成。
    """
    question = state["question"]
    actions = list(state.get("trace_actions") or [])
    metrics = get_metrics_dictionary_skill().resolve(question)
    metrics_context = metrics.as_context()
    metric_prompt = metrics.as_prompt()
    actions.append(
        {
            "id": "skill_metrics",
            "label": "指标口径对齐",
            "status": "ok" if metrics.matched_keys else "skipped",
            "detail": {
                "matched_keys": list(metrics.matched_keys or [])[:12],
                "has_context": bool(metrics_context.strip()),
            },
        }
    )

    parts: list[str] = []
    sql_rows: list[dict[str, Any]] = list(state.get("sql_rows") or [])
    used_specialized = False

    inventory_skill = get_inventory_alert_skill()
    inventory_matched = inventory_skill.matches(question)
    if inventory_matched:
        try:
            alert = inventory_skill.run(question)
            used_specialized = True
            alert_text = alert.as_context()
            if alert_text:
                parts.append(alert_text)
            actions.append(
                {
                    "id": "skill_inventory_alert",
                    "label": "库存预警 Skill",
                    "status": "error" if alert.error else "ok",
                    "detail": {
                        "matched": True,
                        "item_count": len(alert.items),
                        "error": alert.error,
                    },
                }
            )
            logger.info(
                "库存预警 matched items=%s error=%s",
                len(alert.items),
                alert.error,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("库存预警失败: %s", exc)
            actions.append(
                {
                    "id": "skill_inventory_alert",
                    "label": "库存预警 Skill",
                    "status": "error",
                    "detail": {"matched": True, "error": str(exc)},
                }
            )
    else:
        actions.append(
            {
                "id": "skill_inventory_alert",
                "label": "库存预警 Skill",
                "status": "skipped",
                "detail": {"matched": False},
            }
        )

    ad_skill = get_ad_diagnosis_skill()
    ad_matched = ad_skill.matches(question)
    if ad_matched:
        try:
            diagnosis = ad_skill.run(question)
            used_specialized = True
            text = diagnosis.as_context()
            if text:
                parts.append(text)
            actions.append(
                {
                    "id": "skill_ad_diagnosis",
                    "label": "广告诊断 Skill",
                    "status": "error" if diagnosis.error else "ok",
                    "detail": {
                        "matched": True,
                        "item_count": len(diagnosis.items),
                        "error": diagnosis.error,
                    },
                }
            )
            logger.info(
                "广告诊断 matched items=%s error=%s",
                len(diagnosis.items),
                diagnosis.error,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("广告诊断失败: %s", exc)
            actions.append(
                {
                    "id": "skill_ad_diagnosis",
                    "label": "广告诊断 Skill",
                    "status": "error",
                    "detail": {"matched": True, "error": str(exc)},
                }
            )
    else:
        actions.append(
            {
                "id": "skill_ad_diagnosis",
                "label": "广告诊断 Skill",
                "status": "skipped",
                "detail": {"matched": False},
            }
        )

    return_skill = get_return_attribution_skill()
    return_matched = return_skill.matches(question)
    if return_matched:
        try:
            attribution = return_skill.run(question)
            used_specialized = True
            text = attribution.as_context()
            if text:
                parts.append(text)
            actions.append(
                {
                    "id": "skill_return_attribution",
                    "label": "退货归因 Skill",
                    "status": "error" if attribution.error else "ok",
                    "detail": {
                        "matched": True,
                        "reason_count": len(attribution.reasons),
                        "error": attribution.error,
                    },
                }
            )
            logger.info(
                "退货归因 matched reasons=%s error=%s",
                len(attribution.reasons),
                attribution.error,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("退货归因失败: %s", exc)
            actions.append(
                {
                    "id": "skill_return_attribution",
                    "label": "退货归因 Skill",
                    "status": "error",
                    "detail": {"matched": True, "error": str(exc)},
                }
            )
    else:
        actions.append(
            {
                "id": "skill_return_attribution",
                "label": "退货归因 Skill",
                "status": "skipped",
                "detail": {"matched": False},
            }
        )

    run_nl2sql = _should_run_nl2sql(
        question,
        inventory_matched=inventory_matched,
        ad_matched=ad_matched,
        return_matched=return_matched,
        used_specialized=used_specialized,
    )
    # hybrid：专项 SQL 与 RAG 并行；NL2SQL 等 RAG 后再跑
    defer_nl2sql = state.get("route") == "hybrid"

    if run_nl2sql and not defer_nl2sql:
        rows, nl_meta = _run_nl2sql_into_parts(
            question,
            parts,
            metric_prompt=metric_prompt,
            matched_keys=metrics.matched_keys,
            user_role=str(state.get("user_role") or "manager"),
        )
        if rows:
            sql_rows = rows
        actions.append(
            {
                "id": "skill_nl2sql",
                "label": "NL2SQL 生成与执行",
                "status": "error" if nl_meta.get("error") else "ok",
                "detail": {
                    "deferred": False,
                    "metrics": list(metrics.matched_keys or [])[:8],
                    **nl_meta,
                },
            }
        )
    elif defer_nl2sql and run_nl2sql:
        actions.append(
            {
                "id": "skill_nl2sql",
                "label": "NL2SQL（hybrid 延后至 Enrich）",
                "status": "skipped",
                "detail": {"deferred": True, "reason": "wait_rag_enrich"},
            }
        )
    else:
        actions.append(
            {
                "id": "skill_nl2sql",
                "label": "NL2SQL 生成与执行",
                "status": "skipped",
                "detail": {
                    "deferred": False,
                    "reason": "covered_by_specialized_skill",
                    "inventory": inventory_matched,
                    "ad": ad_matched,
                    "return": return_matched,
                },
            }
        )

    result = "\n\n".join(p for p in parts if p) or (
        "暂无结构化查询结果。" if not defer_nl2sql else ""
    )
    visualizations = build_visualizations(sql_rows, question=question) if sql_rows else []
    return {
        **state,
        "metrics_context": metrics_context,
        "sql_result": result,
        "sql_rows": sql_rows,
        "visualizations": visualizations,
        "trace_actions": actions,
    }


def enrich_sql_with_rag(state: AgentState) -> AgentState:
    """hybrid：RAG 完成后，将内部知识注入 NL2SQL 再推算/执行 SQL."""
    if state.get("route") != "hybrid":
        return state

    question = state["question"]
    actions = list(state.get("trace_actions") or [])
    inventory_matched = get_inventory_alert_skill().matches(question)
    ad_matched = get_ad_diagnosis_skill().matches(question)
    return_matched = get_return_attribution_skill().matches(question)
    used_specialized = inventory_matched or ad_matched or return_matched
    if not _should_run_nl2sql(
        question,
        inventory_matched=inventory_matched,
        ad_matched=ad_matched,
        return_matched=return_matched,
        used_specialized=used_specialized,
    ):
        # 专项已覆盖且无额外结构化诉求
        actions.append(
            {
                "id": "enrich_nl2sql",
                "label": "Hybrid Enrich：跳过 NL2SQL",
                "status": "skipped",
                "detail": {"reason": "covered_by_specialized_skill"},
            }
        )
        if not (state.get("sql_result") or "").strip():
            return {
                **state,
                "sql_result": "暂无结构化查询结果。",
                "trace_actions": actions,
            }
        return {**state, "trace_actions": actions}

    metrics = get_metrics_dictionary_skill().resolve(question)
    parts: list[str] = []
    existing = (state.get("sql_result") or "").strip()
    if existing:
        parts.append(existing)

    rows, nl_meta = _run_nl2sql_into_parts(
        question,
        parts,
        metric_prompt=metrics.as_prompt(),
        knowledge_context=state.get("rag_context") or "",
        matched_keys=metrics.matched_keys,
        user_role=str(state.get("user_role") or "manager"),
    )
    result = "\n\n".join(p for p in parts if p) or "暂无结构化查询结果。"
    sql_rows = rows or list(state.get("sql_rows") or [])
    visualizations = build_visualizations(sql_rows, question=question) if sql_rows else []
    actions.append(
        {
            "id": "enrich_nl2sql",
            "label": "Hybrid Enrich：知识注入后 NL2SQL",
            "status": "error" if nl_meta.get("error") else "ok",
            "detail": {
                "has_rag_context": bool((state.get("rag_context") or "").strip()),
                "metrics": list(metrics.matched_keys or [])[:8],
                **nl_meta,
            },
        }
    )
    return {
        **state,
        "metrics_context": state.get("metrics_context") or metrics.as_context(),
        "sql_result": result,
        "sql_rows": sql_rows,
        "visualizations": visualizations,
        "trace_actions": actions,
    }


def retrieve_rag_context(state: AgentState) -> AgentState:
    """通过 RAG Skill：类目路由 + 多路召回 + 重排 + 引用溯源."""
    question = state["question"]
    actions = list(state.get("trace_actions") or [])
    try:
        outcome = get_rag_skill().retrieve(question, top_k=4)
        context = outcome.as_context()
        sources = outcome.as_sources()
        actions.append(
            {
                "id": "retrieve_rag",
                "label": "RAG 知识检索",
                "status": "ok",
                "detail": {
                    "source_count": len(sources),
                    "titles": [
                        str(s.get("title") or s.get("category") or "")[:40]
                        for s in sources[:5]
                    ],
                    "has_context": bool((context or "").strip()),
                },
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG 检索失败，降级为空上下文: %s", exc)
        context = "内部知识检索暂不可用。"
        sources = []
        actions.append(
            {
                "id": "retrieve_rag",
                "label": "RAG 知识检索",
                "status": "error",
                "detail": {"error": str(exc), "degraded": True},
            }
        )

    return {
        **state,
        "rag_context": context,
        "sources": sources,
        "trace_actions": actions,
    }


def _truncate_text(text: str, max_chars: int) -> str:
    cleaned = (text or "").strip()
    if max_chars <= 0 or len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1] + "…"


def _prior_history_messages(state: AgentState) -> list[SystemMessage | HumanMessage | AIMessage]:
    """从 state.messages 取出当前问题之前的最近若干轮，供最终生成使用."""
    from app.config import get_settings

    settings = get_settings()
    max_n = max(0, int(settings.answer_history_messages))
    max_chars = max(64, int(settings.answer_history_max_chars))
    if max_n <= 0:
        return []

    raw = list(state.get("messages") or [])
    question = (state.get("question") or "").strip()
    # 去掉末尾当前用户问题，避免与下面的 HumanMessage 重复
    if raw:
        last = raw[-1]
        last_content = getattr(last, "content", "")
        if isinstance(last, HumanMessage) and str(last_content).strip() == question:
            raw = raw[:-1]

    selected = raw[-max_n:]
    out: list[SystemMessage | HumanMessage | AIMessage] = []
    for msg in selected:
        content = _truncate_text(str(getattr(msg, "content", "") or ""), max_chars)
        if not content:
            continue
        if isinstance(msg, AIMessage):
            out.append(AIMessage(content=content))
        elif isinstance(msg, SystemMessage):
            out.append(SystemMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out


def _build_answer_messages(state: AgentState) -> list[SystemMessage | HumanMessage | AIMessage]:
    question = state["question"]
    route = state.get("route", "hybrid")

    context_parts: list[str] = []
    if state.get("metrics_context"):
        context_parts.append(state["metrics_context"])
    if route in {"sql", "hybrid"} and state.get("sql_result"):
        context_parts.append(f"【结构化数据查询结果】\n{state['sql_result']}")
    if route in {"rag", "hybrid"} and state.get("rag_context"):
        context_parts.append(state["rag_context"])

    context = "\n\n".join(context_parts) if context_parts else "暂无可用上下文。"
    acl = ""
    if state.get("user_role") == "user":
        acl = (
            "\n【权限约束】当前用户为运营组员：禁止披露采购成本、海运费率、单位成本(COGS)、"
            "贡献利润/毛利拆解；若问题涉及此类内容，说明需运营组长权限，并给出可公开的运营建议。\n"
        )

    messages: list[SystemMessage | HumanMessage | AIMessage] = [
        SystemMessage(content=SYSTEM_PROMPT),
    ]
    messages.extend(_prior_history_messages(state))
    messages.append(
        HumanMessage(
            content=(
                f"用户问题: {question}\n\n可用上下文:\n{context}{acl}\n\n"
                "请结合对话历史与上下文给出专业、简洁的回答；"
                "若问题依赖上文（如「刚才那个 SKU」「换成近 30 天」），必须正确承接。"
            )
        )
    )
    return messages


def generate_answer(state: AgentState) -> AgentState:
    """汇总上下文生成最终回答."""
    actions = list(state.get("trace_actions") or [])
    llm = _get_llm()
    messages = _build_answer_messages(state)
    gen_status = "ok"
    gen_error: str | None = None
    try:
        response = invoke_llm_with_retry(
            lambda: llm.invoke(messages),
            operation="generate_answer",
        )
        answer = _content_text(response)
    except LLMRetryExhaustedError as exc:
        logger.warning("最终生成 LLM 重试耗尽，返回降级文案: %s", exc)
        answer = FALLBACK_ANSWER
        gen_status = "error"
        gen_error = f"llm_retry_exhausted:{exc}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("最终生成失败，返回降级文案: %s", exc)
        answer = FALLBACK_ANSWER
        gen_status = "error"
        gen_error = str(exc)

    clean_answer, answer_viz = parse_answer_visualizations(answer)
    auto_viz = list(state.get("visualizations") or [])
    if not auto_viz and state.get("sql_rows"):
        auto_viz = build_visualizations(
            state.get("sql_rows") or [], question=state.get("question") or ""
        )
    visualizations = merge_visualizations(auto_viz, answer_viz)
    final_answer = clean_answer or answer
    actions.append(
        {
            "id": "generate",
            "label": "答案生成",
            "status": gen_status,
            "detail": {
                "answer_chars": len(final_answer or ""),
                "has_sql": bool(state.get("sql_result")),
                "has_rag": bool(state.get("rag_context")),
                "degraded": gen_status == "error",
                "error": gen_error,
                "viz_count": len(visualizations),
            },
        }
    )

    return {
        **state,
        "answer": final_answer,
        "visualizations": visualizations,
        "trace_actions": actions,
        "messages": state.get("messages", [])
        + [AIMessage(content=final_answer)],
    }


async def stream_answer_tokens(state: AgentState):
    """流式生成回答 token。

    未产出任何内容前失败：由 astream_llm_with_retry 重试；耗尽后抛出。
    已产出部分内容后失败：向上抛出，由 ChatService 发 error + done.degraded，
    **不再**把 FALLBACK 拼进正文。
    """
    llm = _get_llm()
    messages = _build_answer_messages(state)

    async def _extract_chunks():
        async for chunk in llm.astream(messages):
            content = chunk.content
            if isinstance(content, str) and content:
                yield content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, str) and part:
                        yield part
                    elif isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text", "")
                        if text:
                            yield text

    async for token in astream_llm_with_retry(
        _extract_chunks, operation="stream_answer_tokens"
    ):
        yield token
