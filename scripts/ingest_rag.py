#!/usr/bin/env python3
"""将傲基内部文档写入 Chroma 向量库.

用法:
  python scripts/ingest_rag.py          # 已有文档则跳过
  python scripts/ingest_rag.py --force  # 清空后重新灌入
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_core.documents import Document

from app.config import get_settings
from app.db.models import InternalDocument
from app.db.mysql import SessionLocal, init_db
from app.llm import get_embeddings
from app.vector.chroma import get_vector_store

DEMO_DOCS = [
    {
        "doc_id": "policy-return-001",
        "title": "傲基跨境电商退货处理规范",
        "category": "policy",
        "content": """傲基跨境电商退货处理规范（Demo）
1. 美国站 Amazon 订单 30 天内可申请退货。
2. 床架类大件需保留原包装，否则收取 15% 重新包装费。
3. 床头柜等小件可直接 FBA 退回或本地仓验收。
4. 退款需在仓库签收后 3 个工作日内发起。
5. Wayfair 大件退货优先安排本地仓质检，质检不合格走 salvage。""",
    },
    {
        "doc_id": "ops-inventory-001",
        "title": "傲基多仓库存同步规则",
        "category": "operations",
        "content": """傲基多仓库存同步规则（Demo）
1. US-CA-1 与 US-NJ-1 仓每日 02:00 UTC 全量同步。
2. 安全库存：床类 SKU 不低于 30 件，床头柜不低于 50 件。
3. 低于安全库存触发补货预警，由供应链组审批。
4. FBA 仓与海外仓库存分开核算，不可混用可售口径。""",
    },
    {
        "doc_id": "product-bed-001",
        "title": "傲基床类产品质检标准",
        "category": "product",
        "content": """傲基床类产品质检标准（Demo）
1. 床架静载测试 ≥ 300kg。
2. 软包床架海绵密度不低于 25kg/m³。
3. 所有床类产品需通过 CA117 阻燃测试（美国市场）。
4. 出货前抽检比例不少于 5%，重大客诉批次需 100% 复检。""",
    },
    {
        "doc_id": "sales-pricing-001",
        "title": "傲基促销定价审批流程",
        "category": "sales",
        "content": """傲基促销定价审批流程（Demo）
1. 折扣 ≤ 10%：品类负责人审批。
2. 折扣 10%-20%：销售总监审批。
3. 折扣 > 20%：需 VP 审批并附竞品比价截图。
4. 大促（BFCM/Prime Day）专项价目表需提前 14 天锁定。""",
    },
    {
        "doc_id": "logistics-firstleg-001",
        "title": "傲基头程海运订舱与时效标准",
        "category": "logistics",
        "content": """傲基头程海运订舱与时效标准（Demo）
1. 美西线标准时效：开船后 18-25 天到港，到仓再加 3-5 天。
2. 美东线标准时效：开船后 28-35 天到港。
3. 欧线（汉堡）标准时效：开船后 32-40 天。
4. 旺季（8-11 月）需提前 21 天锁舱，紧急空运需供应链总监审批。
5. 单票货值超 5 万美元必须购买货运险。""",
    },
    {
        "doc_id": "logistics-lastmile-001",
        "title": "傲基尾程配送与大件预约规则",
        "category": "logistics",
        "content": """傲基尾程配送与大件预约规则（Demo）
1. 床架/床垫等大件默认预约配送，需提供可联系电话。
2. Amazon FBA 尾程以平台物流为准，客服不可承诺精确送达日。
3. 自营仓发货：美西 UPS/FedEx，标准 2-5 个工作日。
4. 二次派送失败产生的费用由买家承担（不可抗力除外）。""",
    },
    {
        "doc_id": "ops-fba-inbound-001",
        "title": "傲基 FBA 入库与标签规范",
        "category": "operations",
        "content": """傲基 FBA 入库与标签规范（Demo）
1. 每个外箱必须粘贴 FNSKU 与外箱标签，禁止遮挡。
2. 床架配件袋需单独装箱并在箱唛标注 HARDWARE。
3. 混装 SKU 禁止进入同一 FBA shipment（除官方允许的混装计划）。
4. 预约送仓窗口偏差超过 2 小时需重新预约，避免拒收。""",
    },
    {
        "doc_id": "product-nightstand-001",
        "title": "傲基床头柜质检与包装标准",
        "category": "product",
        "content": """傲基床头柜质检与包装标准（Demo）
1. 抽屉推拉 ≥ 5000 次循环测试。
2. USB 充电款需通过 UL 相关安规抽检。
3. 包装跌落测试：1.2m 六面三棱八角，内件无结构性损坏。
4. 五金件齐全率 100%，缺件不得出货。""",
    },
    {
        "doc_id": "product-compliance-us-001",
        "title": "傲基美国市场合规清单",
        "category": "compliance",
        "content": """傲基美国市场合规清单（Demo）
1. 床垫/软包需满足 CA117 或等效阻燃要求。
2. 木质产品需关注 CARB/TSCA 甲醛合规声明。
3. 带电床头柜需保留 UL/ETL 证书档案。
4. 包装与说明书需含英文警告语与组装安全提示。""",
    },
    {
        "doc_id": "product-compliance-eu-001",
        "title": "傲基欧盟/英国市场合规清单",
        "category": "compliance",
        "content": """傲基欧盟/英国市场合规清单（Demo）
1. 需具备 CE/UKCA 相关符合性声明（按品类）。
2. 木质家具关注 REACH 与有害物质限制。
3. 德语/英语说明书至少覆盖安装、承重、儿童安全提示。
4. 德国站大件需关注包装法（VerpackG）注册信息。""",
    },
    {
        "doc_id": "sales-listing-001",
        "title": "傲基多平台 Listing 上架检查表",
        "category": "sales",
        "content": """傲基多平台 Listing 上架检查表（Demo）
1. 标题含尺寸/材质/颜色关键词，禁止夸大承重。
2. 主图白底，副图至少含尺寸图、场景图、细节图。
3. A+ / 富文本需与实物一致，变更需同步全站点。
4. 上架前校验 HS 编码、包装重量与运费模板。""",
    },
    {
        "doc_id": "ads-acos-001",
        "title": "傲基广告 ACOS 管控规则",
        "category": "ads",
        "content": """傲基广告 ACOS 管控规则（Demo）
1. 成熟款目标 ACOS：床类 ≤ 25%，床头柜 ≤ 30%。
2. 新品冷启动 14 天内允许 ACOS 放宽至 40%。
3. 连续 7 天 ACOS 超目标 1.5 倍，自动降出价 10% 并预警。
4. 否定关键词每周至少复盘一次，清理无效搜索词。""",
    },
    {
        "doc_id": "cs-review-001",
        "title": "傲基差评与客诉处理SOP",
        "category": "customer_service",
        "content": """傲基差评与客诉处理SOP（Demo）
1. 1-2 星差评需在 24 小时内首响。
2. 运输破损：优先补发配件；结构性损坏可退货退款。
3. 异味类客诉：引导通风 48-72 小时，仍不接受则走退货。
4. 禁止引导买家删除差评，合规沟通仅限解决问题。""",
    },
    {
        "doc_id": "ops-safety-stock-001",
        "title": "傲基安全库存与周转率标准",
        "category": "operations",
        "content": """傲基安全库存与周转率标准（Demo）
1. 目标周转：床类 45-60 天，床头柜 30-45 天。
2. 库龄 > 90 天需启动清货或站内促销。
3. 库龄 > 180 天必须提交处理方案（降价/移仓/销毁）。
4. 补货量 = 未来 60 天预测销量 - 在库 - 在途 + 安全库存。""",
    },
    {
        "doc_id": "supply-po-001",
        "title": "傲基采购下单与工厂交期管理",
        "category": "supply_chain",
        "content": """傲基采购下单与工厂交期管理（Demo）
1. 标准交期：下单后 30-40 天完工（含质检）。
2. 延期超过 7 天需工厂书面说明，并更新 ETA。
3. 重要大促备货需在大促前 90 天完成下单。
4. 单价变更超 3% 需重新走采购审批。""",
    },
    {
        "doc_id": "finance-settlement-001",
        "title": "傲基平台结算与对账要点",
        "category": "finance",
        "content": """傲基平台结算与对账要点（Demo）
1. Amazon 结算周期以后台 Transfer 为准，需核对费用明细。
2. 退货退款、广告费、仓储费需按 SKU 分摊到毛利模型。
3. 汇率统一按入账日公司中间价折算 USD。
4. 差异超 1% 或金额超 500 USD 需财务复核。""",
    },
    {
        "doc_id": "ops-transfer-001",
        "title": "傲基仓间调拨作业规范",
        "category": "operations",
        "content": """傲基仓间调拨作业规范（Demo）
1. 美西→美东调拨优先满足东区爆款断货。
2. 调拨单需包含 SKU、数量、承运商、预计到达日。
3. 在途库存计入供应链可视，但不计入可售。
4. 调拨差异需在到仓 48 小时内完成盘点关闭。""",
    },
    {
        "doc_id": "sales-bundle-001",
        "title": "傲基床+床头柜组合售卖策略",
        "category": "sales",
        "content": """傲基床+床头柜组合售卖策略（Demo）
1. 推荐组合：Queen 床 + 双抽床头柜 ×2。
2. 组合折扣通常 5%-8%，需走促销审批。
3. Listing 需明确是否含床垫；默认不含。
4. 组合发货尽量同仓出库，降低拆单差评。""",
    },
    {
        "doc_id": "it-data-dictionary-001",
        "title": "傲基业务数据口径说明（问答Agent用）",
        "category": "data",
        "content": """傲基业务数据口径说明（Demo）
1. GMV：成交金额，优先看 gmv_usd。
2. 可售库存：available_qty，不含 reserved 与 in_transit。
3. ACOS = ad_spend_usd / ad_sales_usd。
4. 退货率 = refund_units / units（按同一统计周期）。
5. 站点字段 site：US/UK/DE/CA；平台 marketplace：Amazon/Wayfair/Walmart/OTTO。""",
    },
    {
        "doc_id": "hr-oncall-001",
        "title": "傲基跨境业务值班与升级机制",
        "category": "ops_management",
        "content": """傲基跨境业务值班与升级机制（Demo）
1. 工作日 9:00-22:00（北京时间）运营值班在线。
2. P0（全站断货/大面积发货失败）15 分钟内升级到值班经理。
3. P1（单仓异常/广告超支）2 小时内给出处理方案。
4. 涉及资金与合规问题必须同步财务与法务。""",
    },
]


def _clear_dir_contents(path: Path) -> None:
    """清空目录内容；保留目录本身（Docker volume 挂载点不能 rmtree）."""
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


def _reset_chroma_dir() -> None:
    settings = get_settings()
    if settings.vector_backend_normalized == "http":
        # 远程 Chroma：删除集合而非本地目录
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=int(settings.chroma_port),
            ssl=bool(settings.chroma_ssl),
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        name = settings.chroma_collection_name
        try:
            client.delete_collection(name)
            print(f"已删除远程集合: {name}")
        except Exception as exc:  # noqa: BLE001
            print(f"删除远程集合跳过/失败（可能不存在）: {exc}")
        return

    persist_dir = Path(settings.chroma_persist_dir)
    try:
        # 优先整目录重建（本地开发）；挂载卷会 Device busy，改清内容
        if persist_dir.exists():
            shutil.rmtree(persist_dir)
        persist_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if getattr(exc, "errno", None) != 16:  # Device or resource busy
            raise
        print(f"挂载点无法删除目录本身，改为清空内容: {persist_dir}")
        _clear_dir_contents(persist_dir)


def ingest(*, force: bool = False) -> None:
    init_db()
    # 清缓存，确保 force 后重新初始化向量库
    get_vector_store.cache_clear()
    get_embeddings.cache_clear()

    db = SessionLocal()
    try:
        existing = db.query(InternalDocument).count()
        if existing > 0 and not force:
            print(f"向量文档已存在（{existing} 条），跳过。如需重建请加 --force")
            return

        if force and existing > 0:
            backend = get_settings().vector_backend_normalized
            print(
                f"清理 MySQL internal_documents 与向量库（backend={backend}）..."
            )
            db.query(InternalDocument).delete()
            db.commit()
            _reset_chroma_dir()
            get_vector_store.cache_clear()

        vector_store = get_vector_store()
        documents: list[Document] = []
        for item in DEMO_DOCS:
            documents.append(
                Document(
                    page_content=item["content"],
                    metadata={
                        "doc_id": item["doc_id"],
                        "title": item["title"],
                        "category": item["category"],
                    },
                )
            )

        print(f"开始写入 {len(documents)} 条文档到 Chroma...")
        ids: list[str] = []
        batch_size = 10  # 百炼 embedding 单批上限
        for start in range(0, len(documents), batch_size):
            batch = documents[start : start + batch_size]
            batch_ids = vector_store.add_documents(batch)
            ids.extend(batch_ids)
            print(f"  已写入 {min(start + batch_size, len(documents))}/{len(documents)}")

        for item, chroma_id in zip(DEMO_DOCS, ids):
            db.add(
                InternalDocument(
                    doc_id=item["doc_id"],
                    title=item["title"],
                    category=item["category"],
                    summary=item["content"][:120],
                    chroma_id=chroma_id,
                )
            )

        db.commit()
        print(f"已向 Chroma 写入 {len(documents)} 条内部文档。")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="清空后重新灌入")
    args = parser.parse_args()
    ingest(force=args.force)
