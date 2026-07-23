"""傲基业务库 Schema 与 NL2SQL 提示素材."""

ALLOWED_TABLES = {
    "products",
    "marketplace_listings",
    "warehouses",
    "sales_orders",
    "order_items",
    "inventory_snapshots",
    "inventory_transactions",
    "shipments",
    "shipment_items",
    "returns",
    "purchase_orders",
    "purchase_order_items",
    "ad_spend_daily",
    "daily_sku_metrics",
    "ocean_freight_rates",
    "sku_cost_impact_daily",
    "sku_batches",
    "product_status_history",
    "document_status_history",
    "lifecycle_events",
    "internal_documents",
}

SCHEMA_HINT = """
表与常用字段:
- products(sku, parent_sku, name_cn, name_en, category, subcategory, brand, material, color, size, status, launch_date)
- marketplace_listings(sku, marketplace, site, asin, sale_price, currency, fulfillment, rating, review_count, status)
- warehouses(warehouse_code, warehouse_name, warehouse_type, country, region, operator)
- sales_orders(order_no, marketplace, site, order_date, buyer_country, currency, gmv_usd, status)
- order_items(order_id, order_no, product_sku, quantity, unit_price_usd, subtotal_usd, cogs_usd, fulfillment_center, batch_no)
- inventory_snapshots(snapshot_date, warehouse_code, product_sku, on_hand_qty, available_qty, reserved_qty, in_transit_qty, safety_stock, aging_*)
- inventory_transactions(txn_date, warehouse_code, product_sku, txn_type, qty_change, ref_no, batch_no)
- shipments(shipment_no, shipment_type, order_no, carrier, from_warehouse, to_warehouse, ship_date, eta_date, freight_cost_usd, status)
- shipment_items(shipment_no, product_sku, quantity, carton_qty, batch_no)
- returns(return_no, order_no, product_sku, marketplace, site, reason_code, refund_amount_usd, opened_date, status, batch_no)
- purchase_orders(po_no, supplier_name, factory_city, order_date, etd, eta, total_amount, status)
- purchase_order_items(po_no, product_sku, quantity, unit_cost, destination_warehouse, batch_no)
- ad_spend_daily(spend_date, marketplace, site, product_sku, spend_usd, ad_sales_usd, acos, roas)
- daily_sku_metrics(metric_date, product_sku, marketplace, site, units, gmv_usd, refund_units, ad_spend_usd, conversion_rate, available_qty)
- ocean_freight_rates(rate_date, lane_code, origin_port, dest_region, rate_usd, bunker_usd, total_usd, index_base, remark)
  lane_code: CN-USWC|CN-USEC|CN-EU；index_base 为相对基期运价指数
- sku_cost_impact_daily(metric_date, product_sku, marketplace, site, phase, units, gmv_usd, ad_spend_usd, ad_sales_usd, ocean_freight_unit_usd, ocean_freight_total_usd, cogs_usd, contribution_usd, lane_code, remark)
  phase: baseline|ad_up|ad_down|freight_up|mixed；contribution_usd = gmv - cogs - ad - ocean_freight
  分析「广告花费变化对营收/贡献的影响」「海运费上涨挤压利润」优先查此表，可与 ocean_freight_rates 按 lane_code+日期对照
- sku_batches(batch_no, product_sku, po_no, quantity, destination_warehouse, opened_date, current_stage, current_status)
- product_status_history(product_sku, scope, marketplace, site, from_status, to_status, changed_at, reason)
- document_status_history(doc_type, doc_no, product_sku, batch_no, from_status, to_status, changed_at, remark)
- lifecycle_events(product_sku, batch_no, event_time, stage, event_type, from_status, to_status, ref_type, ref_no, warehouse_code, quantity, remark)
  stage 取值: product|listing|purchase|first_leg|inventory|order|last_mile|return
  追踪某产品全阶段状态变化时优先查 lifecycle_events，再按 batch_no 关联采购/物流/库存/订单
"""

FEW_SHOT_EXAMPLES = """
示例:
问题: 近7天 Amazon US 的 GMV 是多少？
SQL: SELECT SUM(gmv_usd) AS gmv_usd FROM sales_orders WHERE marketplace = 'Amazon' AND site = 'US' AND order_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) AND status IN ('completed','shipped') LIMIT 50;

问题: US-CA-1 仓哪些床类 SKU 可售库存低于安全库存？
SQL: SELECT s.product_sku, s.available_qty, s.safety_stock, p.name_cn FROM inventory_snapshots s JOIN products p ON p.sku = s.product_sku WHERE s.warehouse_code = 'US-CA-1' AND s.snapshot_date = (SELECT MAX(snapshot_date) FROM inventory_snapshots) AND p.category = 'bed' AND s.available_qty < s.safety_stock LIMIT 50;

问题: 近30天退货原因分布？
SQL: SELECT reason_code, COUNT(*) AS cnt, SUM(refund_amount_usd) AS refund_usd FROM returns WHERE opened_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) GROUP BY reason_code ORDER BY cnt DESC LIMIT 50;

问题: AU-BED-F-VEL-001 各阶段状态变化？
SQL: SELECT event_time, stage, event_type, from_status, to_status, batch_no, ref_type, ref_no, remark FROM lifecycle_events WHERE product_sku = 'AU-BED-F-VEL-001' ORDER BY event_time ASC LIMIT 50;

问题: 批次 LOT-2026-0101 的采购和头程状态？
SQL: SELECT b.batch_no, b.current_stage, b.current_status, d.doc_type, d.doc_no, d.from_status, d.to_status, d.changed_at FROM sku_batches b LEFT JOIN document_status_history d ON d.batch_no = b.batch_no WHERE b.batch_no = 'LOT-2026-0101' ORDER BY d.changed_at ASC LIMIT 50;

问题: 某床类 SKU 广告加投后 GMV 和贡献怎么变？
SQL: SELECT metric_date, phase, ad_spend_usd, gmv_usd, contribution_usd, remark FROM sku_cost_impact_daily WHERE product_sku = 'AU-BED-F-VEL-001' ORDER BY metric_date ASC LIMIT 60;

问题: 近90天 CN-USWC 海运费怎么变化？
SQL: SELECT rate_date, rate_usd, bunker_usd, total_usd, index_base, remark FROM ocean_freight_rates WHERE lane_code = 'CN-USWC' ORDER BY rate_date ASC LIMIT 90;

问题: 海运上涨期间哪些 SKU 贡献被侵蚀？
SQL: SELECT product_sku, phase, AVG(ad_spend_usd) AS avg_ad, AVG(gmv_usd) AS avg_gmv, AVG(ocean_freight_unit_usd) AS avg_freight_unit, AVG(contribution_usd) AS avg_contrib FROM sku_cost_impact_daily WHERE phase IN ('freight_up','mixed') GROUP BY product_sku, phase ORDER BY avg_contrib ASC LIMIT 50;
"""

DANGEROUS_SQL_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "create",
    "replace",
    "grant",
    "revoke",
)
