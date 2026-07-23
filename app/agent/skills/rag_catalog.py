"""RAG 知识检索：类目路由规则."""

from __future__ import annotations

# 文档 category 与问题关键词映射（长词优先匹配）
CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "policy": ("退货规范", "退货政策", "退货处理", "退货", "退款政策", "政策", "制度", "规范"),
    "operations": (
        "库存同步",
        "安全库存",
        "周转率",
        "库龄",
        "调拨",
        "fba 入库",
        "fba",
        "运营",
        "作业规范",
    ),
    "product": ("质检", "产品标准", "阻燃", "包装标准", "静载", "抽检"),
    "sales": ("促销", "定价", "折扣审批", "listing", "上架", "组合售卖", "bundl"),
    "logistics": ("头程", "海运", "订舱", "尾程", "配送", "大件预约", "物流时效"),
    "compliance": ("合规", "carb", "tsca", "ce", "ukca", "ul", "etl", "reach"),
    "ads": ("acos", "roas", "广告", "投放", "否定关键词", "出价"),
    "customer_service": ("差评", "客诉", "客服", "首响", "1-2 星", "异味"),
    "supply_chain": ("采购", "工厂", "交期", "下单", "供应商", "etd", "eta"),
    "finance": ("结算", "对账", "财务", "transfer", "汇率"),
    "data": ("数据口径", "gmv 口径", "指标说明", "问答 agent"),
    "ops_management": ("值班", "升级机制", "p0", "p1", "断货升级"),
}

KNOWN_CATEGORIES = tuple(CATEGORY_ALIASES.keys())
