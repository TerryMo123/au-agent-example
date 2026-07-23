"""傲基业务指标口径目录（Metrics Dictionary）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDef:
    """单个指标口径定义."""

    key: str
    name_cn: str
    aliases: tuple[str, ...]
    definition: str
    formula: str
    preferred_tables: tuple[str, ...]
    preferred_fields: tuple[str, ...]
    sql_hint: str
    notes: str = ""


# 口径与 Demo 表字段对齐；回答/NL2SQL 均以此为准
METRIC_CATALOG: tuple[MetricDef, ...] = (
    MetricDef(
        key="gmv",
        name_cn="GMV（成交额）",
        aliases=("gmv", "成交额", "销售额", "营收", "销售金额", "流水"),
        definition="订单成交金额，统一使用美元口径 gmv_usd。",
        formula="SUM(sales_orders.gmv_usd)",
        preferred_tables=("sales_orders",),
        preferred_fields=("gmv_usd", "order_date", "marketplace", "site", "status"),
        sql_hint="优先查 sales_orders.gmv_usd；默认过滤 status IN ('completed','shipped')；按站点用 site，按平台用 marketplace。",
        notes="不要用 list_price * quantity 估算，除非明确问标价。",
    ),
    MetricDef(
        key="units",
        name_cn="销量（件数）",
        aliases=("销量", "销售件数", "出单量", "units", "件数", "卖了多少件"),
        definition="成交商品件数。订单明细用 order_items.quantity；日汇总可用 daily_sku_metrics.units。",
        formula="SUM(order_items.quantity) 或 SUM(daily_sku_metrics.units)",
        preferred_tables=("order_items", "daily_sku_metrics", "sales_orders"),
        preferred_fields=("quantity", "units", "product_sku", "order_date", "metric_date"),
        sql_hint="按天下单销量：order_items JOIN sales_orders 用 order_date；看 SKU 日趋势优先 daily_sku_metrics。",
    ),
    MetricDef(
        key="available_inventory",
        name_cn="可售库存",
        aliases=("可售库存", "可售", "available", "能卖多少", "现货可售"),
        definition="当前可售数量，不含占用与在途。",
        formula="inventory_snapshots.available_qty",
        preferred_tables=("inventory_snapshots",),
        preferred_fields=("available_qty", "warehouse_code", "product_sku", "snapshot_date", "safety_stock"),
        sql_hint="取最新 snapshot_date；低于安全库存用 available_qty < safety_stock。",
        notes="不要把 in_transit_qty / reserved_qty 算进可售。",
    ),
    MetricDef(
        key="on_hand_inventory",
        name_cn="在库库存",
        aliases=("在库", "on_hand", "实物库存", "仓内库存"),
        definition="仓库在库数量（含占用），不等于可售。",
        formula="inventory_snapshots.on_hand_qty",
        preferred_tables=("inventory_snapshots",),
        preferred_fields=("on_hand_qty", "reserved_qty", "available_qty"),
        sql_hint="在库=on_hand_qty；可售=available_qty；占用=reserved_qty。",
    ),
    MetricDef(
        key="in_transit",
        name_cn="在途库存",
        aliases=("在途", "在途库存", "in_transit", "海运在途"),
        definition="已发运未入库数量，不计入可售。",
        formula="inventory_snapshots.in_transit_qty",
        preferred_tables=("inventory_snapshots", "shipments", "shipment_items"),
        preferred_fields=("in_transit_qty", "shipment_type", "status", "eta_date"),
        sql_hint="看数量用 inventory_snapshots.in_transit_qty；看头程明细用 shipments(shipment_type='first_leg')。",
    ),
    MetricDef(
        key="refund_rate",
        name_cn="退货率",
        aliases=("退货率", "退款率", "return rate", "refund rate"),
        definition="退货件数 / 销售件数，需同一统计周期。",
        formula="refund_units / units",
        preferred_tables=("daily_sku_metrics", "returns", "order_items"),
        preferred_fields=("refund_units", "units", "refund_usd", "opened_date"),
        sql_hint="有日汇总时用 daily_sku_metrics：SUM(refund_units)/NULLIF(SUM(units),0)；否则 returns 与销量分母需同周期。",
    ),
    MetricDef(
        key="refund_amount",
        name_cn="退款金额",
        aliases=("退款金额", "退货金额", "refund", "退了多少钱"),
        definition="退货退款美元金额。",
        formula="SUM(returns.refund_amount_usd) 或 SUM(daily_sku_metrics.refund_usd)",
        preferred_tables=("returns", "daily_sku_metrics"),
        preferred_fields=("refund_amount_usd", "refund_usd", "reason_code", "opened_date"),
        sql_hint="明细归因用 returns.reason_code；金额汇总可用 returns 或 daily_sku_metrics.refund_usd。",
    ),
    MetricDef(
        key="acos",
        name_cn="ACOS",
        aliases=("acos", "广告花费占比", "广告成本销售比"),
        definition="广告花费 / 广告带来的销售额。",
        formula="ad_spend_usd / ad_sales_usd",
        preferred_tables=("ad_spend_daily", "daily_sku_metrics"),
        preferred_fields=("acos", "spend_usd", "ad_spend_usd", "ad_sales_usd", "spend_date"),
        sql_hint="优先用 ad_spend_daily.acos，或 SUM(spend_usd)/NULLIF(SUM(ad_sales_usd),0)；按 SKU/站点分组。",
        notes="成熟款床类目标 ACOS≤25%，床头柜≤30%（内部规范）。",
    ),
    MetricDef(
        key="roas",
        name_cn="ROAS",
        aliases=("roas", "广告回报", "投入产出比"),
        definition="广告销售额 / 广告花费。",
        formula="ad_sales_usd / ad_spend_usd",
        preferred_tables=("ad_spend_daily",),
        preferred_fields=("roas", "ad_sales_usd", "spend_usd"),
        sql_hint="优先 ad_spend_daily.roas，或 SUM(ad_sales_usd)/NULLIF(SUM(spend_usd),0)。",
    ),
    MetricDef(
        key="ad_spend",
        name_cn="广告花费",
        aliases=("广告花费", "广告费", "投放花费", "ad spend", "spend"),
        definition="广告投放支出（美元）。",
        formula="SUM(ad_spend_daily.spend_usd)",
        preferred_tables=("ad_spend_daily", "daily_sku_metrics"),
        preferred_fields=("spend_usd", "ad_spend_usd", "spend_date", "campaign_type"),
        sql_hint="明细用 ad_spend_daily.spend_usd；SKU 日汇总可用 daily_sku_metrics.ad_spend_usd。",
    ),
    MetricDef(
        key="conversion_rate",
        name_cn="转化率",
        aliases=("转化率", "cvr", "conversion", "转化"),
        definition="成交件数 / 会话数（sessions）。",
        formula="units / sessions",
        preferred_tables=("daily_sku_metrics",),
        preferred_fields=("conversion_rate", "units", "sessions", "metric_date"),
        sql_hint="优先 daily_sku_metrics.conversion_rate，或 SUM(units)/NULLIF(SUM(sessions),0)。",
    ),
    MetricDef(
        key="gross_margin_proxy",
        name_cn="毛利粗算",
        aliases=("毛利", "毛利率", "利润", "margin", "cogs"),
        definition="Demo 粗口径：销售额 - 货本 - 预估物流成本（未含广告/仓租等全费用）。",
        formula="subtotal_usd - cogs_usd - estimated_shipping_cost_usd",
        preferred_tables=("order_items",),
        preferred_fields=("subtotal_usd", "cogs_usd", "estimated_shipping_cost_usd"),
        sql_hint="用 order_items 计算；回答时需声明这是粗算毛利，未扣广告与平台费用。",
        notes="若用户要经营净利润，需说明当前 Demo 数据不足以精确核算。",
    ),
)
