import json
from typing import Any


def format_sse(event: str, data: Any) -> str:
    """格式化为 SSE 消息."""
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"
