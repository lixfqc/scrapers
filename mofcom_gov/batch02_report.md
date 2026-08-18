# batch02_report 回传报告

## 一、政策（policy_doc）
| 国家 | 扫描 | 命中 | 新增 | 去重 | 方向不符 | 失败 | 站点 | 栏目数 |
|------|------|------|------|------|----------|------|------|--------|
| BHR | 450 | 24 | 11 | 0 | 11 | 0 | http://bh.mofcom.gov.cn/ | 3 |
| MMR | 356 | 9 | 7 | 0 | 1 | 0 | http://mm.mofcom.gov.cn/ | 3 |
| KHM | {'site_fail': '首页不可达或无栏目'} |
| IDN | 598 | 21 | 9 | 0 | 8 | 0 | http://id.mofcom.gov.cn/ | 8 |
| JOR | 332 | 4 | 2 | 0 | 2 | 0 | http://jo.mofcom.gov.cn/ | 5 |
| LAO | 471 | 4 | 4 | 0 | 0 | 0 | http://la.mofcom.gov.cn/ | 5 |
| MNG | 251 | 4 | 2 | 0 | 2 | 0 | http://mn.mofcom.gov.cn/ | 3 |

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
  - cid=105 加纳 hs=8703 scope=通用（汽油≤1000cc/柴油≤1500cc，ECOWAS CET 低档） rate=5.0% eff=2026-01-01 conf=P0
  - cid=105 加纳 hs=8703 scope=通用（汽油>3000cc/柴油>2500cc，ECOWAS CET 高档） rate=20.0% eff=2026-01-01 conf=P0
  - cid=105 加纳 hs=8703 scope=通用（汽油1000-3000cc/柴油1500-2500cc，ECOWAS CET 中档） rate=10.0% eff=2026-01-01 conf=P0
  - cid=118 肯尼亚 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P1
  - cid=173 尼日利亚 hs=8703 scope=通用 rate=35.0% eff=2026-01-01 conf=P1
  - cid=216 坦桑尼亚 hs=8703 scope=通用 rate=25.0% eff=2026-01-01 conf=P1

## 三、crawl_task_log 按 status
- 成功 = 87
- 失败 = 71
- 方向不符 = 40
- 去重跳过 = 23

## 四、URL 样例（本批新增 policy_doc）
- 153 | 蒙古免除部分食品粮油增值税和关税 | http://mn.mofcom.gov.cn/sqfb/art/2020/art_267a2105c42f495f962feed2e6fa5cb7.html
- 153 | 蒙古首都乌兰巴托将于2024年11月起增设新入境机动车上牌限制 | http://mn.mofcom.gov.cn/sqfb/art/2024/art_09462a24562f4efdbfcff06ad9f48afa.html
- 124 | 老挝将采取措施提高关税管理水平 | http://la.mofcom.gov.cn/lwjj/art/2020/art_4575fd37052549818ae6cb139dd07b24.html
- 124 | 老挝政府对稀土行业加收10%出口关税 | http://la.mofcom.gov.cn/lwjj/art/2023/art_b3c506395dc34aa0ad6a55374904ca42.html
- 124 | 老挝政府对稀土行业加收10%出口关税 | http://la.mofcom.gov.cn/sqfb/art/2023/art_bfbc37b0ff0547faada4475eef2d5038.html

## 五、批2 关税（tariff_rate，本批新增 6 行）
- 新增: 6, 更新(去重): 0, 附加税费新增: 0, 附加税费去重: 0
  - cid=118(?) 巴林 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1 url=customs.gov.bh GCC统一关税（美国FTA除外）
  - 柬埔寨 hs=8703 scope=通用（二手乘用车主流排量档） rate=35.0% eff=2026-01-01 conf=P1 url=customs.gov.kh GDCE AHTN
  - 印尼 hs=8703 scope=通用 rate=10.0% eff=2026-01-01 conf=P1 url=beacukai.go.id（另有PPnBM奢侈品税按排量10-200%属消费税）
  - 约旦 hs=8703 scope=通用 rate=30.0% eff=2026-01-01 conf=P1 url=customs.gov.jo（另有GST16%普遍税费）
  - 老挝 hs=8703 scope=通用（≤2000cc） rate=40.0% eff=2026-01-01 conf=P1 url=customs.gov.la AHTN
  - 蒙古 hs=8703 scope=通用 rate=5.0% eff=2026-01-01 conf=P1 url=customs.gov.mn（WTO TPR统一5%）

## 六、批2 问题清单
- 缅甸(MMR) 8703 关税无可靠公开口径（进口配额+政策多变，搜索口径相互矛盾：calcmytariff 15% 为美国进口税率误引导、cartax.online 0% 不可靠），未落库，需官方税则（缅甸海关/计划财政部）核实后再补。
- 柬埔寨 35% 为二手乘用车主流 headline，special tax(3-45%)/VAT10% 属消费税普遍税费未落；不同排量分档留待阶段B。
- 印尼 CBU 轿车 MFN 约 10%（kickrate 个别税目显示 50% 疑为特定排量档），PPnBM 奢侈品税 10-200% 属消费税类未落 tax_rule，待阶段B按排量细化。
- 巴林/蒙古为统一关税（5%），美国原产 FTA 零关税为特例，普通 MFN 口径已落 5%。
- 政策批耗时 16.5 分钟 + KHM 首次失败（kh 域名不存在→cb 站补跑），关税核实为 websearch 转录 P1。