"""业务数据查询响应模型."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class PageMeta(BaseModel):
    total: int
    page: int
    page_size: int


class DataPage(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int = Field(description="从 1 开始")
    page_size: int


class FilterOptions(BaseModel):
    marketplaces: list[str] = Field(default_factory=list)
    sites: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    warehouses: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    order_statuses: list[str] = Field(default_factory=list)
    campaign_types: list[str] = Field(default_factory=list)


class OverviewPoint(BaseModel):
    date: date
    gmv_usd: Decimal = Decimal("0")
    units: int = 0
    refund_usd: Decimal = Decimal("0")
    ad_spend_usd: Decimal = Decimal("0")


class OverviewResponse(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    total_gmv_usd: Decimal = Decimal("0")
    total_units: int = 0
    total_refund_usd: Decimal = Decimal("0")
    total_ad_spend_usd: Decimal = Decimal("0")
    series: list[OverviewPoint] = Field(default_factory=list)


def serialize_row(obj: Any) -> dict[str, Any]:
    """ORM / mapping → JSON 友好 dict."""
    if hasattr(obj, "__table__"):
        data: dict[str, Any] = {}
        for col in obj.__table__.columns:
            val = getattr(obj, col.name)
            if isinstance(val, Decimal):
                data[col.name] = float(val)
            elif isinstance(val, (datetime, date)):
                data[col.name] = val.isoformat()
            else:
                data[col.name] = val
        return data
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(v, Decimal):
                out[k] = float(v)
            elif isinstance(v, (datetime, date)):
                out[k] = v.isoformat()
            else:
                out[k] = v
        return out
    return dict(obj)
