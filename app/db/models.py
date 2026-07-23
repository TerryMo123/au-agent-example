"""数据库模型."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.mysql import Base


# ---------------------------------------------------------------------------
# 业务主数据
# ---------------------------------------------------------------------------


class Product(Base):
    """产品主数据 - 床、床头柜等家具 SKU."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    parent_sku: Mapped[str | None] = mapped_column(String(64), index=True)
    name_cn: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(64))
    brand: Mapped[str] = mapped_column(String(64), default="傲基")
    material: Mapped[str | None] = mapped_column(String(128))
    color: Mapped[str | None] = mapped_column(String(64))
    size: Mapped[str | None] = mapped_column(String(64))
    net_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    package_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    package_l_cm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    package_w_cm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    package_h_cm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    origin_country: Mapped[str] = mapped_column(String(8), default="CN")
    hs_code: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    launch_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MarketplaceListing(Base):
    """平台刊登信息."""

    __tablename__ = "marketplace_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(64), index=True)
    marketplace: Mapped[str] = mapped_column(String(64), index=True)
    site: Mapped[str] = mapped_column(String(16), index=True)
    asin: Mapped[str | None] = mapped_column(String(32), index=True)
    platform_item_id: Mapped[str | None] = mapped_column(String(64))
    seller_sku: Mapped[str] = mapped_column(String(64))
    list_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    sale_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    fulfillment: Mapped[str] = mapped_column(String(16), default="FBA")
    buy_box_owner: Mapped[int] = mapped_column(Integer, default=1)  # 1 yes / 0 no
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Warehouse(Base):
    """仓库主数据."""

    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    warehouse_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    warehouse_name: Mapped[str] = mapped_column(String(128))
    warehouse_type: Mapped[str] = mapped_column(String(32), index=True)
    country: Mapped[str] = mapped_column(String(8), index=True)
    region: Mapped[str | None] = mapped_column(String(64))
    operator: Mapped[str] = mapped_column(String(64), default="傲基自营")
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 销售
# ---------------------------------------------------------------------------


class SalesOrder(Base):
    """销售订单头."""

    __tablename__ = "sales_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    platform_order_id: Mapped[str] = mapped_column(String(64), index=True)
    marketplace: Mapped[str] = mapped_column(String(64), index=True)
    site: Mapped[str] = mapped_column(String(16), index=True)
    order_date: Mapped[date] = mapped_column(Date, index=True)
    ship_by_date: Mapped[date | None] = mapped_column(Date)
    buyer_country: Mapped[str] = mapped_column(String(8), index=True)
    buyer_state: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    fx_rate_to_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("1"))
    gmv_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    gmv_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), index=True)
    shipping_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    sales_channel: Mapped[str] = mapped_column(String(32), default="DF")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OrderItem(Base):
    """订单明细."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    order_no: Mapped[str] = mapped_column(String(64), index=True)
    product_sku: Mapped[str] = mapped_column(String(64), index=True)
    asin: Mapped[str | None] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    unit_price_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    item_discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    subtotal_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    cogs_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    estimated_shipping_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0")
    )
    fulfillment_center: Mapped[str | None] = mapped_column(String(64))
    batch_no: Mapped[str | None] = mapped_column(String(64), index=True)


# ---------------------------------------------------------------------------
# 库存
# ---------------------------------------------------------------------------


class InventorySnapshot(Base):
    """库存日快照."""

    __tablename__ = "inventory_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    warehouse_code: Mapped[str] = mapped_column(String(32), index=True)
    product_sku: Mapped[str] = mapped_column(String(64), index=True)
    on_hand_qty: Mapped[int] = mapped_column(Integer, default=0)
    available_qty: Mapped[int] = mapped_column(Integer, default=0)
    reserved_qty: Mapped[int] = mapped_column(Integer, default=0)
    in_transit_qty: Mapped[int] = mapped_column(Integer, default=0)
    safety_stock: Mapped[int] = mapped_column(Integer, default=0)
    aging_0_30: Mapped[int] = mapped_column(Integer, default=0)
    aging_31_60: Mapped[int] = mapped_column(Integer, default=0)
    aging_61_90: Mapped[int] = mapped_column(Integer, default=0)
    aging_90_plus: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class InventoryTransaction(Base):
    """库存流水."""

    __tablename__ = "inventory_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    txn_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    txn_date: Mapped[date] = mapped_column(Date, index=True)
    warehouse_code: Mapped[str] = mapped_column(String(32), index=True)
    product_sku: Mapped[str] = mapped_column(String(64), index=True)
    txn_type: Mapped[str] = mapped_column(String(32), index=True)
    qty_change: Mapped[int] = mapped_column(Integer)
    ref_no: Mapped[str | None] = mapped_column(String(64))
    batch_no: Mapped[str | None] = mapped_column(String(64), index=True)
    remark: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 物流
# ---------------------------------------------------------------------------


class Shipment(Base):
    """发运单（头程/尾程/调拨）."""

    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    shipment_type: Mapped[str] = mapped_column(String(32), index=True)
    order_no: Mapped[str | None] = mapped_column(String(64), index=True)
    carrier: Mapped[str] = mapped_column(String(64))
    tracking_no: Mapped[str | None] = mapped_column(String(128))
    from_warehouse: Mapped[str | None] = mapped_column(String(32))
    to_warehouse: Mapped[str | None] = mapped_column(String(32))
    ship_date: Mapped[date | None] = mapped_column(Date, index=True)
    eta_date: Mapped[date | None] = mapped_column(Date)
    delivered_date: Mapped[date | None] = mapped_column(Date)
    freight_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    duty_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(32), default="in_transit", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ShipmentItem(Base):
    """发运明细."""

    __tablename__ = "shipment_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_id: Mapped[int] = mapped_column(Integer, index=True)
    shipment_no: Mapped[str] = mapped_column(String(64), index=True)
    product_sku: Mapped[str] = mapped_column(String(64), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    carton_qty: Mapped[int] = mapped_column(Integer, default=1)
    batch_no: Mapped[str | None] = mapped_column(String(64), index=True)


# ---------------------------------------------------------------------------
# 售后
# ---------------------------------------------------------------------------


class ReturnOrder(Base):
    """退货退款."""

    __tablename__ = "returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    return_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    order_no: Mapped[str] = mapped_column(String(64), index=True)
    product_sku: Mapped[str] = mapped_column(String(64), index=True)
    marketplace: Mapped[str] = mapped_column(String(64), index=True)
    site: Mapped[str] = mapped_column(String(16), index=True)
    reason_code: Mapped[str] = mapped_column(String(64), index=True)
    reason_detail: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    refund_amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    return_shipping_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0")
    )
    restocking_fee_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    disposition: Mapped[str] = mapped_column(String(32), default="sellable")
    opened_date: Mapped[date] = mapped_column(Date, index=True)
    closed_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="refunded", index=True)
    batch_no: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 供应链
# ---------------------------------------------------------------------------


class PurchaseOrder(Base):
    """采购/工厂订单."""

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    supplier_name: Mapped[str] = mapped_column(String(128))
    factory_city: Mapped[str | None] = mapped_column(String(64))
    order_date: Mapped[date] = mapped_column(Date, index=True)
    etd: Mapped[date | None] = mapped_column(Date)
    eta: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(32), default="confirmed", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PurchaseOrderItem(Base):
    """采购明细."""

    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_id: Mapped[int] = mapped_column(Integer, index=True)
    po_no: Mapped[str] = mapped_column(String(64), index=True)
    product_sku: Mapped[str] = mapped_column(String(64), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    destination_warehouse: Mapped[str] = mapped_column(String(32))
    batch_no: Mapped[str | None] = mapped_column(String(64), index=True)


# ---------------------------------------------------------------------------
# 经营分析
# ---------------------------------------------------------------------------


class AdSpendDaily(Base):
    """广告日花费."""

    __tablename__ = "ad_spend_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spend_date: Mapped[date] = mapped_column(Date, index=True)
    marketplace: Mapped[str] = mapped_column(String(64), index=True)
    site: Mapped[str] = mapped_column(String(16), index=True)
    product_sku: Mapped[str] = mapped_column(String(64), index=True)
    campaign_type: Mapped[str] = mapped_column(String(64))
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    spend_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    ad_sales_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    acos: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    roas: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DailySkuMetric(Base):
    """SKU 日经营汇总."""

    __tablename__ = "daily_sku_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_date: Mapped[date] = mapped_column(Date, index=True)
    product_sku: Mapped[str] = mapped_column(String(64), index=True)
    marketplace: Mapped[str] = mapped_column(String(64), index=True)
    site: Mapped[str] = mapped_column(String(16), index=True)
    units: Mapped[int] = mapped_column(Integer, default=0)
    gmv_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    refund_units: Mapped[int] = mapped_column(Integer, default=0)
    refund_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    ad_spend_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    ad_sales_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    sessions: Mapped[int] = mapped_column(Integer, default=0)
    conversion_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    available_qty: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OceanFreightRate(Base):
    """海运费率历史（按航线/日期），用于分析运费涨跌对成本的影响."""

    __tablename__ = "ocean_freight_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    lane_code: Mapped[str] = mapped_column(String(32), index=True)
    # 如 CN-USWC / CN-USEC / CN-EU
    origin_port: Mapped[str] = mapped_column(String(64))
    dest_region: Mapped[str] = mapped_column(String(64), index=True)
    container_type: Mapped[str] = mapped_column(String(16), default="40HQ")
    rate_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    bunker_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    index_base: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), default=Decimal("1")
    )  # 相对基期指数
    remark: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SkuCostImpactDaily(Base):
    """SKU 日度费用-营收对照：广告花费、分摊海运、GMV/毛利，便于做变化归因."""

    __tablename__ = "sku_cost_impact_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_date: Mapped[date] = mapped_column(Date, index=True)
    product_sku: Mapped[str] = mapped_column(String(64), index=True)
    marketplace: Mapped[str] = mapped_column(String(64), index=True)
    site: Mapped[str] = mapped_column(String(16), index=True)
    phase: Mapped[str] = mapped_column(String(32), index=True)
    # baseline | ad_up | ad_down | freight_up | mixed
    units: Mapped[int] = mapped_column(Integer, default=0)
    gmv_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    ad_spend_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    ad_sales_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    ocean_freight_unit_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), default=Decimal("0")
    )
    ocean_freight_total_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0")
    )
    cogs_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    contribution_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    # gmv - cogs - ad - ocean_freight
    lane_code: Mapped[str | None] = mapped_column(String(32), index=True)
    remark: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# 批次 / 生命周期追踪
# ---------------------------------------------------------------------------


class SkuBatch(Base):
    """SKU 供应批次：把采购→头程→入库串成一条链."""

    __tablename__ = "sku_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    product_sku: Mapped[str] = mapped_column(String(64), index=True)
    po_no: Mapped[str] = mapped_column(String(64), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    destination_warehouse: Mapped[str] = mapped_column(String(32), index=True)
    opened_date: Mapped[date] = mapped_column(Date, index=True)
    current_stage: Mapped[str] = mapped_column(String(32), index=True)
    current_status: Mapped[str] = mapped_column(String(32), index=True)
    remark: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ProductStatusHistory(Base):
    """产品 / 刊登状态变更历史."""

    __tablename__ = "product_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_sku: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(32), index=True)  # product | listing
    marketplace: Mapped[str | None] = mapped_column(String(64), index=True)
    site: Mapped[str | None] = mapped_column(String(16), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    reason: Mapped[str | None] = mapped_column(String(255))
    operator: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DocumentStatusHistory(Base):
    """单据状态变更历史（采购/物流/订单）."""

    __tablename__ = "document_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_type: Mapped[str] = mapped_column(String(32), index=True)  # po|shipment|order
    doc_no: Mapped[str] = mapped_column(String(64), index=True)
    product_sku: Mapped[str | None] = mapped_column(String(64), index=True)
    batch_no: Mapped[str | None] = mapped_column(String(64), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    remark: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LifecycleEvent(Base):
    """SKU 全链路事件时间线（便于一次查清各阶段状态变化）."""

    __tablename__ = "lifecycle_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_sku: Mapped[str] = mapped_column(String(64), index=True)
    batch_no: Mapped[str | None] = mapped_column(String(64), index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    # product|listing|purchase|first_leg|inventory|order|last_mile|return
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32), index=True)
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_no: Mapped[str | None] = mapped_column(String(64), index=True)
    warehouse_code: Mapped[str | None] = mapped_column(String(32), index=True)
    quantity: Mapped[int | None] = mapped_column(Integer)
    remark: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# RAG 元数据 + 会话（非业务种子）
# ---------------------------------------------------------------------------


class InternalDocument(Base):
    """内部文档元数据（正文存 Chroma）."""

    __tablename__ = "internal_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    chroma_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ChatSession(Base):
    """对话会话."""

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="新会话")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )


class ChatMessage(Base):
    """会话消息."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_pk: Mapped[int] = mapped_column(
        Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sources: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped["ChatSession"] = relationship(back_populates="messages")


# 业务表清单（seed 重建用，不含会话/RAG）
BUSINESS_TABLES = [
    LifecycleEvent.__table__,
    DocumentStatusHistory.__table__,
    ProductStatusHistory.__table__,
    SkuBatch.__table__,
    SkuCostImpactDaily.__table__,
    OceanFreightRate.__table__,
    DailySkuMetric.__table__,
    AdSpendDaily.__table__,
    PurchaseOrderItem.__table__,
    PurchaseOrder.__table__,
    ReturnOrder.__table__,
    ShipmentItem.__table__,
    Shipment.__table__,
    InventoryTransaction.__table__,
    InventorySnapshot.__table__,
    OrderItem.__table__,
    SalesOrder.__table__,
    MarketplaceListing.__table__,
    Warehouse.__table__,
    Product.__table__,
]
