# batch04_report 回传报告

## 一、政策（policy_doc）
| 国家 | 扫描 | 命中 | 新增 | 去重 | 方向不符 | 失败 | 站点 | 栏目数 |
|------|------|------|------|------|----------|------|------|--------|
| KAZ | {'skipped': '种子政策已有，跳过原文爬取'} |
| KGZ | 316 | 9 | 4 | 0 | 5 | 0 | http://kg.mofcom.gov.cn/ | 3 |
| TJK | 319 | 8 | 4 | 0 | 4 | 0 | http://tj.mofcom.gov.cn/ | 4 |
| UZB | {'skipped': '种子政策已有，跳过原文爬取'} |
| GEO | {'skipped': '种子政策已有，跳过原文爬取'} |
| AZE | 360 | 12 | 2 | 0 | 9 | 0 | http://az.mofcom.gov.cn/ | 3 |

## 二、关税（tariff_rate）
- 新增: 0, 更新(去重): 0, 附加税费新增: 0, 附加税费去重: 0
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.22汽油1000-1500cc） rate=12.5% eff=2026-01-01 conf=P1
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.32柴油1500-2500cc） rate=18.0% eff=2026-01-01 conf=P1
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.33柴油>2500cc/8703.24汽油>3000cc） rate=25.71% eff=2026-01-01 conf=P1
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.21汽油≤1000cc，清关年或次年款） rate=12.86% eff=2026-01-01 conf=P1
  - cid=5 阿联酋 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=9 埃及 hs=8703 scope=通用（≤1600cc） rate=30.0% eff=2026-01-01 conf=P1
  - cid=9 埃及 hs=8703 scope=通用（>1600cc） rate=100.0% eff=2026-01-01 conf=P1
  - cid=10 埃塞俄比亚 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P0
  - cid=14 安哥拉 hs=8703 scope=通用 rate=15.0% eff=2026-01-01 conf=P1
  - cid=26 巴林 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=105 加纳 hs=8703 scope=通用（汽油>3000cc/柴油>2500cc，ECOWAS CET 高档） rate=20.0% eff=2026-01-01 conf=P0
  - cid=105 加纳 hs=8703 scope=通用（汽油1000-3000cc/柴油1500-2500cc，ECOWAS CET 中档） rate=10.0% eff=2026-01-01 conf=P0
  - cid=105 加纳 hs=8703 scope=通用（汽油≤1000cc/柴油≤1500cc，ECOWAS CET 低档） rate=5.0% eff=2026-01-01 conf=P0
  - cid=107 柬埔寨 hs=8703 scope=通用（二手乘用车主流排量档） rate=35.0% eff=2026-01-01 conf=P1
  - cid=111 卡塔尔 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=118 肯尼亚 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P1
  - cid=124 老挝 hs=8703 scope=通用（≤2000cc） rate=40.0% eff=2026-01-01 conf=P1
  - cid=153 蒙古 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=173 尼日利亚 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P1
  - cid=194 沙特阿拉伯 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=215 泰国 hs=8703 scope=通用 rate=80.0% eff=2026-01-01 conf=P1
  - cid=216 坦桑尼亚 hs=8703 scope=通用 rate=25.0% eff=2026-01-01 conf=P1
  - cid=224 土耳其 hs=8703 scope=通用 rate=40.0% eff=2026-01-01 conf=P1
  - cid=253 印度尼西亚 hs=8703 scope=通用 rate=10.0% eff=2026-01-01 conf=P1
  - cid=257 约旦 hs=8703 scope=通用 rate=30.0% eff=2026-01-01 conf=P1
  - cid=258 越南 hs=8703 scope=通用（主流档≤3000cc，原64%降） rate=50.0% eff=2025-03-31 conf=P1
  - cid=258 越南 hs=8703 scope=通用（轿车/4WD>3000cc档，原45%降） rate=32.0% eff=2025-03-31 conf=P1

## 三、crawl_task_log 按 status
- 成功 = 153
- 方向不符 = 85
- 失败 = 77
- 去重跳过 = 23

## 四、URL 样例（本批新增 policy_doc）
- 8 | 4月阿汽车价格增速放缓 | http://az.mofcom.gov.cn/jmxw/art/2026/art_76c23d010cc644939c3243dcbe114687.html
- 8 | 阿塞拜疆拟引入碳税及排放交易机制 | http://az.mofcom.gov.cn/jmxw/art/2026/art_deec5268a03c46bcb072c52d60e3f21a.html
- 214 | 塔吉克汽车市场概况 | http://tj.mofcom.gov.cn/scdy/art/2007/art_3b7212a439c246f4a8d1baff18e9a113.html
- 214 | 塔投资项目简介之三：汽车制造，电子和化学工业 | http://tj.mofcom.gov.cn/scdy/art/2007/art_44d767e8e6c949c587bf2a9b90df462b.html
- 214 | 2025年底杜尚别计划建成500个电动汽车充电桩 | http://tj.mofcom.gov.cn/jmxw/art/2025/art_57df78964b6e47cf9905b05e48b2e827.html

## 五、问题清单
- 政策批耗时 6.7 分钟

## 六、批4 关税落库（tariff_rate +4，tax_rule 不变）

| 国家 | hs_code | rate_pct | goods_scope | eff | conf | url |
|------|---------|----------|-------------|-----|------|-----|
| KAZ 哈萨克斯坦 | 8703 | 15% | 通用 | 2026-01-01 | P1 | 10100.com/article/83374395 |
| KGZ 吉尔吉斯斯坦 | 8703 | 15% | 通用 | 2026-01-01 | P1 | None |
| UZB 乌兹别克斯坦 | 8703 | 15% | 通用（基础档+排量从量$0.6-1/cc） | 2026-01-01 | P1 | None |
| GEO 格鲁吉亚 | 8703 | 0.5% | 通用 | 2026-01-01 | P1 | None |

来源口径：KAZ/KGZ 为 EAEU 共同关税（<3年从价15%，3年以上按排量 €/cc 从量档）；UZB 2023-06 总统令优惠期 2025-12-31 到期、2026-01-01 恢复标准 15%+从量；GEO 8703 关税 0.5% 且免征 VAT（格海关法）。

## 七、批4 问题清单
1. 塔吉克斯坦 8703 官方税则口径未公开（官方 0-15%、贸易加权约 7%），待官方税则核实后补落。
2. 阿塞拜疆汽车关税为按排量从量结构（新车 $0.4-0.7/cc、二手车 $0.7-1.4/cc），且 2026 起调整车龄>7年消费税，暂不落，待官方从量表核实。
3. 哈萨克种子 tax_rule 记 VAT 16%，与现行 12% 不符（疑过期），留待阶段B统一校验。
4. KAZ/KGZ 二手车分龄从量档（€1.5-5.7/cc）与 UZB 排量从量档（$0.6-1/cc）为附加计征结构，留待阶段B细分税目。
5. crawl_task_log 对 url=None 的落库曾报 NOT NULL 违规，已修复（log_crawl 内部兜底占位 target_url）。
