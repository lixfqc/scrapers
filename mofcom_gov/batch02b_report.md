# batch02b_report 回传报告

## 一、政策（policy_doc）
| 国家 | 扫描 | 命中 | 新增 | 去重 | 方向不符 | 失败 | 站点 | 栏目数 |
|------|------|------|------|------|----------|------|------|--------|
| KHM | 419 | 9 | 3 | 0 | 3 | 0 | http://cb.mofcom.gov.cn/ | 4 |

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
- 成功 = 90
- 失败 = 71
- 方向不符 = 43
- 去重跳过 = 23

## 四、URL 样例（本批新增 policy_doc）
- 107 | 今年前8个月柬埔寨汽车轮胎出口额达8.7亿美元 | http://cb.mofcom.gov.cn/jmdt/art/2025/art_293adc2820234b518eec9a2ec2222ac1.html
- 107 | 柬埔寨政府大幅下调太阳能设备与电动车进口关税 | http://cb.mofcom.gov.cn/jmdt/art/2026/art_52a8fef1684c4fd89d1a01489777739d.html
- 107 | 柬埔寨质量认证赋能渔业出口 | http://cb.mofcom.gov.cn/jmdt/art/2026/art_62a40717b7f54822819dd0690c793214.html
- 153 | 蒙古免除部分食品粮油增值税和关税 | http://mn.mofcom.gov.cn/sqfb/art/2020/art_267a2105c42f495f962feed2e6fa5cb7.html
- 153 | 蒙古首都乌兰巴托将于2024年11月起增设新入境机动车上牌限制 | http://mn.mofcom.gov.cn/sqfb/art/2024/art_09462a24562f4efdbfcff06ad9f48afa.html

## 五、问题清单
- 政策批耗时 2.7 分钟