# batch05_report 回传报告

## 一、政策（policy_doc）
| 国家 | 扫描 | 命中 | 新增 | 去重 | 方向不符 | 失败 | 站点 | 栏目数 |
|------|------|------|------|------|----------|------|------|--------|
| BLR | 474 | 18 | 4 | 0 | 14 | 0 | http://by.mofcom.gov.cn/ | 5 |
| RUS | {'skipped': '种子政策已有，跳过原文爬取'} |
| UKR | 552 | 11 | 5 | 0 | 6 | 0 | http://ua.mofcom.gov.cn/ | 6 |
| ARG | 300 | 9 | 5 | 0 | 3 | 0 | http://ar.mofcom.gov.cn/ | 8 |
| CHL | 172 | 15 | 13 | 0 | 2 | 0 | http://cl.mofcom.gov.cn/ | 2 |
| MEX | 376 | 32 | 6 | 0 | 26 | 0 | http://mx.mofcom.gov.cn/ | 4 |

## 二、关税（tariff_rate）
- 新增: 0, 更新(去重): 0, 附加税费新增: 0, 附加税费去重: 0
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.22汽油1000-1500cc） rate=12.5% eff=2026-01-01 conf=P1
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.33柴油>2500cc/8703.24汽油>3000cc） rate=25.71% eff=2026-01-01 conf=P1
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.32柴油1500-2500cc） rate=18.0% eff=2026-01-01 conf=P1
  - cid=2 阿尔及利亚 hs=8703 scope=通用（8703.21汽油≤1000cc，清关年或次年款） rate=12.86% eff=2026-01-01 conf=P1
  - cid=5 阿联酋 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=9 埃及 hs=8703 scope=通用（>1600cc） rate=100.0% eff=2026-01-01 conf=P1
  - cid=9 埃及 hs=8703 scope=通用（≤1600cc） rate=30.0% eff=2026-01-01 conf=P1
  - cid=10 埃塞俄比亚 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P0
  - cid=14 安哥拉 hs=8703 scope=通用 rate=15.0% eff=2026-01-01 conf=P1
  - cid=26 巴林 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1
  - cid=84 格鲁吉亚 hs=8703 scope=通用 rate=0.5% eff=2026-01-01 conf=P1
  - cid=90 哈萨克斯坦 hs=8703 scope=通用 rate=15.0% eff=2026-01-01 conf=P1
  - cid=100 吉尔吉斯斯坦 hs=8703 scope=通用 rate=15.0% eff=2026-01-01 conf=P1
  - cid=105 加纳 hs=8703 scope=通用（汽油≤1000cc/柴油≤1500cc，ECOWAS CET 低档） rate=5.0% eff=2026-01-01 conf=P0
  - cid=105 加纳 hs=8703 scope=通用（汽油1000-3000cc/柴油1500-2500cc，ECOWAS CET 中档） rate=10.0% eff=2026-01-01 conf=P0
  - cid=105 加纳 hs=8703 scope=通用（汽油>3000cc/柴油>2500cc，ECOWAS CET 高档） rate=20.0% eff=2026-01-01 conf=P0
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
  - cid=235 乌兹别克斯坦 hs=8703 scope=通用（基础税率档，另按排量从量$0.6-1/cc） rate=15.0% eff=2026-01-01 conf=P1
  - cid=253 印度尼西亚 hs=8703 scope=通用 rate=10.0% eff=2026-01-01 conf=P1
  - cid=257 约旦 hs=8703 scope=通用 rate=30.0% eff=2026-01-01 conf=P1
  - cid=258 越南 hs=8703 scope=通用（主流档≤3000cc，原64%降） rate=50.0% eff=2025-03-31 conf=P1
  - cid=258 越南 hs=8703 scope=通用（轿车/4WD>3000cc档，原45%降） rate=32.0% eff=2025-03-31 conf=P1

## 三、crawl_task_log 按 status
- 成功 = 187
- 方向不符 = 136
- 失败 = 83
- 去重跳过 = 28

## 四、URL 样例（本批新增 policy_doc）
- 163 | 墨汽车工人时薪恐难满足《美墨加协定》要求 | http://mx.mofcom.gov.cn/scxxydy/art/2021/art_4bcd2c5f2e784051ac2f9af70094c4cd.html
- 163 | 墨西哥经济部降低进口水泥关税 | http://mx.mofcom.gov.cn/sqfb/art/2009/art_2bb5f6a8f0ca4b668fa8224b26263fdb.html
- 163 | 墨西哥2010年平均关税水平大幅下调 | http://mx.mofcom.gov.cn/sqfb/art/2010/art_bf65c0a329494c64bda79e8bacfdb315.html
- 163 | 上半年墨西哥海关税收创历史新高 | http://mx.mofcom.gov.cn/jmxw/art/2025/art_9670dc4e1c9b45f3ad6c8a344f6faf7a.html
- 163 | 世贸组织预计关税冲击将在2026年显现 | http://mx.mofcom.gov.cn/jmxw/art/2025/art_b133050f237f4518a28330cb15b2b7b5.html

## 五、问题清单
- 政策批耗时 12.8 分钟

## 六、批5 关税落库（tariff_rate +6，tax_rule +1）

| 国家 | hs_code | rate_pct | duty_base | goods_scope | eff | conf | url |
|------|---------|----------|-----------|-------------|-----|------|-----|
| BLR 白俄罗斯 | 8703 | 15% | CIF | 通用 | 2026-01-01 | P1 | None |
| RUS 俄罗斯 | 8703 | 15% | CIF | 通用 | 2026-01-01 | P1 | gdfs.customs.gov.cn |
| UKR 乌克兰 | 8703 | 10% | CIF | 通用 | 2026-01-01 | P1 | customs.gov.ua |
| ARG 阿根廷 | 8703 | 35% | CIF | 通用 | 2026-01-01 | P1 | None |
| CHL 智利 | 8703 | 6% | CIF | 通用 | 2026-01-01 | P1 | None |
| MEX 墨西哥 | 8703 | 50% | FOB | 通用 | 2025-12-29 | P1 | whitecase.com |

tax_rule 新增：UKR 二手车消费税费（专属附加）公式=基准€50/100(汽油≤/>3000cc)、€75/150(柴油≤/>3500cc)×排量系数×车龄系数，示例 2.0L 汽油 6 年=€600。

## 七、批5 问题清单
1. **墨西哥整车关税 50% 为 2025-12-29 法律化新口径**（White & Case），旧 MFN 20%（dutiable 2026）失效，后续批量阶段注意勿沿用旧口径。
2. 俄罗斯 2025-01-01 起二手车（>3年）按排量从量系数提高 20-38%，本次只落 <3年 从价 15% 档，>3年从量档留待阶段B。
3. 乌克兰消费税为排量×车龄复合公式（非固定比例），tax_rule 以 amount/基准+公式留痕，rate=50 仅为示例基准；白俄/阿根廷/智利车龄准入限制为准入非税未落 tax_rule。
