"""从查询结果构建前端可视化规格（表格 / 折线 / 柱状）。"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any


DATE_KEYS = (
    "rate_date",
    "metric_date",
    "spend_date",
    "order_date",
    "snapshot_date",
    "opened_date",
    "event_time",
    "changed_at",
    "ship_date",
    "date",
    "day",
)

SKIP_KEYS = {"id", "created_at", "remark", "reason", "operator", "rag_hint"}


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def serialize_rows(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if hasattr(row, "_mapping"):
            data = dict(row._mapping)
        elif isinstance(row, dict):
            data = dict(row)
        else:
            try:
                data = dict(row)
            except Exception:  # noqa: BLE001
                continue
        out.append({str(k): to_jsonable(v) for k, v in data.items()})
    return out


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _pick_date_key(keys: list[str]) -> str | None:
    lower_map = {k.lower(): k for k in keys}
    for cand in DATE_KEYS:
        if cand in lower_map:
            return lower_map[cand]
    for k in keys:
        lk = k.lower()
        if lk.endswith("_date") or lk.endswith("_at") or lk in {"date", "day"}:
            return k
    return None


def _pick_numeric_keys(rows: list[dict[str, Any]], keys: list[str]) -> list[str]:
    nums: list[str] = []
    for k in keys:
        if k.lower() in SKIP_KEYS or k.lower().endswith("_id"):
            continue
        sample = [r.get(k) for r in rows if r.get(k) is not None][:8]
        if sample and all(_is_number(v) or (isinstance(v, str) and _is_number(_try_float(v))) for v in sample):
            # prefer already numeric
            if all(_is_number(v) for v in sample):
                nums.append(k)
    return nums


def _try_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_numeric(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        item = dict(r)
        for k in keys:
            if k in item and not _is_number(item[k]):
                f = _try_float(item[k])
                if f is not None:
                    item[k] = f
        out.append(item)
    return out


def build_visualizations(
    rows: list[dict[str, Any]] | None,
    *,
    question: str = "",
    title: str | None = None,
    max_rows: int = 60,
) -> list[dict[str, Any]]:
    """根据二维结果自动生成 table + line/column 规格."""
    if not rows:
        return []

    rows = serialize_rows(rows)[:max_rows]
    if not rows:
        return []

    keys = list(rows[0].keys())
    date_key = _pick_date_key(keys)
    numeric_keys = _pick_numeric_keys(rows, keys)
    rows = _normalize_numeric(rows, numeric_keys)

    viz: list[dict[str, Any]] = []
    q = question or ""
    auto_title = title or (q[:40] if q else "查询结果")

    # 表格始终给一份（便于核对）
    columns = [{"title": k, "dataIndex": k, "key": k} for k in keys]
    viz.append(
        {
            "type": "table",
            "title": f"{auto_title}（表格）",
            "columns": columns,
            "data": rows,
        }
    )

    if date_key and numeric_keys:
        # 折线：长表或多指标
        chart_data: list[dict[str, Any]] = []
        y_keys = numeric_keys[:3]
        if len(y_keys) == 1:
            y = y_keys[0]
            for r in rows:
                if r.get(date_key) is None or r.get(y) is None:
                    continue
                chart_data.append({"x": str(r[date_key])[:19], "y": float(r[y]), "series": y})
            series_field = None
        else:
            for r in rows:
                x = r.get(date_key)
                if x is None:
                    continue
                for y in y_keys:
                    if r.get(y) is None:
                        continue
                    chart_data.append(
                        {"x": str(x)[:19], "y": float(r[y]), "series": y}
                    )
            series_field = "series"

        if len(chart_data) >= 2:
            viz.append(
                {
                    "type": "line",
                    "title": f"{auto_title}（趋势）",
                    "xField": "x",
                    "yField": "y",
                    "seriesField": series_field,
                    "data": chart_data,
                }
            )
        return viz

    # 无日期：分类柱状（取第一非数值列 + 第一数值列）
    if numeric_keys:
        cat_key = next((k for k in keys if k not in numeric_keys), None)
        if cat_key:
            y = numeric_keys[0]
            bar_data = []
            for r in rows[:20]:
                if r.get(cat_key) is None or r.get(y) is None:
                    continue
                bar_data.append({"x": str(r[cat_key]), "y": float(r[y])})
            if len(bar_data) >= 2:
                viz.append(
                    {
                        "type": "column",
                        "title": f"{auto_title}（对比）",
                        "xField": "x",
                        "yField": "y",
                        "seriesField": None,
                        "data": bar_data,
                    }
                )

    return viz


_CHART_FENCE = re.compile(
    r"```(?:aoji-chart|chart)\s*\n(\{.*?\})\n```",
    re.DOTALL | re.IGNORECASE,
)
_TABLE_FENCE = re.compile(
    r"```(?:aoji-table|table-data)\s*\n(\{.*?\})\n```",
    re.DOTALL | re.IGNORECASE,
)


def parse_answer_visualizations(answer: str) -> tuple[str, list[dict[str, Any]]]:
    """从回答中剥离可选的 chart/table JSON 代码块，返回纯文本 + viz."""
    if not answer:
        return "", []
    viz: list[dict[str, Any]] = []
    text = answer

    def _load(raw: str) -> dict[str, Any] | None:
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    for m in _CHART_FENCE.finditer(answer):
        data = _load(m.group(1))
        if not data:
            continue
        chart_type = data.get("type") or "line"
        if chart_type not in {"line", "column", "bar"}:
            chart_type = "line"
        viz.append(
            {
                "type": chart_type,
                "title": data.get("title") or "图表",
                "xField": data.get("xField") or "x",
                "yField": data.get("yField") or "y",
                "seriesField": data.get("seriesField"),
                "data": data.get("data") or [],
            }
        )
    text = _CHART_FENCE.sub("", text)

    for m in _TABLE_FENCE.finditer(answer):
        data = _load(m.group(1))
        if not data:
            continue
        viz.append(
            {
                "type": "table",
                "title": data.get("title") or "表格",
                "columns": data.get("columns") or [],
                "data": data.get("data") or data.get("rows") or [],
            }
        )
    text = _TABLE_FENCE.sub("", text)
    return text.strip(), viz


def merge_visualizations(
    *groups: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        if not group:
            continue
        for item in group:
            key = f"{item.get('type')}|{item.get('title')}|{len(item.get('data') or [])}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged
