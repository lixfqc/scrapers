# -*- coding: utf-8 -*-
"""仅生成阶段A-0 回传报告（数据已在库，跳过爬取）"""
import logging

from db import Db
from run_test import stat_report

logging.basicConfig(level=logging.WARNING)
ISSUES = [
    '加纳超龄罚款口径修订：种子媒体口径（10-12年12.5%/P1）已按 GRA 官方税表覆盖为官方口径（10-12年5%/12-15年20%/15-25年50%，P0，effective_date=GSA公告日2026-08-14）；媒体12.5%疑为误报，两表已统一，无重复。',
    '埃塞俄比亚 8703 基础关税 35%（ERCA，载客<10人 ICE 车）已落 tariff_rate goods_scope=通用；但埃塞2024起 ICE 私人进口被禁（内燃机禁令）、2025更新延至SKD/CKD套件，该税率对二手燃油车实际不可用；EV 关税 CBU15%/SKD5%/CKD0%。待阶段B复核。',
    'tax_rule 实际表结构（tax_id/country_id/tax_type/rate/basis/amount/unit/effective_date/expire_date/is_current/source_doc_id/confidence/created_at）无 hs_code/url/source 字段，与交接文档描述不同；upsert 已按实测结构适配，查重键=country_id+tax_type+effective_date+rate。',
    'tariff_rate 每国 hs_code=8703 一条（加纳10%/埃塞35%）；加纳按排量分档5/10/20% 已写入 source 留痕，细分 8703.21-8703.90 档位未单列，留待批量阶段。',
    'crawl_task_log 无政策/无税率的国家本轮仅记已搜索动作（埃塞4篇命中+加纳关税动作），全量268国扩散时按无内容记 status=成功 result_doc_id=NULL。',
]
db = Db()
report_txt = stat_report(db, {'issues': ISSUES})
with open('stageA0_report.md', 'w', encoding='utf-8') as f:
    f.write(report_txt)
print('report written -> stageA0_report.md (%d chars)' % len(report_txt))
db.close()