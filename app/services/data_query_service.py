"""业务数据只读查询服务."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AdSpendDaily,
    DailySkuMetric,
    DocumentStatusHistory,
    InventorySnapshot,
    LifecycleEvent,
    OceanFreightRate,
    Product,
    ProductStatusHistory,
    ReturnOrder,
    SalesOrder,
    SkuBatch,
    SkuCostImpactDaily,
    Warehouse,
)
from app.schemas.data import (
    DataPage,
    FilterOptions,
    OverviewPoint,
    OverviewResponse,
    serialize_row,
)


def _paginate(db: Session, stmt: Select[Any], *, page: int, page_size: int) -> DataPage:
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    offset = (page - 1) * page_size
    rows = db.execute(stmt.offset(offset).limit(page_size)).scalars().all()
    return DataPage(
        items=[serialize_row(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


class DataQueryService:
    def get_filter_options(self, db: Session) -> FilterOptions:
        def distinct(col) -> list[str]:
            rows = db.execute(
                select(col).where(col.is_not(None)).distinct().order_by(col).limit(200)
            ).scalars().all()
            return [str(x) for x in rows if x is not None]

        return FilterOptions(
            marketplaces=distinct(SalesOrder.marketplace),
            sites=distinct(SalesOrder.site),
            categories=distinct(Product.category),
            warehouses=distinct(Warehouse.warehouse_code),
            reason_codes=distinct(ReturnOrder.reason_code),
            order_statuses=distinct(SalesOrder.status),
            campaign_types=distinct(AdSpendDaily.campaign_type),
        )

    def overview(
        self,
        db: Session,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        marketplace: str | None = None,
        site: str | None = None,
    ) -> OverviewResponse:
        if date_to is None:
            date_to = db.execute(select(func.max(DailySkuMetric.metric_date))).scalar()
        if date_to is None:
            date_to = date.today()
        if date_from is None:
            date_from = date_to - timedelta(days=29)

        stmt = (
            select(
                DailySkuMetric.metric_date.label("metric_date"),
                func.coalesce(func.sum(DailySkuMetric.gmv_usd), 0).label("gmv_usd"),
                func.coalesce(func.sum(DailySkuMetric.units), 0).label("units"),
                func.coalesce(func.sum(DailySkuMetric.refund_usd), 0).label("refund_usd"),
                func.coalesce(func.sum(DailySkuMetric.ad_spend_usd), 0).label(
                    "ad_spend_usd"
                ),
            )
            .where(DailySkuMetric.metric_date >= date_from)
            .where(DailySkuMetric.metric_date <= date_to)
        )
        if marketplace:
            stmt = stmt.where(DailySkuMetric.marketplace == marketplace)
        if site:
            stmt = stmt.where(DailySkuMetric.site == site)
        stmt = stmt.group_by(DailySkuMetric.metric_date).order_by(
            DailySkuMetric.metric_date
        )

        rows = db.execute(stmt).mappings().all()
        series: list[OverviewPoint] = []
        total_gmv = Decimal("0")
        total_units = 0
        total_refund = Decimal("0")
        total_ad = Decimal("0")
        for row in rows:
            gmv = Decimal(str(row["gmv_usd"] or 0))
            units = int(row["units"] or 0)
            refund = Decimal(str(row["refund_usd"] or 0))
            ad = Decimal(str(row["ad_spend_usd"] or 0))
            total_gmv += gmv
            total_units += units
            total_refund += refund
            total_ad += ad
            series.append(
                OverviewPoint(
                    date=row["metric_date"],
                    gmv_usd=gmv,
                    units=units,
                    refund_usd=refund,
                    ad_spend_usd=ad,
                )
            )

        return OverviewResponse(
            date_from=date_from,
            date_to=date_to,
            total_gmv_usd=total_gmv,
            total_units=total_units,
            total_refund_usd=total_refund,
            total_ad_spend_usd=total_ad,
            series=series,
        )

    def list_products(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        category: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> DataPage:
        stmt = select(Product).order_by(Product.id.desc())
        if category:
            stmt = stmt.where(Product.category == category)
        if status:
            stmt = stmt.where(Product.status == status)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                (Product.sku.like(like))
                | (Product.name_cn.like(like))
                | (Product.name_en.like(like))
            )
        return _paginate(db, stmt, page=page, page_size=page_size)

    def list_orders(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        date_from: date | None = None,
        date_to: date | None = None,
        marketplace: str | None = None,
        site: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> DataPage:
        stmt = select(SalesOrder).order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())
        if date_from:
            stmt = stmt.where(SalesOrder.order_date >= date_from)
        if date_to:
            stmt = stmt.where(SalesOrder.order_date <= date_to)
        if marketplace:
            stmt = stmt.where(SalesOrder.marketplace == marketplace)
        if site:
            stmt = stmt.where(SalesOrder.site == site)
        if status:
            stmt = stmt.where(SalesOrder.status == status)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(SalesOrder.order_no.like(like))
        return _paginate(db, stmt, page=page, page_size=page_size)

    def list_inventory(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        snapshot_date: date | None = None,
        warehouse_code: str | None = None,
        product_sku: str | None = None,
        below_safety: bool = False,
    ) -> DataPage:
        if snapshot_date is None:
            snapshot_date = db.execute(
                select(func.max(InventorySnapshot.snapshot_date))
            ).scalar()

        stmt = select(InventorySnapshot).order_by(
            InventorySnapshot.available_qty.asc(), InventorySnapshot.id.desc()
        )
        if snapshot_date:
            stmt = stmt.where(InventorySnapshot.snapshot_date == snapshot_date)
        if warehouse_code:
            stmt = stmt.where(InventorySnapshot.warehouse_code == warehouse_code)
        if product_sku:
            stmt = stmt.where(InventorySnapshot.product_sku.like(f"%{product_sku}%"))
        if below_safety:
            stmt = stmt.where(
                InventorySnapshot.available_qty < InventorySnapshot.safety_stock
            )
        return _paginate(db, stmt, page=page, page_size=page_size)

    def list_returns(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        date_from: date | None = None,
        date_to: date | None = None,
        marketplace: str | None = None,
        site: str | None = None,
        reason_code: str | None = None,
        product_sku: str | None = None,
    ) -> DataPage:
        stmt = select(ReturnOrder).order_by(
            ReturnOrder.opened_date.desc(), ReturnOrder.id.desc()
        )
        if date_from:
            stmt = stmt.where(ReturnOrder.opened_date >= date_from)
        if date_to:
            stmt = stmt.where(ReturnOrder.opened_date <= date_to)
        if marketplace:
            stmt = stmt.where(ReturnOrder.marketplace == marketplace)
        if site:
            stmt = stmt.where(ReturnOrder.site == site)
        if reason_code:
            stmt = stmt.where(ReturnOrder.reason_code == reason_code)
        if product_sku:
            stmt = stmt.where(ReturnOrder.product_sku.like(f"%{product_sku}%"))
        return _paginate(db, stmt, page=page, page_size=page_size)

    def list_ads(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        date_from: date | None = None,
        date_to: date | None = None,
        marketplace: str | None = None,
        site: str | None = None,
        campaign_type: str | None = None,
        product_sku: str | None = None,
        min_acos: float | None = None,
    ) -> DataPage:
        stmt = select(AdSpendDaily).order_by(
            AdSpendDaily.spend_date.desc(), AdSpendDaily.id.desc()
        )
        if date_from:
            stmt = stmt.where(AdSpendDaily.spend_date >= date_from)
        if date_to:
            stmt = stmt.where(AdSpendDaily.spend_date <= date_to)
        if marketplace:
            stmt = stmt.where(AdSpendDaily.marketplace == marketplace)
        if site:
            stmt = stmt.where(AdSpendDaily.site == site)
        if campaign_type:
            stmt = stmt.where(AdSpendDaily.campaign_type == campaign_type)
        if product_sku:
            stmt = stmt.where(AdSpendDaily.product_sku.like(f"%{product_sku}%"))
        if min_acos is not None:
            stmt = stmt.where(AdSpendDaily.acos >= min_acos)
        return _paginate(db, stmt, page=page, page_size=page_size)

    def list_metrics(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        date_from: date | None = None,
        date_to: date | None = None,
        marketplace: str | None = None,
        site: str | None = None,
        product_sku: str | None = None,
    ) -> DataPage:
        stmt = select(DailySkuMetric).order_by(
            DailySkuMetric.metric_date.desc(), DailySkuMetric.id.desc()
        )
        if date_from:
            stmt = stmt.where(DailySkuMetric.metric_date >= date_from)
        if date_to:
            stmt = stmt.where(DailySkuMetric.metric_date <= date_to)
        if marketplace:
            stmt = stmt.where(DailySkuMetric.marketplace == marketplace)
        if site:
            stmt = stmt.where(DailySkuMetric.site == site)
        if product_sku:
            stmt = stmt.where(DailySkuMetric.product_sku.like(f"%{product_sku}%"))
        return _paginate(db, stmt, page=page, page_size=page_size)

    def list_lifecycle(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        product_sku: str | None = None,
        batch_no: str | None = None,
        stage: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> DataPage:
        stmt = select(LifecycleEvent).order_by(
            LifecycleEvent.event_time.asc(), LifecycleEvent.id.asc()
        )
        if product_sku:
            stmt = stmt.where(LifecycleEvent.product_sku.like(f"%{product_sku}%"))
        if batch_no:
            stmt = stmt.where(LifecycleEvent.batch_no.like(f"%{batch_no}%"))
        if stage:
            stmt = stmt.where(LifecycleEvent.stage == stage)
        if date_from:
            stmt = stmt.where(LifecycleEvent.event_time >= date_from)
        if date_to:
            # inclusive end-of-day via next day exclusive would be better; keep simple date cast
            stmt = stmt.where(func.date(LifecycleEvent.event_time) <= date_to)
        return _paginate(db, stmt, page=page, page_size=page_size)

    def list_batches(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        product_sku: str | None = None,
        current_stage: str | None = None,
        current_status: str | None = None,
    ) -> DataPage:
        stmt = select(SkuBatch).order_by(SkuBatch.opened_date.desc(), SkuBatch.id.desc())
        if product_sku:
            stmt = stmt.where(SkuBatch.product_sku.like(f"%{product_sku}%"))
        if current_stage:
            stmt = stmt.where(SkuBatch.current_stage == current_stage)
        if current_status:
            stmt = stmt.where(SkuBatch.current_status == current_status)
        return _paginate(db, stmt, page=page, page_size=page_size)

    def list_product_status_history(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        product_sku: str | None = None,
        scope: str | None = None,
    ) -> DataPage:
        stmt = select(ProductStatusHistory).order_by(
            ProductStatusHistory.changed_at.asc(), ProductStatusHistory.id.asc()
        )
        if product_sku:
            stmt = stmt.where(ProductStatusHistory.product_sku.like(f"%{product_sku}%"))
        if scope:
            stmt = stmt.where(ProductStatusHistory.scope == scope)
        return _paginate(db, stmt, page=page, page_size=page_size)

    def list_document_status_history(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        product_sku: str | None = None,
        batch_no: str | None = None,
        doc_type: str | None = None,
    ) -> DataPage:
        stmt = select(DocumentStatusHistory).order_by(
            DocumentStatusHistory.changed_at.asc(), DocumentStatusHistory.id.asc()
        )
        if product_sku:
            stmt = stmt.where(DocumentStatusHistory.product_sku.like(f"%{product_sku}%"))
        if batch_no:
            stmt = stmt.where(DocumentStatusHistory.batch_no.like(f"%{batch_no}%"))
        if doc_type:
            stmt = stmt.where(DocumentStatusHistory.doc_type == doc_type)
        return _paginate(db, stmt, page=page, page_size=page_size)

    def list_freight_rates(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        lane_code: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> DataPage:
        stmt = select(OceanFreightRate).order_by(
            OceanFreightRate.rate_date.asc(), OceanFreightRate.id.asc()
        )
        if lane_code:
            stmt = stmt.where(OceanFreightRate.lane_code == lane_code)
        if date_from:
            stmt = stmt.where(OceanFreightRate.rate_date >= date_from)
        if date_to:
            stmt = stmt.where(OceanFreightRate.rate_date <= date_to)
        return _paginate(db, stmt, page=page, page_size=page_size)

    def list_cost_impact(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        product_sku: str | None = None,
        phase: str | None = None,
        marketplace: str | None = None,
        site: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> DataPage:
        stmt = select(SkuCostImpactDaily).order_by(
            SkuCostImpactDaily.metric_date.asc(), SkuCostImpactDaily.id.asc()
        )
        if product_sku:
            stmt = stmt.where(SkuCostImpactDaily.product_sku.like(f"%{product_sku}%"))
        if phase:
            stmt = stmt.where(SkuCostImpactDaily.phase == phase)
        if marketplace:
            stmt = stmt.where(SkuCostImpactDaily.marketplace == marketplace)
        if site:
            stmt = stmt.where(SkuCostImpactDaily.site == site)
        if date_from:
            stmt = stmt.where(SkuCostImpactDaily.metric_date >= date_from)
        if date_to:
            stmt = stmt.where(SkuCostImpactDaily.metric_date <= date_to)
        return _paginate(db, stmt, page=page, page_size=page_size)


_data_service: DataQueryService | None = None


def get_data_query_service() -> DataQueryService:
    global _data_service
    if _data_service is None:
        _data_service = DataQueryService()
    return _data_service
