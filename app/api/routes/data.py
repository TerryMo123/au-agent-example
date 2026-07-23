"""业务数据只读查询 API（供前端数据看板使用）."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.mysql import get_db
from app.schemas.data import DataPage, FilterOptions, OverviewResponse
from app.services.data_query_service import DataQueryService, get_data_query_service

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/filters", response_model=FilterOptions)
def get_filters(
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> FilterOptions:
    return service.get_filter_options(db)


@router.get("/overview", response_model=OverviewResponse)
def get_overview(
    date_from: date | None = None,
    date_to: date | None = None,
    marketplace: str | None = None,
    site: str | None = None,
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> OverviewResponse:
    return service.overview(
        db,
        date_from=date_from,
        date_to=date_to,
        marketplace=marketplace,
        site=site,
    )


@router.get("/products", response_model=DataPage)
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataPage:
    return service.list_products(
        db,
        page=page,
        page_size=page_size,
        category=category,
        status=status,
        keyword=keyword,
    )


@router.get("/orders", response_model=DataPage)
def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    date_from: date | None = None,
    date_to: date | None = None,
    marketplace: str | None = None,
    site: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataPage:
    return service.list_orders(
        db,
        page=page,
        page_size=page_size,
        date_from=date_from,
        date_to=date_to,
        marketplace=marketplace,
        site=site,
        status=status,
        keyword=keyword,
    )


@router.get("/inventory", response_model=DataPage)
def list_inventory(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    snapshot_date: date | None = None,
    warehouse_code: str | None = None,
    product_sku: str | None = None,
    below_safety: bool = False,
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataPage:
    return service.list_inventory(
        db,
        page=page,
        page_size=page_size,
        snapshot_date=snapshot_date,
        warehouse_code=warehouse_code,
        product_sku=product_sku,
        below_safety=below_safety,
    )


@router.get("/returns", response_model=DataPage)
def list_returns(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    date_from: date | None = None,
    date_to: date | None = None,
    marketplace: str | None = None,
    site: str | None = None,
    reason_code: str | None = None,
    product_sku: str | None = None,
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataPage:
    return service.list_returns(
        db,
        page=page,
        page_size=page_size,
        date_from=date_from,
        date_to=date_to,
        marketplace=marketplace,
        site=site,
        reason_code=reason_code,
        product_sku=product_sku,
    )


@router.get("/ads", response_model=DataPage)
def list_ads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    date_from: date | None = None,
    date_to: date | None = None,
    marketplace: str | None = None,
    site: str | None = None,
    campaign_type: str | None = None,
    product_sku: str | None = None,
    min_acos: float | None = None,
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataPage:
    return service.list_ads(
        db,
        page=page,
        page_size=page_size,
        date_from=date_from,
        date_to=date_to,
        marketplace=marketplace,
        site=site,
        campaign_type=campaign_type,
        product_sku=product_sku,
        min_acos=min_acos,
    )


@router.get("/metrics", response_model=DataPage)
def list_metrics(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    date_from: date | None = None,
    date_to: date | None = None,
    marketplace: str | None = None,
    site: str | None = None,
    product_sku: str | None = None,
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataPage:
    return service.list_metrics(
        db,
        page=page,
        page_size=page_size,
        date_from=date_from,
        date_to=date_to,
        marketplace=marketplace,
        site=site,
        product_sku=product_sku,
    )


@router.get("/lifecycle", response_model=DataPage)
def list_lifecycle(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    product_sku: str | None = None,
    batch_no: str | None = None,
    stage: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataPage:
    return service.list_lifecycle(
        db,
        page=page,
        page_size=page_size,
        product_sku=product_sku,
        batch_no=batch_no,
        stage=stage,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/batches", response_model=DataPage)
def list_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    product_sku: str | None = None,
    current_stage: str | None = None,
    current_status: str | None = None,
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataPage:
    return service.list_batches(
        db,
        page=page,
        page_size=page_size,
        product_sku=product_sku,
        current_stage=current_stage,
        current_status=current_status,
    )


@router.get("/product-status", response_model=DataPage)
def list_product_status(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    product_sku: str | None = None,
    scope: str | None = None,
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataPage:
    return service.list_product_status_history(
        db,
        page=page,
        page_size=page_size,
        product_sku=product_sku,
        scope=scope,
    )


@router.get("/document-status", response_model=DataPage)
def list_document_status(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    product_sku: str | None = None,
    batch_no: str | None = None,
    doc_type: str | None = None,
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataPage:
    return service.list_document_status_history(
        db,
        page=page,
        page_size=page_size,
        product_sku=product_sku,
        batch_no=batch_no,
        doc_type=doc_type,
    )


@router.get("/freight-rates", response_model=DataPage)
def list_freight_rates(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    lane_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataPage:
    return service.list_freight_rates(
        db,
        page=page,
        page_size=page_size,
        lane_code=lane_code,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/cost-impact", response_model=DataPage)
def list_cost_impact(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    product_sku: str | None = None,
    phase: str | None = None,
    marketplace: str | None = None,
    site: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    service: DataQueryService = Depends(get_data_query_service),
) -> DataPage:
    return service.list_cost_impact(
        db,
        page=page,
        page_size=page_size,
        product_sku=product_sku,
        phase=phase,
        marketplace=marketplace,
        site=site,
        date_from=date_from,
        date_to=date_to,
    )
