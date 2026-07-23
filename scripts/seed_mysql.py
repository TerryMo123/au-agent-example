#!/usr/bin/env python3
"""向 MySQL 写入傲基跨境家具 Demo 业务数据.

用法:
  python scripts/seed_mysql.py          # 若 products 已有数据则跳过
  python scripts/seed_mysql.py --force  # 删除业务表后重建并灌数
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.models import (
    BUSINESS_TABLES,
    AdSpendDaily,
    DailySkuMetric,
    DocumentStatusHistory,
    InventorySnapshot,
    InventoryTransaction,
    LifecycleEvent,
    MarketplaceListing,
    OceanFreightRate,
    OrderItem,
    Product,
    ProductStatusHistory,
    PurchaseOrder,
    PurchaseOrderItem,
    ReturnOrder,
    SalesOrder,
    Shipment,
    ShipmentItem,
    SkuBatch,
    SkuCostImpactDaily,
    Warehouse,
)
from app.db.mysql import SessionLocal, engine, init_db

RNG = random.Random(42)
TODAY = date.today()
YEAR = TODAY.year


def days_ago(n: int) -> date:
    """相对今天往前 n 天（保证落在近一年内）."""
    return TODAY - timedelta(days=min(max(n, 0), 364))


def D(value: float | str) -> Decimal:
    return Decimal(str(value))


def rebuild_business_tables() -> None:
    print("重建业务表...")
    for table in BUSINESS_TABLES:
        table.drop(bind=engine, checkfirst=True)
    for table in reversed(BUSINESS_TABLES):
        table.create(bind=engine, checkfirst=True)


def seed_warehouses(db) -> list[Warehouse]:
    rows = [
        Warehouse(
            warehouse_code="CN-SZ",
            warehouse_name="深圳国内中转仓",
            warehouse_type="domestic",
            country="CN",
            region="华南",
            operator="傲基自营",
        ),
        Warehouse(
            warehouse_code="CN-DG",
            warehouse_name="东莞工厂暂存仓",
            warehouse_type="domestic",
            country="CN",
            region="华南",
            operator="傲基自营",
        ),
        Warehouse(
            warehouse_code="US-CA-1",
            warehouse_name="美西洛杉矶海外仓",
            warehouse_type="overseas",
            country="US",
            region="West",
            operator="傲基自营",
        ),
        Warehouse(
            warehouse_code="US-NJ-1",
            warehouse_name="美东新泽西海外仓",
            warehouse_type="overseas",
            country="US",
            region="East",
            operator="傲基自营",
        ),
        Warehouse(
            warehouse_code="US-FBA-ONT8",
            warehouse_name="Amazon FBA ONT8",
            warehouse_type="fba",
            country="US",
            region="West",
            operator="Amazon",
        ),
        Warehouse(
            warehouse_code="EU-DE-1",
            warehouse_name="德国汉堡海外仓",
            warehouse_type="overseas",
            country="DE",
            region="EU",
            operator="3PL-DHL",
        ),
        Warehouse(
            warehouse_code="UK-FBA-LBA4",
            warehouse_name="Amazon FBA LBA4",
            warehouse_type="fba",
            country="UK",
            region="UK",
            operator="Amazon",
        ),
        Warehouse(
            warehouse_code="CA-TOR-1",
            warehouse_name="加拿大多伦多仓",
            warehouse_type="overseas",
            country="CA",
            region="Ontario",
            operator="3PL",
        ),
    ]
    db.add_all(rows)
    db.flush()
    return rows


def seed_products(db) -> list[Product]:
    # 最后一列为上架距今天数（近一年内）
    catalog = [
        # beds
        ("AU-BED-Q-OAK-001", "AU-BED-Q-OAK", "傲基橡木Queen实木床", "AoJi Oak Queen Platform Bed", "bed", "platform_bed", "Oak", "Natural", "Queen", 42, 48, 200, 35, 18, "9403500090", 320),
        ("AU-BED-K-OAK-001", "AU-BED-Q-OAK", "傲基橡木King实木床", "AoJi Oak King Platform Bed", "bed", "platform_bed", "Oak", "Natural", "King", 48, 55, 220, 38, 18, "9403500090", 320),
        ("AU-BED-Q-VEL-001", "AU-BED-Q-VEL", "傲基绒布Queen软包床", "AoJi Velvet Queen Upholstered Bed", "bed", "upholstered", "Velvet+Steel", "Grey", "Queen", 38, 45, 195, 34, 20, "9403500090", 280),
        ("AU-BED-F-VEL-001", "AU-BED-Q-VEL", "傲基绒布Full软包床", "AoJi Velvet Full Upholstered Bed", "bed", "upholstered", "Velvet+Steel", "Grey", "Full", 34, 40, 185, 32, 20, "9403500090", 280),
        ("AU-BED-Q-LIN-001", "AU-BED-Q-LIN", "傲基亚麻Queen床架", "AoJi Linen Queen Bed Frame", "bed", "upholstered", "Linen+Wood", "Beige", "Queen", 36, 43, 198, 33, 19, "9403500090", 220),
        ("AU-BED-Q-STO-001", "AU-BED-Q-STO", "傲基储物Queen床", "AoJi Storage Queen Bed", "bed", "storage_bed", "PB+Metal", "White", "Queen", 55, 62, 205, 40, 35, "9403500090", 160),
        ("AU-BED-T-MET-001", "AU-BED-T-MET", "傲基金属Twin床架", "AoJi Metal Twin Bed Frame", "bed", "metal_frame", "Steel", "Black", "Twin", 22, 26, 160, 28, 12, "9403208090", 350),
        ("AU-BED-Q-LED-001", "AU-BED-Q-LED", "傲基LED灯光Queen床", "AoJi LED Queen Bed", "bed", "upholstered", "Velvet+LED", "Navy", "Queen", 40, 47, 200, 35, 22, "9403500090", 140),
        # nightstands
        ("AU-NS-2D-WHT-001", "AU-NS-2D", "傲基双抽白色床头柜", "AoJi 2-Drawer White Nightstand", "nightstand", "drawer_ns", "PB", "White", "Standard", 12, 14, 50, 40, 55, "9403500080", 300),
        ("AU-NS-2D-OAK-001", "AU-NS-2D", "傲基双抽橡木床头柜", "AoJi 2-Drawer Oak Nightstand", "nightstand", "drawer_ns", "Oak Veneer", "Natural", "Standard", 13, 15, 50, 40, 55, "9403500080", 300),
        ("AU-NS-USB-BLK-001", "AU-NS-USB", "傲基USB充电床头柜", "AoJi USB Charging Nightstand", "nightstand", "charging_ns", "PB+USB", "Black", "Standard", 14, 16, 52, 42, 58, "9403500080", 250),
        ("AU-NS-USB-WHT-001", "AU-NS-USB", "傲基USB白色床头柜", "AoJi USB White Nightstand", "nightstand", "charging_ns", "PB+USB", "White", "Standard", 14, 16, 52, 42, 58, "9403500080", 250),
        ("AU-NS-3D-GRY-001", "AU-NS-3D", "傲基三抽灰色床头柜", "AoJi 3-Drawer Grey Nightstand", "nightstand", "drawer_ns", "PB", "Grey", "Tall", 16, 18, 48, 40, 70, "9403500080", 200),
        ("AU-NS-RND-WAL-001", "AU-NS-RND", "傲基圆形胡桃床头柜", "AoJi Round Walnut Nightstand", "nightstand", "round_ns", "MDF+Walnut", "Walnut", "Round", 11, 13, 45, 45, 50, "9403500080", 120),
        # dressers / extras
        ("AU-DR-6D-WHT-001", "AU-DR-6D", "傲基六抽白色斗柜", "AoJi 6-Drawer White Dresser", "dresser", "bedroom_dresser", "PB", "White", "Standard", 45, 52, 150, 45, 80, "9403500080", 270),
        ("AU-DR-6D-OAK-001", "AU-DR-6D", "傲基六抽橡木斗柜", "AoJi 6-Drawer Oak Dresser", "dresser", "bedroom_dresser", "Oak Veneer", "Natural", "Standard", 48, 55, 150, 45, 80, "9403500080", 270),
        ("AU-MT-Q-MEM-001", "AU-MT-Q", "傲基Queen记忆棉床垫", "AoJi Queen Memory Foam Mattress", "mattress", "memory_foam", "Memory Foam", "White", "Queen", 28, 32, 200, 150, 30, "9404219000", 230),
        ("AU-MT-K-MEM-001", "AU-MT-Q", "傲基King记忆棉床垫", "AoJi King Memory Foam Mattress", "mattress", "memory_foam", "Memory Foam", "White", "King", 34, 38, 220, 160, 30, "9404219000", 230),
        ("AU-BN-FAB-GRY-001", "AU-BN-FAB", "傲基灰色布艺床尾凳", "AoJi Grey Fabric Bench", "bench", "bed_bench", "Fabric+Wood", "Grey", "Standard", 10, 12, 120, 40, 45, "9401619000", 180),
        ("AU-MR-LED-BLK-001", "AU-MR-LED", "傲基LED黑色全身镜", "AoJi LED Full Length Mirror", "mirror", "floor_mirror", "Glass+MDF", "Black", "Standard", 15, 18, 50, 8, 165, "7009920000", 150),
        ("AU-NS-2D-WHT-002", "AU-NS-2D", "傲基双抽白色床头柜(升级)", "AoJi 2-Drawer White Nightstand Plus", "nightstand", "drawer_ns", "PB", "White", "Standard", 12.5, 14.5, 50, 40, 56, "9403500080", 90),
        ("AU-BED-Q-OAK-002", "AU-BED-Q-OAK", "傲基橡木Queen床(二代)", "AoJi Oak Queen Bed Gen2", "bed", "platform_bed", "Oak", "Walnut Stain", "Queen", 43, 49, 200, 35, 18, "9403500090", 60),
    ]

    products: list[Product] = []
    for row in catalog:
        (
            sku, parent, name_cn, name_en, cat, sub, material, color, size,
            net_w, pkg_w, l, w, h, hs, launch_days,
        ) = row
        products.append(
            Product(
                sku=sku,
                parent_sku=parent,
                name_cn=name_cn,
                name_en=name_en,
                category=cat,
                subcategory=sub,
                brand="傲基",
                material=material,
                color=color,
                size=size,
                net_weight_kg=D(net_w),
                package_weight_kg=D(pkg_w),
                package_l_cm=D(l),
                package_w_cm=D(w),
                package_h_cm=D(h),
                origin_country="CN",
                hs_code=hs,
                status="active",
                launch_date=days_ago(launch_days),
            )
        )
    db.add_all(products)
    db.flush()
    return products


def seed_listings(db, products: list[Product]) -> list[MarketplaceListing]:
    channels = [
        ("Amazon", "US", "USD", "FBA"),
        ("Amazon", "UK", "GBP", "FBA"),
        ("Amazon", "DE", "EUR", "FBA"),
        ("Wayfair", "US", "USD", "FBM"),
        ("Walmart", "US", "USD", "WFS"),
        ("OTTO", "DE", "EUR", "FBM"),
    ]
    # 价格锚点按品类
    base_price = {
        "bed": 320,
        "nightstand": 95,
        "dresser": 280,
        "mattress": 260,
        "bench": 89,
        "mirror": 119,
    }
    listings: list[MarketplaceListing] = []
    asin_seq = 1000
    for p in products:
        # 每个 SKU 上 2~4 个渠道
        chosen = RNG.sample(channels, k=RNG.randint(2, 4))
        for marketplace, site, currency, fulfillment in chosen:
            price = base_price.get(p.category, 100) * RNG.uniform(0.9, 1.35)
            if p.size in {"King"}:
                price *= 1.18
            if currency == "GBP":
                price *= 0.78
            elif currency == "EUR":
                price *= 0.92
            list_price = round(price * 1.08, 2)
            sale_price = round(price, 2)
            asin = f"B0AU{asin_seq:06d}" if marketplace == "Amazon" else None
            asin_seq += 1
            listings.append(
                MarketplaceListing(
                    sku=p.sku,
                    marketplace=marketplace,
                    site=site,
                    asin=asin,
                    platform_item_id=asin or f"{marketplace[:3].upper()}-{asin_seq}",
                    seller_sku=f"{p.sku}-{site}",
                    list_price=D(list_price),
                    sale_price=D(sale_price),
                    currency=currency,
                    fulfillment=fulfillment,
                    buy_box_owner=1 if RNG.random() > 0.15 else 0,
                    rating=D(round(RNG.uniform(3.8, 4.9), 2)),
                    review_count=RNG.randint(20, 2800),
                    status="active",
                )
            )
    db.add_all(listings)
    db.flush()
    return listings


def seed_purchase_orders(db, products: list[Product]) -> None:
    suppliers = [
        ("东莞市宏达家具有限公司", "东莞"),
        ("南康区金典家居厂", "南康"),
        ("佛山市南海兴旺木业", "佛山"),
    ]
    dests = ["US-CA-1", "US-NJ-1", "EU-DE-1", "US-FBA-ONT8"]
    for i in range(1, 13):
        order_date = TODAY - timedelta(days=RNG.randint(20, 120))
        etd = order_date + timedelta(days=RNG.randint(25, 40))
        eta = etd + timedelta(days=RNG.randint(18, 32))
        supplier, city = suppliers[i % len(suppliers)]
        po_no = f"PO-{YEAR}-{i:04d}"
        picks = RNG.sample(products, k=RNG.randint(2, 5))
        total = D(0)
        items = []
        for p in picks:
            qty = RNG.choice([50, 80, 100, 120, 200])
            unit = D(round(RNG.uniform(28, 160), 2))
            total += unit * qty
            items.append((p.sku, qty, unit, RNG.choice(dests)))
        status = "closed" if eta < TODAY - timedelta(days=5) else RNG.choice(
            ["shipped", "produced", "confirmed"]
        )
        po = PurchaseOrder(
            po_no=po_no,
            supplier_name=supplier,
            factory_city=city,
            order_date=order_date,
            etd=etd,
            eta=eta,
            currency="USD",
            total_amount=total,
            status=status,
        )
        db.add(po)
        db.flush()
        for sku, qty, unit, dest in items:
            db.add(
                PurchaseOrderItem(
                    po_id=po.id,
                    po_no=po_no,
                    product_sku=sku,
                    quantity=qty,
                    unit_cost=unit,
                    destination_warehouse=dest,
                )
            )


def seed_orders_and_returns(
    db, products: list[Product], listings: list[MarketplaceListing]
) -> tuple[list[SalesOrder], list[OrderItem]]:
    listing_by_sku: dict[str, list[MarketplaceListing]] = {}
    for li in listings:
        listing_by_sku.setdefault(li.sku, []).append(li)

    fx = {"USD": D("1"), "GBP": D("1.27"), "EUR": D("1.08")}
    states = {
        "US": ["CA", "TX", "NY", "FL", "WA", "IL"],
        "UK": ["England", "Scotland"],
        "DE": ["Bayern", "NRW", "Berlin"],
        "CA": ["ON", "BC"],
    }
    fc_map = {
        ("Amazon", "US"): "US-FBA-ONT8",
        ("Amazon", "UK"): "UK-FBA-LBA4",
        ("Amazon", "DE"): "EU-DE-1",
        ("Wayfair", "US"): "US-CA-1",
        ("Walmart", "US"): "US-NJ-1",
        ("OTTO", "DE"): "EU-DE-1",
    }

    orders: list[SalesOrder] = []
    items: list[OrderItem] = []
    returns: list[ReturnOrder] = []

    for i in range(1, 281):
        p = RNG.choice(products)
        li = RNG.choice(listing_by_sku[p.sku])
        order_date = TODAY - timedelta(days=RNG.randint(0, 89))
        qty = 1 if p.category in {"bed", "dresser", "mattress"} else RNG.choice([1, 1, 2])
        rate = fx[li.currency]
        unit = li.sale_price
        unit_usd = (unit * rate).quantize(D("0.01"))
        discount = D("0") if RNG.random() > 0.2 else (unit_usd * D("0.05") * qty).quantize(D("0.01"))
        ship_rev = D("0") if li.fulfillment == "FBA" else D(str(RNG.choice([0, 9.99, 19.99, 29.99])))
        gmv_usd = (unit_usd * qty - discount + ship_rev).quantize(D("0.01"))
        gmv_amount = (unit * qty).quantize(D("0.01"))
        status = RNG.choices(
            ["completed", "shipped", "refunded", "cancelled"],
            weights=[78, 12, 7, 3],
        )[0]
        order_no = f"SO-{YEAR}-{i:05d}"
        buyer_country = li.site if li.site != "DE" else "DE"
        if li.site == "UK":
            buyer_country = "UK"
        order = SalesOrder(
            order_no=order_no,
            platform_order_id=f"{li.marketplace[:2].upper()}-{100000 + i}",
            marketplace=li.marketplace,
            site=li.site,
            order_date=order_date,
            ship_by_date=order_date + timedelta(days=2),
            buyer_country=buyer_country,
            buyer_state=RNG.choice(states.get(buyer_country, ["N/A"])),
            currency=li.currency,
            fx_rate_to_usd=rate,
            gmv_amount=gmv_amount,
            gmv_usd=gmv_usd,
            shipping_revenue=ship_rev,
            discount_amount=discount,
            tax_amount=(gmv_usd * D("0.08")).quantize(D("0.01")),
            status=status,
            sales_channel="DF" if li.marketplace in {"Amazon", "Walmart"} else "自营",
        )
        orders.append(order)

    db.add_all(orders)
    db.flush()

    reasons = [
        ("damaged", "运输破损/包装损坏"),
        ("size_issue", "尺寸不合适"),
        ("not_as_described", "与描述不符"),
        ("changed_mind", "买家改变主意"),
        ("missing_parts", "配件缺失"),
        ("quality", "做工/异味问题"),
    ]

    for order in orders:
        # 找到对应 listing 价
        p = RNG.choice(products)
        # 尽量用订单相关 sku：从同 marketplace 的 listing 抽
        candidates = [x for x in listings if x.marketplace == order.marketplace and x.site == order.site]
        li = RNG.choice(candidates) if candidates else RNG.choice(listings)
        p_sku = li.sku
        prod = next(x for x in products if x.sku == p_sku)
        qty = 1 if prod.category in {"bed", "dresser", "mattress"} else RNG.choice([1, 1, 2])
        unit_usd = (li.sale_price * fx[li.currency]).quantize(D("0.01"))
        cogs = D(str(round(float(unit_usd) * RNG.uniform(0.35, 0.55), 2)))
        ship_cost = D(str(round(RNG.uniform(8, 55), 2)))
        item = OrderItem(
            order_id=order.id,
            order_no=order.order_no,
            product_sku=p_sku,
            asin=li.asin,
            quantity=qty,
            unit_price=li.sale_price,
            unit_price_usd=unit_usd,
            item_discount=order.discount_amount,
            subtotal_usd=(unit_usd * qty - order.discount_amount).quantize(D("0.01")),
            cogs_usd=cogs * qty,
            estimated_shipping_cost_usd=ship_cost,
            fulfillment_center=fc_map.get((li.marketplace, li.site), "US-CA-1"),
        )
        items.append(item)

        if order.status == "refunded" or (order.status == "completed" and RNG.random() < 0.08):
            reason_code, reason_detail = RNG.choice(reasons)
            opened = order.order_date + timedelta(days=RNG.randint(3, 25))
            returns.append(
                ReturnOrder(
                    return_no=f"RMA-{YEAR}-{order.id:05d}",
                    order_no=order.order_no,
                    product_sku=p_sku,
                    marketplace=order.marketplace,
                    site=order.site,
                    reason_code=reason_code,
                    reason_detail=reason_detail,
                    quantity=qty,
                    refund_amount_usd=item.subtotal_usd,
                    return_shipping_cost_usd=D(str(RNG.choice([0, 12.5, 25, 45]))),
                    restocking_fee_usd=D("0")
                    if reason_code != "changed_mind"
                    else (item.subtotal_usd * D("0.15")).quantize(D("0.01")),
                    disposition=RNG.choice(["sellable", "salvage", "destroy"]),
                    opened_date=opened,
                    closed_date=opened + timedelta(days=RNG.randint(2, 10)),
                    status="refunded",
                )
            )

    db.add_all(items)
    db.add_all(returns)
    db.flush()
    return orders, items


def seed_inventory(db, products: list[Product], warehouses: list[Warehouse]) -> None:
    overseas = [w for w in warehouses if w.warehouse_type in {"overseas", "fba"}]
    snapshots: list[InventorySnapshot] = []
    txns: list[InventoryTransaction] = []
    txn_i = 1

    # 近 30 天，每隔 3 天一张快照，覆盖主要 SKU × 海外仓
    focus_skus = [p.sku for p in products if p.category in {"bed", "nightstand"}][:14]
    for day_offset in range(0, 30, 3):
        snap_date = TODAY - timedelta(days=day_offset)
        for wh in overseas:
            for sku in focus_skus:
                on_hand = RNG.randint(20, 260)
                reserved = RNG.randint(0, 25)
                available = max(on_hand - reserved, 0)
                in_transit = RNG.randint(0, 80)
                safety = 30 if "BED" in sku else 50
                a0 = int(on_hand * 0.45)
                a31 = int(on_hand * 0.25)
                a61 = int(on_hand * 0.15)
                a90 = on_hand - a0 - a31 - a61
                snapshots.append(
                    InventorySnapshot(
                        snapshot_date=snap_date,
                        warehouse_code=wh.warehouse_code,
                        product_sku=sku,
                        on_hand_qty=on_hand,
                        available_qty=available,
                        reserved_qty=reserved,
                        in_transit_qty=in_transit,
                        safety_stock=safety,
                        aging_0_30=a0,
                        aging_31_60=a31,
                        aging_61_90=a61,
                        aging_90_plus=max(a90, 0),
                    )
                )

    # 库存流水抽样
    for _ in range(120):
        wh = RNG.choice(overseas)
        sku = RNG.choice(focus_skus)
        txn_type = RNG.choice(["inbound", "outbound", "adjust", "return", "transfer"])
        qty = RNG.randint(1, 40)
        if txn_type in {"outbound", "transfer"}:
            qty = -qty
        elif txn_type == "adjust":
            qty = RNG.choice([-5, -3, -1, 1, 2, 5])
        txns.append(
            InventoryTransaction(
                txn_no=f"INV-TXN-{txn_i:05d}",
                txn_date=TODAY - timedelta(days=RNG.randint(0, 60)),
                warehouse_code=wh.warehouse_code,
                product_sku=sku,
                txn_type=txn_type,
                qty_change=qty,
                ref_no=f"REF-{txn_i:05d}",
                remark=None,
            )
        )
        txn_i += 1

    db.add_all(snapshots)
    db.add_all(txns)
    db.flush()


def seed_shipments(db, products: list[Product], orders: list[SalesOrder]) -> None:
    carriers_first = ["Maersk", "COSCO", "MSC", "Evergreen"]
    carriers_last = ["UPS", "FedEx", "Amazon Logistics", "DHL"]
    shipments: list[Shipment] = []
    items: list[ShipmentItem] = []

    # 头程
    for i in range(1, 36):
        ship_date = TODAY - timedelta(days=RNG.randint(5, 70))
        eta = ship_date + timedelta(days=RNG.randint(22, 35))
        delivered = eta + timedelta(days=RNG.randint(0, 4)) if eta < TODAY else None
        status = "delivered" if delivered else RNG.choice(["in_transit", "booked"])
        sh_no = f"SHP-FL-{i:04d}"
        sh = Shipment(
            shipment_no=sh_no,
            shipment_type="first_leg",
            order_no=None,
            carrier=RNG.choice(carriers_first),
            tracking_no=f"FL{100000 + i}",
            from_warehouse="CN-SZ",
            to_warehouse=RNG.choice(["US-CA-1", "US-NJ-1", "EU-DE-1", "US-FBA-ONT8"]),
            ship_date=ship_date,
            eta_date=eta,
            delivered_date=delivered,
            freight_cost_usd=D(str(round(RNG.uniform(1800, 6800), 2))),
            duty_cost_usd=D(str(round(RNG.uniform(200, 1200), 2))),
            status=status,
        )
        shipments.append(sh)

    # 尾程（关联部分订单）
    for i, order in enumerate(RNG.sample(orders, k=min(70, len(orders))), start=1):
        ship_date = order.order_date + timedelta(days=RNG.randint(0, 2))
        delivered = ship_date + timedelta(days=RNG.randint(2, 7))
        sh_no = f"SHP-LM-{i:04d}"
        shipments.append(
            Shipment(
                shipment_no=sh_no,
                shipment_type="last_mile",
                order_no=order.order_no,
                carrier=RNG.choice(carriers_last),
                tracking_no=f"LM{200000 + i}",
                from_warehouse=RNG.choice(["US-CA-1", "US-FBA-ONT8", "EU-DE-1"]),
                to_warehouse=None,
                ship_date=ship_date,
                eta_date=ship_date + timedelta(days=3),
                delivered_date=delivered if delivered <= TODAY else None,
                freight_cost_usd=D(str(round(RNG.uniform(8, 65), 2))),
                duty_cost_usd=D("0"),
                status="delivered" if delivered <= TODAY else "in_transit",
            )
        )

    db.add_all(shipments)
    db.flush()

    for sh in shipments:
        sku_count = RNG.randint(1, 3) if sh.shipment_type == "first_leg" else 1
        for p in RNG.sample(products, k=sku_count):
            qty = RNG.randint(40, 200) if sh.shipment_type == "first_leg" else 1
            items.append(
                ShipmentItem(
                    shipment_id=sh.id,
                    shipment_no=sh.shipment_no,
                    product_sku=p.sku,
                    quantity=qty,
                    carton_qty=max(qty // 2, 1) if sh.shipment_type == "first_leg" else 1,
                )
            )
    db.add_all(items)
    db.flush()


def seed_ads_and_metrics(
    db, products: list[Product], listings: list[MarketplaceListing]
) -> None:
    focus = [p for p in products if p.category in {"bed", "nightstand"}][:10]
    ads: list[AdSpendDaily] = []
    metrics: list[DailySkuMetric] = []

    for day_offset in range(0, 30):
        d = TODAY - timedelta(days=day_offset)
        for p in focus:
            related = [li for li in listings if li.sku == p.sku]
            if not related:
                continue
            li = RNG.choice(related)
            impressions = RNG.randint(800, 18000)
            clicks = int(impressions * RNG.uniform(0.02, 0.08))
            spend = D(str(round(clicks * RNG.uniform(0.35, 1.2), 2)))
            ad_sales = D(str(round(float(spend) * RNG.uniform(2.2, 6.5), 2)))
            acos = (spend / ad_sales).quantize(D("0.0001")) if ad_sales else None
            roas = (ad_sales / spend).quantize(D("0.0001")) if spend else None
            ads.append(
                AdSpendDaily(
                    spend_date=d,
                    marketplace=li.marketplace,
                    site=li.site,
                    product_sku=p.sku,
                    campaign_type=RNG.choice(["sponsored_products", "display"]),
                    impressions=impressions,
                    clicks=clicks,
                    spend_usd=spend,
                    ad_sales_usd=ad_sales,
                    acos=acos,
                    roas=roas,
                )
            )

    # 近 60 天 SKU 日汇总（抽样渠道）
    for day_offset in range(0, 60):
        d = TODAY - timedelta(days=day_offset)
        for p in focus:
            for marketplace, site in [("Amazon", "US"), ("Wayfair", "US"), ("Amazon", "DE")]:
                if RNG.random() < 0.35:
                    continue
                units = RNG.randint(0, 18)
                gmv = D(str(round(units * RNG.uniform(80, 420), 2)))
                refund_units = 1 if units > 5 and RNG.random() < 0.12 else 0
                refund = D(str(round(refund_units * RNG.uniform(80, 350), 2)))
                ad_spend = D(str(round(RNG.uniform(0, 90), 2)))
                ad_sales = D(str(round(float(ad_spend) * RNG.uniform(0, 5), 2)))
                sessions = RNG.randint(20, 600)
                cvr = D(str(round(units / sessions, 4))) if sessions else None
                metrics.append(
                    DailySkuMetric(
                        metric_date=d,
                        product_sku=p.sku,
                        marketplace=marketplace,
                        site=site,
                        units=units,
                        gmv_usd=gmv,
                        refund_units=refund_units,
                        refund_usd=refund,
                        ad_spend_usd=ad_spend,
                        ad_sales_usd=ad_sales,
                        sessions=sessions,
                        conversion_rate=cvr,
                        available_qty=RNG.randint(15, 220),
                    )
                )

    db.add_all(ads)
    db.add_all(metrics)
    db.flush()


def seed_freight_and_cost_impact(
    db, products: list[Product], listings: list[MarketplaceListing]
) -> None:
    """海运费率曲线 + 广告花费/营收/运费联动的日度对照（可讲故事的 Demo 情景）."""
    lanes = [
        ("CN-USWC", "深圳盐田", "US West Coast", 3200),
        ("CN-USEC", "深圳盐田", "US East Coast", 4100),
        ("CN-EU", "宁波舟山", "North Europe", 2800),
    ]
    freight_rows: list[OceanFreightRate] = []
    for day_offset in range(0, 90):
        d = TODAY - timedelta(days=89 - day_offset)  # 从旧到新
        # 情景：近 35~15 天海运大涨，近 14 天回落但仍高于基期
        if 55 <= day_offset <= 74:  # 涨价期（约 35~15 天前）
            mult = 1.0 + 0.35 + 0.01 * (day_offset - 55)
            phase_remark = "旺季/舱位紧张，海运费上涨"
        elif day_offset >= 75:
            mult = 1.28 - 0.008 * (day_offset - 75)
            phase_remark = "运价高位回落"
        else:
            mult = 1.0 + 0.002 * RNG.uniform(-1, 1)
            phase_remark = "运价平稳"
        for lane, origin, dest, base in lanes:
            rate = D(str(round(base * mult, 2)))
            bunker = D(str(round(float(rate) * 0.08, 2)))
            total = rate + bunker
            freight_rows.append(
                OceanFreightRate(
                    rate_date=d,
                    lane_code=lane,
                    origin_port=origin,
                    dest_region=dest,
                    container_type="40HQ",
                    rate_usd=rate,
                    bunker_usd=bunker,
                    total_usd=total,
                    index_base=D(str(round(mult, 4))),
                    remark=phase_remark,
                )
            )
    db.add_all(freight_rows)
    db.flush()

    # 建 rate lookup: (lane, date) -> total
    rate_map: dict[tuple[str, date], Decimal] = {
        (r.lane_code, r.rate_date): r.total_usd for r in freight_rows
    }

    # 选 3 个故事 SKU：广告加投→营收升，再降投→营收回落；并叠加海运涨价挤压贡献
    story_skus = [p for p in products if p.category == "bed"][:3]
    if len(story_skus) < 3:
        story_skus = products[:3]

    sku_lane = {
        story_skus[0].sku: "CN-USWC",
        story_skus[1].sku: "CN-USEC" if len(story_skus) > 1 else "CN-USWC",
        story_skus[2].sku: "CN-EU" if len(story_skus) > 2 else "CN-USWC",
    }
    sku_channel = {
        story_skus[0].sku: ("Amazon", "US"),
        story_skus[1].sku: ("Amazon", "US") if len(story_skus) > 1 else ("Amazon", "US"),
        story_skus[2].sku: ("Amazon", "DE") if len(story_skus) > 2 else ("Amazon", "US"),
    }
    # 单价锚点
    unit_price = {
        story_skus[0].sku: 340.0,
        story_skus[1].sku: 360.0 if len(story_skus) > 1 else 340.0,
        story_skus[2].sku: 290.0 if len(story_skus) > 2 else 340.0,
    }
    unit_cogs = {k: v * 0.42 for k, v in unit_price.items()}

    impact_rows: list[SkuCostImpactDaily] = []
    story_ads: list[AdSpendDaily] = []
    story_metrics: list[DailySkuMetric] = []

    for p in story_skus:
        sku = p.sku
        lane = sku_lane[sku]
        marketplace, site = sku_channel[sku]
        price = unit_price[sku]
        cogs_u = unit_cogs[sku]
        # 每柜约装载件数（Demo）
        units_per_container = 90 if "BED" in sku else 160

        for day_offset in range(0, 60):
            d = TODAY - timedelta(days=59 - day_offset)
            # 阶段划分（相对 60 天窗口）
            if day_offset < 20:
                phase = "baseline"
                ad_mult = 1.0
                demand_mult = 1.0
                remark = "基线期：广告与营收平稳"
            elif day_offset < 40:
                phase = "ad_up"
                # 广告加投约 +80%，营收滞后 1 天抬升
                ad_mult = 1.8
                demand_mult = 1.15 if day_offset == 20 else 1.55
                remark = "加投期：广告花费上升，带动 GMV/广告成交上升"
            else:
                phase = "ad_down"
                ad_mult = 0.7
                demand_mult = 0.85
                remark = "降投期：削减广告后，营收回落"

            # 海运涨价期叠加（对应费率曲线 day_offset 在全局 90 天中的位置）
            # d 对应 freight 曲线：用 rate_map
            freight_total = rate_map.get((lane, d))
            if freight_total is None:
                # 若日期不在 90 天费率表内，取最近
                freight_total = D("3500")
            freight_unit = (freight_total / units_per_container).quantize(D("0.0001"))

            # 若处于海运高位，标记 mixed
            idx = None
            for r in freight_rows:
                if r.lane_code == lane and r.rate_date == d:
                    idx = float(r.index_base)
                    break
            if idx and idx >= 1.25 and phase == "ad_up":
                phase = "mixed"
                remark = "加投同时海运上涨：GMV 升但贡献利润被运费侵蚀"
            elif idx and idx >= 1.25 and phase == "ad_down":
                phase = "freight_up"
                remark = "降投 + 海运仍高：营收与贡献双承压"

            base_units = 6 if p.category == "bed" else 10
            units = max(int(round(base_units * demand_mult * RNG.uniform(0.92, 1.08))), 0)
            # 广告加投首日营收尚未完全跟上
            if day_offset == 20:
                units = max(int(round(base_units * 1.1)), 1)

            gmv = D(str(round(units * price, 2)))
            base_ad = 45.0 if p.category == "bed" else 28.0
            ad_spend = D(str(round(base_ad * ad_mult * RNG.uniform(0.95, 1.05), 2)))
            # 广告成交约占 GMV 的一部分，随 ROAS 变化
            roas = 4.2 if phase in {"ad_up", "mixed"} else (3.0 if phase == "baseline" else 2.4)
            ad_sales = D(str(round(min(float(gmv), float(ad_spend) * roas), 2)))
            ocean_total = (freight_unit * units).quantize(D("0.01"))
            cogs = D(str(round(units * cogs_u, 2)))
            contribution = (gmv - cogs - ad_spend - ocean_total).quantize(D("0.01"))

            impact_rows.append(
                SkuCostImpactDaily(
                    metric_date=d,
                    product_sku=sku,
                    marketplace=marketplace,
                    site=site,
                    phase=phase,
                    units=units,
                    gmv_usd=gmv,
                    ad_spend_usd=ad_spend,
                    ad_sales_usd=ad_sales,
                    ocean_freight_unit_usd=freight_unit,
                    ocean_freight_total_usd=ocean_total,
                    cogs_usd=cogs,
                    contribution_usd=contribution,
                    lane_code=lane,
                    remark=remark,
                )
            )

            impressions = int(8000 * ad_mult)
            clicks = max(int(impressions * 0.04), 1)
            acos = (ad_spend / ad_sales).quantize(D("0.0001")) if ad_sales else None
            roas_d = (ad_sales / ad_spend).quantize(D("0.0001")) if ad_spend else None
            story_ads.append(
                AdSpendDaily(
                    spend_date=d,
                    marketplace=marketplace,
                    site=site,
                    product_sku=sku,
                    campaign_type="sponsored_products",
                    impressions=impressions,
                    clicks=clicks,
                    spend_usd=ad_spend,
                    ad_sales_usd=ad_sales,
                    acos=acos,
                    roas=roas_d,
                )
            )
            sessions = max(int(units / 0.04), units + 1)
            story_metrics.append(
                DailySkuMetric(
                    metric_date=d,
                    product_sku=sku,
                    marketplace=marketplace,
                    site=site,
                    units=units,
                    gmv_usd=gmv,
                    refund_units=1 if units > 8 and RNG.random() < 0.08 else 0,
                    refund_usd=D("0"),
                    ad_spend_usd=ad_spend,
                    ad_sales_usd=ad_sales,
                    sessions=sessions,
                    conversion_rate=D(str(round(units / sessions, 4))),
                    available_qty=RNG.randint(40, 180),
                )
            )

    db.add_all(impact_rows)
    db.add_all(story_ads)
    db.add_all(story_metrics)
    db.flush()
    print(
        f"费用影响情景：freight_rates={len(freight_rows)}, "
        f"cost_impact_days={len(impact_rows)}, story_skus={[p.sku for p in story_skus]}"
    )


def _at(day: date, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, 0)


def seed_lifecycle_traces(
    db,
    products: list[Product],
    listings: list[MarketplaceListing],
    orders: list[SalesOrder],
) -> None:
    """为焦点 SKU 写入可追踪的批次链路 + 状态历史 + 时间线事件."""
    focus = [p for p in products if p.category in {"bed", "nightstand"}][:8]
    if not focus:
        focus = products[:6]

    listings_by_sku: dict[str, list[MarketplaceListing]] = {}
    for li in listings:
        listings_by_sku.setdefault(li.sku, []).append(li)

    order_items = db.query(OrderItem).all()
    orders_by_sku: dict[str, list[tuple[SalesOrder, OrderItem]]] = {}
    order_map = {o.order_no: o for o in orders}
    for oi in order_items:
        o = order_map.get(oi.order_no)
        if o:
            orders_by_sku.setdefault(oi.product_sku, []).append((o, oi))

    batches: list[SkuBatch] = []
    prod_hist: list[ProductStatusHistory] = []
    doc_hist: list[DocumentStatusHistory] = []
    events: list[LifecycleEvent] = []
    extra_pos: list[PurchaseOrder] = []
    extra_po_items: list[PurchaseOrderItem] = []
    extra_ships: list[Shipment] = []
    extra_ship_items: list[ShipmentItem] = []
    extra_txns: list[InventoryTransaction] = []
    extra_returns: list[ReturnOrder] = []

    txn_seq = 90000
    rma_seq = 90000
    ship_seq = 9000

    suppliers = [
        ("东莞市宏达家具有限公司", "东莞"),
        ("南康区金典家居厂", "南康"),
        ("佛山市南海兴旺木业", "佛山"),
    ]
    dests = ["US-CA-1", "US-NJ-1", "EU-DE-1", "US-FBA-ONT8"]

    def add_event(**kwargs):
        events.append(LifecycleEvent(**kwargs))

    def add_doc(**kwargs):
        doc_hist.append(DocumentStatusHistory(**kwargs))

    # 产品主数据 / 刊登状态历史
    for p in products:
        launch = p.launch_date or days_ago(180)
        draft_at = _at(launch - timedelta(days=14), 9)
        active_at = _at(launch, 11)
        prod_hist.append(
            ProductStatusHistory(
                product_sku=p.sku,
                scope="product",
                from_status=None,
                to_status="draft",
                changed_at=draft_at,
                reason="新品建档",
                operator="PLM",
            )
        )
        prod_hist.append(
            ProductStatusHistory(
                product_sku=p.sku,
                scope="product",
                from_status="draft",
                to_status="active",
                changed_at=active_at,
                reason="上架放行",
                operator="运营",
            )
        )
        add_event(
            product_sku=p.sku,
            batch_no=None,
            event_time=draft_at,
            stage="product",
            event_type="status_change",
            from_status=None,
            to_status="draft",
            ref_type="product",
            ref_no=p.sku,
            remark="新品建档",
        )
        add_event(
            product_sku=p.sku,
            batch_no=None,
            event_time=active_at,
            stage="product",
            event_type="status_change",
            from_status="draft",
            to_status="active",
            ref_type="product",
            ref_no=p.sku,
            remark="上架放行",
        )

        for li in listings_by_sku.get(p.sku, []):
            list_draft = _at(launch + timedelta(days=3), 15)
            list_active = _at(launch + timedelta(days=5), 10)
            prod_hist.append(
                ProductStatusHistory(
                    product_sku=p.sku,
                    scope="listing",
                    marketplace=li.marketplace,
                    site=li.site,
                    from_status=None,
                    to_status="draft",
                    changed_at=list_draft,
                    reason="创建刊登",
                    operator="运营",
                )
            )
            prod_hist.append(
                ProductStatusHistory(
                    product_sku=p.sku,
                    scope="listing",
                    marketplace=li.marketplace,
                    site=li.site,
                    from_status="draft",
                    to_status="active",
                    changed_at=list_active,
                    reason="刊登上线",
                    operator="运营",
                )
            )
            add_event(
                product_sku=p.sku,
                event_time=list_active,
                stage="listing",
                event_type="status_change",
                from_status="draft",
                to_status="active",
                ref_type="listing",
                ref_no=f"{li.marketplace}-{li.site}",
                remark=f"{li.marketplace} {li.site} 上线",
            )

    # 少数 SKU 追加停售
    for p in focus[:2]:
        inactive_at = _at(TODAY - timedelta(days=20), 16)
        prod_hist.append(
            ProductStatusHistory(
                product_sku=p.sku,
                scope="product",
                from_status="active",
                to_status="active",
                changed_at=inactive_at,
                reason="保留 active，仅记录巡检（Demo）",
                operator="运营",
            )
        )

    # 焦点 SKU：每 SKU 2 条完整供应批次链
    for sku_i, p in enumerate(focus, start=1):
        for batch_i in range(1, 3):
            batch_no = f"LOT-{YEAR}-{sku_i:02d}{batch_i}"
            dest = dests[(sku_i + batch_i) % len(dests)]
            supplier, city = suppliers[(sku_i + batch_i) % len(suppliers)]
            opened = TODAY - timedelta(days=70 - batch_i * 25 - sku_i)
            qty = RNG.choice([80, 100, 120, 150])
            unit = D(str(round(RNG.uniform(35, 140), 2)))
            po_no = f"PO-LOT-{YEAR}-{sku_i:02d}{batch_i}"

            # PO 状态机
            po_confirmed = opened
            po_produced = opened + timedelta(days=12)
            po_shipped = opened + timedelta(days=28)
            po_closed = opened + timedelta(days=55)
            etd = po_shipped
            eta = po_shipped + timedelta(days=26)

            if po_closed <= TODAY:
                po_status = "closed"
                stage = "inventory"
                batch_status = "in_stock"
            elif po_shipped <= TODAY:
                po_status = "shipped"
                stage = "first_leg"
                batch_status = "in_transit"
            elif po_produced <= TODAY:
                po_status = "produced"
                stage = "purchase"
                batch_status = "produced"
            else:
                po_status = "confirmed"
                stage = "purchase"
                batch_status = "confirmed"

            po = PurchaseOrder(
                po_no=po_no,
                supplier_name=supplier,
                factory_city=city,
                order_date=po_confirmed,
                etd=etd,
                eta=eta,
                currency="USD",
                total_amount=(unit * qty).quantize(D("0.01")),
                status=po_status,
            )
            extra_pos.append(po)

            # Document + lifecycle for PO
            transitions = [
                (None, "confirmed", po_confirmed, "下单确认"),
                ("confirmed", "produced", po_produced, "工厂完工"),
                ("produced", "shipped", po_shipped, "工厂发运"),
            ]
            if po_status == "closed":
                transitions.append(("shipped", "closed", po_closed, "头程入库关闭采购"))

            for fr, to, day, remark in transitions:
                if day > TODAY:
                    break
                add_doc(
                    doc_type="po",
                    doc_no=po_no,
                    product_sku=p.sku,
                    batch_no=batch_no,
                    from_status=fr,
                    to_status=to,
                    changed_at=_at(day, 11),
                    remark=remark,
                )
                add_event(
                    product_sku=p.sku,
                    batch_no=batch_no,
                    event_time=_at(day, 11),
                    stage="purchase",
                    event_type="status_change",
                    from_status=fr,
                    to_status=to,
                    ref_type="po",
                    ref_no=po_no,
                    warehouse_code="CN-SZ" if to != "closed" else dest,
                    quantity=qty,
                    remark=remark,
                )

            # 头程物流
            ship_seq += 1
            ship_no = f"SHP-LOT-{ship_seq:04d}"
            ship_booked = po_shipped - timedelta(days=2)
            ship_depart = po_shipped
            ship_eta = eta
            delivered = ship_eta + timedelta(days=1) if ship_eta < TODAY else None
            if delivered and delivered > TODAY:
                delivered = None
            if delivered:
                ship_status = "delivered"
            elif ship_depart <= TODAY:
                ship_status = "in_transit"
            else:
                ship_status = "booked"

            sh = Shipment(
                shipment_no=ship_no,
                shipment_type="first_leg",
                order_no=None,
                carrier=RNG.choice(["Maersk", "COSCO", "MSC"]),
                tracking_no=f"LOTFL{ship_seq}",
                from_warehouse="CN-SZ",
                to_warehouse=dest,
                ship_date=ship_depart,
                eta_date=ship_eta,
                delivered_date=delivered,
                freight_cost_usd=D(str(round(RNG.uniform(2200, 5600), 2))),
                duty_cost_usd=D(str(round(RNG.uniform(300, 900), 2))),
                status=ship_status,
            )
            extra_ships.append(sh)

            for fr, to, day, remark in [
                (None, "booked", ship_booked, "订舱"),
                ("booked", "in_transit", ship_depart, "离港"),
                ("in_transit", "delivered", delivered or ship_eta, "到仓签收"),
            ]:
                if day is None or day > TODAY:
                    continue
                if to == "delivered" and not delivered:
                    continue
                add_doc(
                    doc_type="shipment",
                    doc_no=ship_no,
                    product_sku=p.sku,
                    batch_no=batch_no,
                    from_status=fr,
                    to_status=to,
                    changed_at=_at(day, 14),
                    remark=remark,
                )
                add_event(
                    product_sku=p.sku,
                    batch_no=batch_no,
                    event_time=_at(day, 14),
                    stage="first_leg",
                    event_type="status_change",
                    from_status=fr,
                    to_status=to,
                    ref_type="shipment",
                    ref_no=ship_no,
                    warehouse_code=dest if to == "delivered" else "CN-SZ",
                    quantity=qty,
                    remark=remark,
                )

            # 入库流水（仅已签收）
            if delivered:
                txn_seq += 1
                txn_no = f"INV-LOT-{txn_seq:05d}"
                extra_txns.append(
                    InventoryTransaction(
                        txn_no=txn_no,
                        txn_date=delivered,
                        warehouse_code=dest,
                        product_sku=p.sku,
                        txn_type="inbound",
                        qty_change=qty,
                        ref_no=ship_no,
                        batch_no=batch_no,
                        remark="头程到仓入库",
                    )
                )
                add_event(
                    product_sku=p.sku,
                    batch_no=batch_no,
                    event_time=_at(delivered, 16),
                    stage="inventory",
                    event_type="inbound",
                    from_status="in_transit",
                    to_status="in_stock",
                    ref_type="inventory_txn",
                    ref_no=txn_no,
                    warehouse_code=dest,
                    quantity=qty,
                    remark="头程到仓入库",
                )

            batches.append(
                SkuBatch(
                    batch_no=batch_no,
                    product_sku=p.sku,
                    po_no=po_no,
                    quantity=qty,
                    destination_warehouse=dest,
                    opened_date=opened,
                    current_stage=stage,
                    current_status=batch_status,
                    remark=f"链路批次 → {ship_no}",
                )
            )

            # 暂存 PO item（po_id 稍后 flush 后补）
            extra_po_items.append(
                PurchaseOrderItem(
                    po_id=0,  # placeholder
                    po_no=po_no,
                    product_sku=p.sku,
                    quantity=qty,
                    unit_cost=unit,
                    destination_warehouse=dest,
                    batch_no=batch_no,
                )
            )
            extra_ship_items.append(
                ShipmentItem(
                    shipment_id=0,
                    shipment_no=ship_no,
                    product_sku=p.sku,
                    quantity=qty,
                    carton_qty=max(qty // 2, 1),
                    batch_no=batch_no,
                )
            )

            # 关联已有销售订单：打 batch_no + 订单状态历史
            related = orders_by_sku.get(p.sku, [])
            if related and delivered:
                o, oi = related[min(batch_i - 1, len(related) - 1)]
                oi.batch_no = batch_no
                # 订单状态轨迹
                o_pending = o.order_date
                o_shipped = o.order_date + timedelta(days=1)
                o_done = o.order_date + timedelta(days=4)
                final = o.status
                seq = [
                    (None, "pending", o_pending, "下单"),
                    ("pending", "shipped", o_shipped, "平台发货"),
                ]
                if final in {"completed", "refunded"}:
                    seq.append(("shipped", "completed", o_done, "签收完成"))
                if final == "refunded":
                    seq.append(
                        ("completed", "refunded", o_done + timedelta(days=6), "退款完成")
                    )
                elif final == "cancelled":
                    seq = [
                        (None, "pending", o_pending, "下单"),
                        ("pending", "cancelled", o_shipped, "取消"),
                    ]
                for fr, to, day, remark in seq:
                    add_doc(
                        doc_type="order",
                        doc_no=o.order_no,
                        product_sku=p.sku,
                        batch_no=batch_no,
                        from_status=fr,
                        to_status=to,
                        changed_at=_at(day, 12),
                        remark=remark,
                    )
                    add_event(
                        product_sku=p.sku,
                        batch_no=batch_no,
                        event_time=_at(day, 12),
                        stage="order",
                        event_type="status_change",
                        from_status=fr,
                        to_status=to,
                        ref_type="order",
                        ref_no=o.order_no,
                        warehouse_code=oi.fulfillment_center,
                        quantity=oi.quantity,
                        remark=remark,
                    )

                # 尾程
                ship_seq += 1
                lm_no = f"SHP-LOTLM-{ship_seq:04d}"
                lm_ship = o_shipped
                lm_delivered = o_done if final != "cancelled" else None
                extra_ships.append(
                    Shipment(
                        shipment_no=lm_no,
                        shipment_type="last_mile",
                        order_no=o.order_no,
                        carrier="Amazon Logistics",
                        tracking_no=f"LOTLM{ship_seq}",
                        from_warehouse=oi.fulfillment_center or dest,
                        to_warehouse=None,
                        ship_date=lm_ship,
                        eta_date=lm_ship + timedelta(days=3),
                        delivered_date=lm_delivered,
                        freight_cost_usd=D("12.50"),
                        duty_cost_usd=D("0"),
                        status="delivered" if lm_delivered else "in_transit",
                    )
                )
                extra_ship_items.append(
                    ShipmentItem(
                        shipment_id=0,
                        shipment_no=lm_no,
                        product_sku=p.sku,
                        quantity=oi.quantity,
                        carton_qty=1,
                        batch_no=batch_no,
                    )
                )
                if lm_delivered:
                    add_event(
                        product_sku=p.sku,
                        batch_no=batch_no,
                        event_time=_at(lm_delivered, 18),
                        stage="last_mile",
                        event_type="status_change",
                        from_status="in_transit",
                        to_status="delivered",
                        ref_type="shipment",
                        ref_no=lm_no,
                        quantity=oi.quantity,
                        remark="尾程签收",
                    )

                # 若订单已退款，补一条带 batch 的退货（若还没有）
                if final == "refunded":
                    rma_seq += 1
                    rma_no = f"RMA-LOT-{rma_seq:05d}"
                    opened_r = o_done + timedelta(days=5)
                    extra_returns.append(
                        ReturnOrder(
                            return_no=rma_no,
                            order_no=o.order_no,
                            product_sku=p.sku,
                            marketplace=o.marketplace,
                            site=o.site,
                            reason_code=RNG.choice(
                                ["damaged", "size_issue", "quality", "changed_mind"]
                            ),
                            reason_detail="生命周期 Demo 退货",
                            quantity=oi.quantity,
                            refund_amount_usd=oi.subtotal_usd,
                            opened_date=opened_r,
                            closed_date=opened_r + timedelta(days=2),
                            status="refunded",
                            batch_no=batch_no,
                        )
                    )
                    add_event(
                        product_sku=p.sku,
                        batch_no=batch_no,
                        event_time=_at(opened_r, 13),
                        stage="return",
                        event_type="status_change",
                        from_status="opened",
                        to_status="refunded",
                        ref_type="return",
                        ref_no=rma_no,
                        quantity=oi.quantity,
                        remark="退货退款",
                    )

    # 先写 PO，拿 id
    db.add_all(extra_pos)
    db.flush()
    po_id_map = {po.po_no: po.id for po in extra_pos}
    for item in extra_po_items:
        item.po_id = po_id_map[item.po_no]
    db.add_all(extra_po_items)

    db.add_all(extra_ships)
    db.flush()
    ship_id_map = {s.shipment_no: s.id for s in extra_ships}
    for item in extra_ship_items:
        item.shipment_id = ship_id_map[item.shipment_no]
    db.add_all(extra_ship_items)

    db.add_all(batches)
    db.add_all(prod_hist)
    db.add_all(doc_hist)
    db.add_all(events)
    db.add_all(extra_txns)
    db.add_all(extra_returns)
    db.flush()
    print(
        f"生命周期追踪：batches={len(batches)}, events={len(events)}, "
        f"product_status={len(prod_hist)}, doc_status={len(doc_hist)}"
    )


def seed(*, force: bool = False) -> None:
    init_db()

    # 先短连接探测是否已有数据，并立即关闭，避免占用元数据锁导致 DROP 卡住
    probe = SessionLocal()
    try:
        has_data = probe.query(Product).count() > 0
    finally:
        probe.close()

    if has_data and not force:
        print("业务数据已存在，跳过。如需重建请加 --force")
        return

    if force or has_data:
        # 丢弃连接池中可能仍持有表锁的旧连接
        engine.dispose()
        rebuild_business_tables()
    else:
        for table in reversed(BUSINESS_TABLES):
            table.create(bind=engine, checkfirst=True)

    db = SessionLocal()
    try:
        print(f"锚定日期 TODAY={TODAY}（近一年相对日期）")
        print("写入仓库...")
        warehouses = seed_warehouses(db)
        print("写入产品...")
        products = seed_products(db)
        print("写入平台刊登...")
        listings = seed_listings(db, products)
        print("写入采购单...")
        seed_purchase_orders(db, products)
        print("写入销售订单/退货...")
        orders, _items = seed_orders_and_returns(db, products, listings)
        print("写入库存...")
        seed_inventory(db, products, warehouses)
        print("写入物流...")
        seed_shipments(db, products, orders)
        print("写入广告与日汇总...")
        seed_ads_and_metrics(db, products, listings)
        print("写入海运费率与广告/营收影响情景...")
        seed_freight_and_cost_impact(db, products, listings)
        print("写入批次与生命周期追踪...")
        seed_lifecycle_traces(db, products, listings, orders)

        db.commit()
        print(
            "Demo 数据写入完成："
            f"products={len(products)}, listings={len(listings)}, "
            f"orders={len(orders)}, warehouses={len(warehouses)}"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="删除并重建业务表后灌数")
    args = parser.parse_args()
    seed(force=args.force)
