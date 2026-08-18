# batch03_report 回传报告

## 一、政策（policy_doc）
| 国家 | 扫描 | 命中 | 新增 | 去重 | 方向不符 | 失败 | 站点 | 栏目数 |
|------|------|------|------|------|----------|------|------|--------|
| KSA | 666 | 17 | 10 | 0 | 6 | 0 | http://sa.mofcom.gov.cn/ | 5 |

## 二、关税（tariff_rate）
- 新增: 0, 更新(去重): 0, 附加税费新增: 0, 附加税费去重: 0
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.32柴油1500-2500cc） rate=18.0% eff=2026-01-01 conf=P1
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.33柴油>2500cc/8703.24汽油>3000cc） rate=25.71% eff=2026-01-01 conf=P1
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.21汽油≤1000cc，清关年或次年款） rate=12.86% eff=2026-01-01 conf=P1
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.22汽油1000-1500cc） rate=12.5% eff=2026-01-01 conf=P1
  - cid=9 埃及 hs=8703 scope=通用（>1600cc） rate=100.0% eff=2026-01-01 conf=P1
  - cid=9 埃及 hs=8703 scope=通用（≤1600cc） rate=30.0% eff=2026-01-01 conf=P1
  - cid=10 埃塞俄比亚 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P0
  - cid=14 安哥拉 hs=8703 scope=通用 rate=15.0% eff=2026-01-01 conf=P1
  - cid=26 巴林 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=105 加纳 hs=8703 scope=通用（汽油>3000cc/柴油>2500cc，ECOWAS CET 高档） rate=20.0% eff=2026-01-01 conf=P0
  - cid=105 加纳 hs=8703 scope=通用（汽油≤1000cc/柴油≤1500cc，ECOWAS CET 低档） rate=5.0% eff=2026-01-01 conf=P0
  - cid=105 加纳 hs=8703 scope=通用（汽油1000-3000cc/柴油1500-2500cc，ECOWAS CET 中档） rate=10.0% eff=2026-01-01 conf=P0
  - cid=107 柬埔寨 hs=8703 scope=通用（二手乘用车主流排量档） rate=35.0% eff=2026-01-01 conf=P1
  - cid=118 肯尼亚 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P1
  - cid=124 老挝 hs=8703 scope=通用（≤2000cc） rate=40.0% eff=2026-01-01 conf=P1
  - cid=153 蒙古 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=173 尼日利亚 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P1
  - cid=216 坦桑尼亚 hs=8703 scope=通用 rate=25.0% eff=2026-01-01 conf=P1
  - cid=253 印度尼西亚 hs=8703 scope=通用 rate=10.0% eff=2026-01-01 conf=P1
  - cid=257 约旦 hs=8703 scope=通用 rate=30.0% eff=2026-01-01 conf=P1

## 三、crawl_task_log 按 status
- 成功 = 136
- 失败 = 77
- 方向不符 = 67
- 去重跳过 = 23

## 四、URL 样例（本批新增 policy_doc）
- 194 | 萨勒曼国王能源园开工建设电动汽车充电设备生产厂 | http://sa.mofcom.gov.cn/sqxx/art/2025/art_c383a65130bd49ac9ac03ac61fe7c3c8.html
- 194 | Lucid的“沙特制造”汽车大部分将出口 | http://sa.mofcom.gov.cn/sqxx/art/2026/art_cfad2fe7de97489ab3796c098d4f2b54.html
- 194 | 沙特瓦利德王子收购电动汽车制造商Lucid5%的股份 | http://sa.mofcom.gov.cn/sqxx/art/2026/art_3a1d114965b84b50927a35ee978e7812.html
- 194 | 沙特汽车市场分析及开拓沙特汽车市场的建议 | http://sa.mofcom.gov.cn/ztdy/art/2007/art_bb287063627b49c39f3c4e1e87a6909b.html
- 194 | 驻沙特使馆经参处提醒汽车制造企业关注沙汽车燃油经济性标准 | http://sa.mofcom.gov.cn/ggxx/art/2014/art_52d626df0e954fc79e6eeed141f85a99.html

## 五、问题清单
- 政策批耗时 4.7 分钟
## 六、批3 关税（QAT/KSA/THA/TUR/ARE/VNM）

已核实落库 tariff_rate 7 行（QAT 5% / SAU 5% / THA 80% / TUR 40% / ARE 5% / VNM 50%+32% 两档）。缅甸（批2）无可靠口径未落库。
- GCC 三国（卡塔尔/沙特/阿联酋）：统一 5%，沙特 VAT15%、阿联酋 VAT5%、卡塔尔无 VAT。
- 泰国：8703 非东盟 CBU MFN 主流 80%（部分低排量 40-80% 区间），EV 免征。
- 土耳其：非欧盟 MFN 约 40%（关税同盟内欧盟原产 0%）。
- 越南：Decree 73/2025/ND-CP（2025-03-31 生效）8703 主流档 64%→50%、>3000cc 轿车/4WD 45%→32%。

## 七、批3 问题清单
1. 泰国 8703 MFN 口径差异大（部分资料报 19.9% 平均 / 40-80%），主流档暂按 80% 落库，需泰国海关税则复核（细目 8703.2x/3x 排量分档）。
2. 土耳其 40-60% 区间待细分（按排量特别消费税不落 tariff_rate）。
3. 越南 50%/32% 为 Decree 73 主档，其余税目（如 >3000cc 柴油档）未细分，待阶段B复核。
4. GCC 三国车龄限制（阿联酋≤5年等）为准入非税，未落 tax_rule。
5. 沙特 >4.0L 大排量额外消费税（消费税类）暂未落 tax_rule，待官方口径。
