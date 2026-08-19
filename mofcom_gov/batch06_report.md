# batch06_report 回传报告

## 一、政策（policy_doc）
| 国家 | 扫描 | 命中 | 新增 | 去重 | 方向不符 | 失败 | 站点 | 栏目数 |
|------|------|------|------|------|----------|------|------|--------|
| PHL | 332 | 21 | 14 | 0 | 7 | 0 | http://ph.mofcom.gov.cn/ | 6 |

## 二、关税（tariff_rate）
- 新增: 0, 更新(去重): 0, 附加税费新增: 0, 附加税费去重: 0
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.33柴油>2500cc/8703.24汽油>3000cc） rate=25.71% eff=2026-01-01 conf=P1
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.32柴油1500-2500cc） rate=18.0% eff=2026-01-01 conf=P1
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.22汽油1000-1500cc） rate=12.5% eff=2026-01-01 conf=P1
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.21汽油≤1000cc，清关年或次年款） rate=12.86% eff=2026-01-01 conf=P1
  - cid=4 阿根廷 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P1
  - cid=5 阿联酋 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=9 埃及 hs=8703 scope=通用（≤1600cc） rate=30.0% eff=2026-01-01 conf=P1
  - cid=9 埃及 hs=8703 scope=通用（>1600cc） rate=100.0% eff=2026-01-01 conf=P1
  - cid=10 埃塞俄比亚 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P0
  - cid=14 安哥拉 hs=8703 scope=通用 rate=15.0% eff=2026-01-01 conf=P1
  - cid=26 巴林 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=29 白俄罗斯 hs=8703 scope=通用 rate=15.0% eff=2026-01-01 conf=P1
  - cid=59 俄罗斯 hs=8703 scope=通用 rate=15.0% eff=2026-01-01 conf=P1
  - cid=84 格鲁吉亚 hs=8703 scope=通用 rate=0.5% eff=2026-01-01 conf=P1
  - cid=90 哈萨克斯坦 hs=8703 scope=通用 rate=15.0% eff=2026-01-01 conf=P1
  - cid=100 吉尔吉斯斯坦 hs=8703 scope=通用 rate=15.0% eff=2026-01-01 conf=P1
  - cid=105 加纳 hs=8703 scope=通用（汽油1000-3000cc/柴油1500-2500cc，ECOWAS CET 中档） rate=10.0% eff=2026-01-01 conf=P0
  - cid=105 加纳 hs=8703 scope=通用（汽油>3000cc/柴油>2500cc，ECOWAS CET 高档） rate=20.0% eff=2026-01-01 conf=P0
  - cid=105 加纳 hs=8703 scope=通用（汽油≤1000cc/柴油≤1500cc，ECOWAS CET 低档） rate=5.0% eff=2026-01-01 conf=P0
  - cid=107 柬埔寨 hs=8703 scope=通用（二手乘用车主流排量档） rate=35.0% eff=2026-01-01 conf=P1
  - cid=111 卡塔尔 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=118 肯尼亚 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P1
  - cid=124 老挝 hs=8703 scope=通用（≤2000cc） rate=40.0% eff=2026-01-01 conf=P1
  - cid=153 蒙古 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=163 墨西哥 hs=8703 scope=通用 rate=50.0% eff=2025-12-29 conf=P1
  - cid=173 尼日利亚 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P1
  - cid=194 沙特阿拉伯 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=215 泰国 hs=8703 scope=通用 rate=80.0% eff=2026-01-01 conf=P1
  - cid=216 坦桑尼亚 hs=8703 scope=通用 rate=25.0% eff=2026-01-01 conf=P1
  - cid=224 土耳其 hs=8703 scope=通用 rate=40.0% eff=2026-01-01 conf=P1
  - cid=233 乌克兰 hs=8703 scope=通用 rate=10.0% eff=2026-01-01 conf=P1
  - cid=235 乌兹别克斯坦 hs=8703 scope=通用（基础税率档，另按排量从量$0.6-1/cc） rate=15.0% eff=2026-01-01 conf=P1
  - cid=253 印度尼西亚 hs=8703 scope=通用 rate=10.0% eff=2026-01-01 conf=P1
  - cid=257 约旦 hs=8703 scope=通用 rate=30.0% eff=2026-01-01 conf=P1
  - cid=258 越南 hs=8703 scope=通用（主流档≤3000cc，原64%降） rate=50.0% eff=2025-03-31 conf=P1
  - cid=258 越南 hs=8703 scope=通用（轿车/4WD>3000cc档，原45%降） rate=32.0% eff=2025-03-31 conf=P1
  - cid=263 智利 hs=8703 scope=通用 rate=6.0% eff=2026-01-01 conf=P1

## 三、crawl_task_log 按 status
- 成功 = 208
- 方向不符 = 143
- 失败 = 84
- 去重跳过 = 28

## 四、URL 样例（本批新增 policy_doc）
- 70 | 中国政府五部门：在有条件的自贸试验区和自贸港试点有关进口税收政策措施 | http://ph.mofcom.gov.cn/zgyw/art/2024/art_3fd1934b9f4341dba0f43be3cd93114c.html
- 70 | 推动汽车低碳合作，促进全球绿色发展 | http://ph.mofcom.gov.cn/zgyw/art/2024/art_cb01650acd59497f8136ab374a9b67cd.html
- 70 | 菲关税削减导致近90亿比索的收入损失 | http://ph.mofcom.gov.cn/jmxw/art/2024/art_04250335c5384fde9dc0465283b317e5.html
- 70 | 研究显示特朗普关税将导致韩国经济收缩 | http://ph.mofcom.gov.cn/jmxw/art/2024/art_4e2aeaf16e30475aa87f1866520b729d.html
- 70 | 菲参议长埃斯库德罗称，新农业关税法将提高菲稻米产量 | http://ph.mofcom.gov.cn/jmxw/art/2024/art_a50dba10aeb943f6b68d44a0073235fe.html

## 五、问题清单
- 政策批耗时 2.7 分钟

## 五、批6 关税说明（PHL 菲律宾）
- 菲律宾 8703 关税**未落库**：官方 Tariff Commission PTF（AHTN 2022）精确税目税率无法程序化获取；公开口径差距过大（二手车 40% / 乘用车按排量 15-100% / MFN 平均 ~6%），按"不猜测、待官方税则核实"原则处理。

## 六、批6 问题清单
1. 菲律宾 8703 关税需 Tariff Commission PTF（finder.tariffcommission.gov.ph）官方税目核实后补落，建议批量扩散阶段用 AHTN 2022 逐税目转录。
2. 菲律宾曾对 8703 征收临时保障关税（P70,000/unit，2021 年前后已终止），勿与现行 MFN 混淆。
3. 菲律宾二手车准入为行政限制（仅左舵、装运前注册≥6个月、DTI CAI 授权），非税费，未落 tax_rule。
4. 菲律宾 VAT 12%（CIF+关税为基）为普遍税费，未落 tax_rule。

## 七、34 国批次完成总览（政策 34/34，关税 30/34）
- 关税缺口 4 国均待官方税则核实：MMR（缅甸无可靠口径）、TJK（塔吉克 8703 税目未公开）、AZE（阿塞拜疆按排量从量结构）、PHL（菲律宾 PTF 税目待转录）。
- 政策 34 国全部完成，全部国家均有爬取记录（含种子 5 国跳过政策原文）。
