# 阶段A-0 测试回传报告

## 一、policy_doc 新增（非种子）
- 非种子 policy_doc 总数: [('种子', 7), ('爬取', 4)]

## 二、tariff_rate
- 总数: 2
- goods_scope 分布: [('通用', 2)]
  - country_id=105 hs=8703 scope=通用 rate=10.0% base=CIF cur=None eff=2026-01-01 source=加纳海关GRA车辆进口税表（ECOWAS CET，8703按排量分档：汽油≤1000cc/柴油≤1500cc 5%，汽油1000-3000cc/柴油1500-2500cc 10%，>3000cc/>2500cc 20%） url=https://gra.gov.gh/customs/vehicle-importation conf=P0
  - country_id=10 hs=8703 scope=通用 rate=35.0% base=CIF cur=None eff=2026-01-01 source=埃塞海关ERCA 8703载客<10人车辆进口关税35%（另有消费税30-100%按排量、VAT15%、附加税10%，均非基础关税） url=https://customs.erca.gov.et/trade/ conf=P0

## 三、tax_rule（附加税费）
- 总数: 9
  - country_id=105 type=超龄罚款 rate=50.0% basis=CIF eff=2026-08-14 conf=P0
  - country_id=105 type=超龄罚款 rate=5.0% basis=CIF eff=2026-08-14 conf=P0
  - country_id=105 type=超龄罚款 rate=20.0% basis=CIF eff=2026-08-14 conf=P0

## 四、crawl_task_log
- 总数: 35
- 按 status: [('去重跳过', 23), ('成功', 12)]

## 五、URL 样例
- policy_doc 样例: 埃塞俄比亚大力推进电动汽车转型，加速脱碳进程 | http://et.mofcom.gov.cn/jmxw/art/2025/art_d289bb33077c4c77b02470b102c18342.html | mofcom_et子站 | country_id=10
- tariff_rate 样例: hs=8703 url=https://gra.gov.gh/customs/vehicle-importation country_id=105

## 六、问题清单
- 加纳超龄罚款口径修订：种子媒体口径（10-12年12.5%/P1）已按 GRA 官方税表覆盖为官方口径（10-12年5%/12-15年20%/15-25年50%，P0，effective_date=GSA公告日2026-08-14）；媒体12.5%疑为误报，两表已统一，无重复。
- 埃塞俄比亚 8703 基础关税 35%（ERCA，载客<10人 ICE 车）已落 tariff_rate goods_scope=通用；但埃塞2024起 ICE 私人进口被禁（内燃机禁令）、2025更新延至SKD/CKD套件，该税率对二手燃油车实际不可用；EV 关税 CBU15%/SKD5%/CKD0%。待阶段B复核。
- tax_rule 实际表结构（tax_id/country_id/tax_type/rate/basis/amount/unit/effective_date/expire_date/is_current/source_doc_id/confidence/created_at）无 hs_code/url/source 字段，与交接文档描述不同；upsert 已按实测结构适配，查重键=country_id+tax_type+effective_date+rate。
- tariff_rate 每国 hs_code=8703 一条（加纳10%/埃塞35%）；加纳按排量分档5/10/20% 已写入 source 留痕，细分 8703.21-8703.90 档位未单列，留待批量阶段。
- crawl_task_log 无政策/无税率的国家本轮仅记已搜索动作（埃塞4篇命中+加纳关税动作），全量268国扩散时按无内容记 status=成功 result_doc_id=NULL。