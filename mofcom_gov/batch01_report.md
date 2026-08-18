# batch01_report 回传报告

## 一、政策（policy_doc）
| 国家 | 扫描 | 命中 | 新增 | 去重 | 方向不符 | 失败 | 站点 | 栏目数 |
|------|------|------|------|------|----------|------|------|--------|
| DZA | 308 | 4 | 1 | 0 | 3 | 0 | http://dz.mofcom.gov.cn/ | 3 |
| AGO | 248 | 3 | 1 | 0 | 2 | 0 | http://ao.mofcom.gov.cn/ | 4 |
| EGY | 445 | 15 | 12 | 0 | 1 | 0 | http://eg.mofcom.gov.cn/ | 7 |
| KEN | 900 | 14 | 5 | 0 | 8 | 0 | http://ke.mofcom.gov.cn/ | 6 |
| NGA | 159 | 12 | 8 | 0 | 0 | 0 | http://ng.mofcom.gov.cn/ | 3 |
| TZA | 524 | 3 | 1 | 0 | 2 | 0 | http://tz.mofcom.gov.cn/ | 4 |

## 二、关税（tariff_rate）
- 新增: 0, 更新(去重): 0, 附加税费新增: 0, 附加税费去重: 0
  - cid=10 埃塞俄比亚 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P0
  - cid=105 加纳 hs=8703 scope=通用（汽油1000-3000cc/柴油1500-2500cc，ECOWAS CET 中档） rate=10.0% eff=2026-01-01 conf=P0
  - cid=105 加纳 hs=8703 scope=通用（汽油≤1000cc/柴油≤1500cc，ECOWAS CET 低档） rate=5.0% eff=2026-01-01 conf=P0
  - cid=105 加纳 hs=8703 scope=通用（汽油>3000cc/柴油>2500cc，ECOWAS CET 高档） rate=20.0% eff=2026-01-01 conf=P0

## 三、crawl_task_log 按 status
- 失败 = 67
- 成功 = 40
- 去重跳过 = 23
- 方向不符 = 16

## 四、URL 样例（本批新增 policy_doc）
- 216 | 东共体7月将采用35%共同对外关税 | http://tz.mofcom.gov.cn/jmxw/art/2022/art_a9c0249adfb9471fa0f240c83fc34a6d.html
- 173 | 尼日利亚国家标准局即将对部分进口商品实施强制性合格评定程序（SONCAP） | http://ng.mofcom.gov.cn/ztdy/art/2005/art_3f230e2f73cc479fa4fdb276d4645cf8.html
- 173 | 尼日利亚国家标准局即将对部分进口商品实施强制性合格评定程序（SONCAP） | http://ng.mofcom.gov.cn/ztdy/art/2005/art_e33b3b64c0214cbf911af79fd82c481c.html
- 173 | 尼强制性合格评定程序（SONCAP）实施日期将暂推延至2005年7月16日 | http://ng.mofcom.gov.cn/ztdy/art/2005/art_75c3ee64103c4ec4afb489c23df13267.html
- 173 | 尼日利亚强制性合格评定程序（SONCAP）实施日期暂推延至2005年9月16日 | http://ng.mofcom.gov.cn/ztdy/art/2005/art_c615aa7d038f4d249bf7efb7c9fb7d1a.html

## 五、问题清单
- 政策批耗时 16.6 分钟
## 批1关税（tariff_rate / tax_rule，web核实结构化落库）

| 国家 | hs_code | goods_scope | rate% | base | 生效 | conf | url |
|---|---|---|---|---|---|---|---|
| AGO 安哥拉 | 8703 | 通用 | 15.0 | CIF | 2026-01-01 | P1 | https://agt.minfin.gov.ao |
| DZA 阿尔及利亚 | 8703 | 通用（8703.22汽油1000-1500cc） | 12.5 | CIF | 2026-01-01 | P1 | https://www.douane.gov.dz |
| DZA 阿尔及利亚 | 8703 | 通用（8703.21汽油≤1000cc，清关年或次年款） | 12.86 | CIF | 2026-01-01 | P1 | https://www.douane.gov.dz |
| DZA 阿尔及利亚 | 8703 | 通用（8703.32柴油1500-2500cc） | 18.0 | CIF | 2026-01-01 | P1 | https://www.douane.gov.dz |
| DZA 阿尔及利亚 | 8703 | 通用（8703.33柴油>2500cc/8703.24汽油>3000cc） | 25.71 | CIF | 2026-01-01 | P1 | https://www.douane.gov.dz |
| EGY 埃及 | 8703 | 通用（≤1600cc） | 30.0 | CIF | 2026-01-01 | P1 | https://customs.gov.eg |
| EGY 埃及 | 8703 | 通用（>1600cc） | 100.0 | CIF | 2026-01-01 | P1 | https://customs.gov.eg |
| ETH 埃塞俄比亚 | 8703 | 通用 | 35.0 | CIF | 2026-01-01 | P0 | https://customs.erca.gov.et/trade/ |
| GHA 加纳 | 8703 | 通用（汽油≤1000cc/柴油≤1500cc，ECOWAS CET 低档） | 5.0 | CIF | 2026-01-01 | P0 | None |
| GHA 加纳 | 8703 | 通用（汽油1000-3000cc/柴油1500-2500cc，ECOWAS CET 中档） | 10.0 | CIF | 2026-01-01 | P0 | https://gra.gov.gh/customs/vehicle-importation |
| GHA 加纳 | 8703 | 通用（汽油>3000cc/柴油>2500cc，ECOWAS CET 高档） | 20.0 | CIF | 2026-01-01 | P0 | None |
| KEN 肯尼亚 | 8703 | 通用 | 35.0 | CIF | 2026-01-01 | P1 | https://www.kra.go.ke |
| NGA 尼日利亚 | 8703 | 通用 | 35.0 | CIF | 2026-01-01 | P1 | https://customs.gov.ng |
| TZA 坦桑尼亚 | 8703 | 通用 | 25.0 | CIF | 2026-01-01 | P1 | https://www.tra.go.tz |

批1 tax_rule 新增：
- TZA 坦桑尼亚：超龄附加消费税 25.0%（CIF，2026-01-01，P1）
- TZA 坦桑尼亚：超龄附加消费税 5.0%（CIF，2026-01-01，P1）

## 问题清单（批1）
1. EAC CET 名义35% vs 坦桑实际25%/肯尼亚35%：EAC 2022版CET将8703提至35%，坦桑日本二手车清关仍25%（出口商2026口径），肯尼亚2023-07起35%；待A电脑复核。
2. 埃及2025-11降税（40->30%、135->100%）以US ITA为准落库，与部分2026资料仍报40/135%矛盾，source留痕。
3. 阿尔及利亚/安哥拉税率来自WITS TRAINS/AGT声明转录（P1），非官方原表逐行。
4. 尼日利亚/肯尼亚二手车超龄惩罚：肯>8年禁入（准入非税）、尼无明确专属附加，未落tax_rule，待阶段B从政策文本复核。
