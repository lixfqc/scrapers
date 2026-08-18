# -*- coding: utf-8 -*-
"""
关税链路（T2）：将已核实的结构化税率落 tariff_rate（基础海关关税），
二手车专属附加税费（超龄罚款/排量额外/右舵惩罚）落 tax_rule。
阶段A-0 用 2 国：加纳（GRA 官网超龄罚款场景）+ 埃塞俄比亚（默认'通用'）。
- goods_scope 判定不误判：加纳超龄罚款进 tax_rule，不进 tariff_rate
- 幂等：tariff_rate UNIQUE(country_id,hs_code,tariff_type,effective_date)、tax_rule 手动查重
"""
import logging
import time

from db import Db
from goods_scope import judge_goods_scope, has_age_extra


def _downgrade(conf):
    order = {'P0': 'P1', 'P1': 'P2', 'P2': 'P2'}
    return order.get(conf, 'P1')


# 结构化税率来源库：每国一组 tariff_rate 条目 + tax_rule 附加税费
# effective_date 为税率生效年（取 2026-01-01 当前版）
TARIFF_SOURCE = {
    # 加纳：GRA 车辆进口税表（官方一手，P0）
    # 8703 载客车辆按排量分档 5/10/20%（CIF），与新旧无关 -> goods_scope='通用'
    'GHA': {
        'site': 'GRA加纳海关',
        # 关税分档规则（2026-08-18 更新）：按排量分档落多行（ECOWAS CET 5/10/20%），
        # goods_scope 注明各排量档位；source 保留完整分档说明；禁止只落一行中档
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 5.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（汽油≤1000cc/柴油≤1500cc，ECOWAS CET 低档）',
             'source': '加纳海关GRA车辆进口税表（ECOWAS CET 8703按排量分档：汽油≤1000cc/柴油≤1500cc 5%，汽油1000-3000cc/柴油1500-2500cc 10%，>3000cc/>2500cc 20%）',
             'url': 'https://gra.gov.gh/customs/vehicle-importation', 'confidence': 'P0'},
            {'hs_code': '8703', 'rate_pct': 10.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（汽油1000-3000cc/柴油1500-2500cc，ECOWAS CET 中档）',
             'source': '加纳海关GRA车辆进口税表（ECOWAS CET 8703按排量分档：汽油≤1000cc/柴油≤1500cc 5%，汽油1000-3000cc/柴油1500-2500cc 10%，>3000cc/>2500cc 20%）',
             'url': 'https://gra.gov.gh/customs/vehicle-importation', 'confidence': 'P0'},
            {'hs_code': '8703', 'rate_pct': 20.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（汽油>3000cc/柴油>2500cc，ECOWAS CET 高档）',
             'source': '加纳海关GRA车辆进口税表（ECOWAS CET 8703按排量分档：汽油≤1000cc/柴油≤1500cc 5%，汽油1000-3000cc/柴油1500-2500cc 10%，>3000cc/>2500cc 20%）',
             'url': 'https://gra.gov.gh/customs/vehicle-importation', 'confidence': 'P0'},
        ],
        'tax_rules': [
            # 超龄罚款：二手车专属附加税费 -> tax_rule，非 goods_scope
            # 以 GSA 公告生效日 2026-08-14 为 effective_date，官方口径覆盖媒体口径（12.5%->5%）
            {'tax_type': '超龄罚款', 'rate': 5.0, 'basis': 'CIF',
             'effective_date': '2026-08-14', 'confidence': 'P0',
             'note': '车龄>10且≤12年（GSA公告GSA/DGS/PN/26/09，按生产年份计）'},
            {'tax_type': '超龄罚款', 'rate': 20.0, 'basis': 'CIF',
             'effective_date': '2026-08-14', 'confidence': 'P0',
             'note': '车龄>12且≤15年（GSA公告GSA/DGS/PN/26/09，按生产年份计）'},
            {'tax_type': '超龄罚款', 'rate': 50.0, 'basis': 'CIF',
             'effective_date': '2026-08-14', 'confidence': 'P0',
             'note': '车龄>15且≤25年（GSA公告GSA/DGS/PN/26/09，按生产年份计）'},
        ],
    },
    # 埃塞俄比亚：ERCA 海关（官方口径），8703 载客<10人 关税 35%（CIF），无二手车单列栏 -> '通用'
    'ETH': {
        'site': 'ERCA埃塞海关',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 35.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '埃塞海关ERCA 8703载客<10人车辆进口关税35%（另有消费税30-100%按排量、VAT15%、附加税10%，均非基础关税）',
             'url': 'https://customs.erca.gov.et/trade/', 'confidence': 'P0'},
        ],
        'tax_rules': [],
    },
    # 阿尔及利亚：douane.gov.dz 海关税则第87章（WITS TRAINS 转录，P1），8703 按排量分档
    'DZA': {
        'site': '阿尔及利亚海关douane.gov.dz',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 12.86, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（8703.21汽油≤1000cc，清关年或次年款）',
             'source': '阿尔及利亚海关税则第8703.21目（汽油≤1000cc 12.86%，清关年或次年产）',
             'url': 'https://www.douane.gov.dz', 'confidence': 'P1'},
            {'hs_code': '8703', 'rate_pct': 12.5, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（8703.22汽油1000-1500cc）',
             'source': '阿尔及利亚海关税则第8703.22目（汽油1000-1500cc 12.5%）',
             'url': 'https://www.douane.gov.dz', 'confidence': 'P1'},
            {'hs_code': '8703', 'rate_pct': 18.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（8703.32柴油1500-2500cc）',
             'source': '阿尔及利亚海关税则第8703.32目（柴油1500-2500cc 18%）',
             'url': 'https://www.douane.gov.dz', 'confidence': 'P1'},
            {'hs_code': '8703', 'rate_pct': 25.71, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（8703.33柴油>2500cc/8703.24汽油>3000cc）',
             'source': '阿尔及利亚海关税则第8703.33目（柴油>2500cc 25.71%）',
             'url': 'https://www.douane.gov.dz', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 安哥拉：AGT Pauta Aduaneira 2022（官方声明转录，P1），普通乘用车关税 25%->15%
    'AGO': {
        'site': '安哥拉AGT税务总局',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 15.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '安哥拉Pauta Aduaneira 2022（AGT官方：普通乘用车进口关税由25%降至15%，高档车Lexus由30%降至20%）',
             'url': 'https://agt.minfin.gov.ao', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 埃及：埃及海关关税表（US ITA trade.gov 2025-11 转录，P1），8703 按排量分档；车龄≤3年为准入限制
    'EGY': {
        'site': '埃及海关',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 30.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（≤1600cc）',
             'source': '埃及海关关税表（US ITA 2025-11：1600cc以下汽车关税由40%降至30%，非EU原产地）',
             'url': 'https://customs.gov.eg', 'confidence': 'P1'},
            {'hs_code': '8703', 'rate_pct': 100.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（>1600cc）',
             'source': '埃及海关关税表（US ITA 2025-11：1600cc以上汽车关税由135%降至100%，非EU原产地）',
             'url': 'https://customs.gov.eg', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 肯尼亚：EAC共同对外关税2022修订（P1），8703由25%提至35%
    'KEN': {
        'site': '肯尼亚KRA海关/EAC CET',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 35.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '东共体共同对外关税EAC CET 2022修订（8702/8703/8704由25%提至35%，肯尼亚2023-07起实施；另有IDF3.5%/RDL2.5%/VAT16%普遍税费）',
             'url': 'https://www.kra.go.ke', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 尼日利亚：尼联邦税则/NCS（ECOWAS CET，P1），8703=35%
    'NGA': {
        'site': '尼日利亚海关NCS',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 35.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '尼日利亚联邦税则/尼海关NCS（ECOWAS CET 8703=35% CIF；另有ECOWAS征费0.5%、ETLS 0.2%、VAT 7.5%普遍税费）',
             'url': 'https://customs.gov.ng', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 坦桑尼亚：坦海关/TRA（EAC CET 25% 清关口径，P1）+ 超龄附加消费税（二手车专属->tax_rule）
    'TZA': {
        'site': '坦桑尼亚海关TRA/EAC CET',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 25.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '坦桑尼亚海关关税表/EAC共同对外关税（8703进口关税25% CIF；另有>2000cc消费税10%、1000-2000cc 5%、VAT20%普遍税费；EAC CET名义35%差异见问题清单）',
             'url': 'https://www.tra.go.tz', 'confidence': 'P1'},
        ],
        'tax_rules': [
            # 二手车专属附加：车龄>8年额外消费税（超龄罚款类）-> tax_rule 而非 goods_scope
            {'tax_type': '超龄附加消费税', 'rate': 25.0, 'basis': 'CIF',
             'effective_date': '2026-01-01', 'confidence': 'P1',
             'note': '车龄>8年（自生产年份计）非营运车额外消费税25%'},
            {'tax_type': '超龄附加消费税', 'rate': 5.0, 'basis': 'CIF',
             'effective_date': '2026-01-01', 'confidence': 'P1',
             'note': '车龄>8年（自生产年份计）营运utility车额外消费税5%'},
        ],
    },
    # 巴林：GCC 统一关税（除烟酒外大部分进口商品 5%，美国FTA除外），8703 通用 5%
    'BHR': {
        'site': '巴林海关/GCC统一关税',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 5.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '巴林海关GCC统一关税（US ITA 2025-12：除烟酒外大部分非GCC进口商品 5%；美国原产FTA零关税）',
             'url': 'https://www.customs.gov.bh/en/tariff-finder', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 柬埔寨：GDCE AHTN 税则，二手乘用车主流 35%（含EV>3000cc 高档）；另有特殊税(Special Tax)按排量 3-45% 属消费税
    'KHM': {
        'site': '柬埔寨海关GDCE',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 35.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（二手乘用车主流排量档）',
             'source': '柬埔寨海关GDCE AHTN税则（8703载客<10人进口关税0-35%，二手车主流按35%；另有特殊税Special Tax按排量3-45%、VAT10%普遍税费）',
             'url': 'https://customs.gov.kh/en', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 印尼：Bea Masuk CBU 轿车 MFN 主流 10%（PMK 简化；另有奢侈品税PPnBM按排量10-200%属消费税），二手车商业进口受严格配额
    'IDN': {
        'site': '印尼海关DJBC',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 10.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '印尼Bea Masuk（8703 CBU轿车MFN约10% CIF；另有奢侈品税PPnBM按排量10-200%、PPN11%普遍税费；二手车商业进口受严格配额）',
             'url': 'https://www.beacukai.go.id', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 约旦：Jordan Customs 8703 轿车关税（GST 16% 普遍），二手车主流 30%
    'JOR': {
        'site': '约旦海关Jordan Customs',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 30.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '约旦海关关税表（8703轿车进口关税30% CIF；另有GST 16%、车辆特别税Special Tax普遍税费）',
             'url': 'https://customs.gov.jo', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 老挝：老挝海关 AHTN 税则（按类型/车龄/排量计），乘用车主流 ≤2000cc 档 40%
    'LAO': {
        'site': '老挝海关AHTN税则',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 40.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（≤2000cc）',
             'source': '老挝海关AHTN税则（8703乘用车关税0-40% ASEAN口径，主流≤2000cc档40%；按类型/车龄/排量评估，>2000cc档待核）',
             'url': 'https://www.customs.gov.la', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 蒙古：蒙古统一关税 5%（WTO TPR 口径），8703 通用 5%
    'MNG': {
        'site': '蒙古海关',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 5.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '蒙古统一关税（WTO TPR：多数进口商品从价关税5%；8703通用5%）',
             'url': 'https://www.customs.gov.mn', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 卡塔尔：GCC 统一关税（除烟酒外大部分进口商品 5%，无VAT），8703 通用 5%
    'QAT': {
        'site': '卡塔尔海关/GCC统一关税',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 5.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '卡塔尔海关GCC统一关税（GCC六国乘用车统一5%；卡塔尔无VAT，EV免注册费）',
             'url': 'https://www.customs.gov.qa', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 沙特：GCC 统一关税 5%，VAT 15%（普遍），8703 通用 5%；SABER 认证准入；>4.0L 大排量另有消费税
    'SAU': {
        'site': '沙特海关/GCC统一关税',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 5.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '沙特海关GCC统一关税（乘用车5% CIF；VAT 15%普遍；SABER/SASO认证准入；>4.0L大排量另有消费税）',
             'url': 'https://zatca.gov.sa', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 泰国：泰国海关税则 8703 乘用车 MFN 主流 80%（部分车型 40-80% 区间），EV 免税（EV3.5 政策）
    'THA': {
        'site': '泰国海关',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 80.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '泰国海关税则（8703乘用车非东盟CBU MFN主流80%，部分低排量40-80%区间待核；EV免征关税；另有消费税按排量8-50%、VAT 7%）',
             'url': 'https://www.customs.go.th', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 土耳其：非欧盟 8703 乘用车 MFN 40%（关税同盟内欧盟原产0%），另有特别消费税按排量
    'TUR': {
        'site': '土耳其海关',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 40.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '土耳其海关关税（非欧盟8703乘用车MFN约40%，范围40-60%；关税同盟内欧盟原产0%；另有特别消费税按排量、VAT 20%）',
             'url': 'https://ticaret.gov.tr', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 阿联酋：GCC 统一关税 5%，VAT 5%（普遍），8703 通用 5%；车龄≤5年准入
    'ARE': {
        'site': '阿联酋海关/GCC统一关税',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 5.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '阿联酋海关GCC统一关税（乘用车5% CIF；VAT 5%普遍；车龄≤5年准入限制）',
             'url': 'https://www.customs.gov.ae', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 越南：Decree 73/2025/ND-CP（2025-03-31生效）8703 MFN 由64%降至50%（主流档）、8703.24 轿车/4WD由45%降至32%
    'VNM': {
        'site': '越南海关',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 50.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2025-03-31', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（主流档≤3000cc，原64%降）',
             'source': '越南Decree 73/2025/ND-CP（2025-03-31生效）：8703乘用车MFN由64%降至50%（8703.23.63/57等主流档）；另有特别消费税按排量35-150%、VAT 10%；车龄>5年禁入',
             'url': 'https://www.customs.gov.vn', 'confidence': 'P1'},
            {'hs_code': '8703', 'rate_pct': 32.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2025-03-31', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（轿车/4WD>3000cc档，原45%降）',
             'source': '越南Decree 73/2025/ND-CP（2025-03-31生效）：8703.24.51轿车/4WD(>3000cc)MFN由45%降至32%；另有特别消费税按排量35-150%、VAT 10%；车龄>5年禁入',
             'url': 'https://www.customs.gov.vn', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 哈萨克斯坦：EAEU 关税，汽油/柴油车 <3年从价 15%（主流）；EV/串联混动零关税；>3000cc 另消费税100坚戈/cc
    'KAZ': {
        'site': '哈萨克斯坦海关（EAEU）',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 15.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '哈萨克斯坦EAEU关税（汽油/柴油车<3年从价15%为主；3-5年€1.5-3.6/cc、>5年€3.0-5.7/cc分龄从量档；EV/串联混动零关税；>3000cc另消费税100坚戈/cc、特别消费税10%、报废回收费；VAT 12%）',
             'url': 'https://www.10100.com/article/83374395', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 吉尔吉斯斯坦：EAEU 成员，8703 通用 15%；EV 免税配额
    'KGZ': {
        'site': '吉尔吉斯斯坦海关（EAEU）',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 15.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '吉尔吉斯斯坦EAEU关税（8703新车/通用15%，2019年由17%降；二手车分龄档口径混乱5-22%；EV免税配额用完后15%）',
             'url': None, 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 乌兹别克斯坦：2023-06总统令优惠期（2025-12-31止）到期，2026-01-01恢复标准税率 15%+排量从量$0.6-1/cc
    'UZB': {
        'site': '乌兹别克斯坦海关',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 15.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'goods_scope': '通用（基础税率档，另按排量从量$0.6-1/cc）',
             'source': '乌兹别克斯坦关税（2023-06总统令优惠期2025-12-31止；2026-01-01恢复标准：燃油车基础15%+排量从量$0.6/cc(1200-1500cc)/$0.8/cc(1500-1800cc)/$1/cc(1800-3000cc)；二手车1-3年回收费90-480BCU；VAT12%；EV零关税）',
             'url': None, 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 格鲁吉亚：8703 关税 0.5%，对乘用车8703免征增值税（格海关法），消费税按排量5-100%
    'GEO': {
        'site': '格鲁吉亚海关',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 0.5, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '格鲁吉亚海关法（8703乘用车进口关税0.5%；8703免征增值税；消费税按排量5-100%2026调整后；其他商品VAT 18%）',
             'url': None, 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 白俄罗斯：EAEU 共同关税，8703 <3年从价 15%；>3年按排量从量
    'BLR': {
        'site': '白俄罗斯海关（EAEU）',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 15.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '白俄罗斯EAEU共同关税（8703<3年从价15%；>3年按排量€/cc从量档）',
             'url': None, 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 俄罗斯：EAEU 共同关税，8703 <3年从价 15%；2025-01-01 起二手车（>3年）按排量从量系数提高 20-38%
    'RUS': {
        'site': '俄罗斯海关（EAEU）',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 15.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '俄罗斯EAEU关税（8703<3年从价15%；2025-01-01起二手车>3年按排量从量单位税率提高20-38%，哈尔滨海关转俄海关在线2024-12-05）',
             'url': 'http://gdfs.customs.gov.cn', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 乌克兰：8703 MFN 10% CIF；二手车专属消费税=基准×排量系数×车龄系数
    'UKR': {
        'site': '乌克兰国家海关署',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 10.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '乌克兰8703 MFN进口关税10% CIF（无美韩FTA；EV免关税/消费税/VAT至2026-01-01；VAT20%）',
             'url': 'https://customs.gov.ua', 'confidence': 'P1'},
        ],
        'tax_rules': [
            {'tax_type': '二手车消费税费（专属附加）', 'rate': 50.0, 'basis': 'CIF',
             'effective_date': '2026-01-01', 'confidence': 'P1',
             'note': '公式=基准€50(汽油≤3000cc)/€100(>3000cc)、柴油€75(≤3500cc)/€150(>3500cc)×排量系数(cc/1000)×车龄系数(年限min1-max15)；例2.0L汽油6年车=€50×2.0×6=€600'},
        ],
    },
    # 阿根廷：Mercosur TEC，NCM 8703 敏感部门 35% CIF；另有SIRA进口许可
    'ARG': {
        'site': '阿根廷海关（Mercosur TEC）',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 35.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '阿根廷Mercosur TEC（NCM 8703汽车为敏感部门，关税35% CIF；另有VAT21%、SIRA进口许可）',
             'url': None, 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 智利：8703 MFN 6% CIF（中国-智利FTA下多数车型0%）；VAT19%、奢侈税>$35k 15%
    'CHL': {
        'site': '智利国家海关',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 6.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '智利8703 MFN关税6% CIF（中国-智利FTA下多数车型0%；VAT19%；奢侈税>$35k 15%）',
             'url': None, 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
    # 墨西哥：2025-12-29 法律化非FTA国家整车进口关税 50%（8703.22/23/24/32/33/34/40/60/80），FOB基准
    'MEX': {
        'site': '墨西哥海关（SE/IVA）',
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 50.0, 'duty_base': 'FOB', 'currency': None,
             'effective_date': '2025-12-29', 'tariff_type': 'MFN最惠国',
             'source': '墨西哥2025-12-29将非FTA国家整车进口关税50%写入法律（8703.22/23/24/32/33/34/40/60/80 finished passenger vehicles，White & Case；与2024-12总统令一致；旧MFN 20%口径失效；IVA16%）',
             'url': 'https://www.whitecase.com/insight-alert/mexico-formalizes-50-tariff', 'confidence': 'P1'},
        ],
        'tax_rules': [],
    },
}


def crawl_tariff(country_codes=('GHA', 'ETH'), db=None, logger=None):
    """爬取并落库关税。返回统计 dict。"""
    logger = logger or logging.getLogger('mofcom.tariff')
    db = db or Db()
    stat = {'countries': 0, 'tariff_inserted': 0, 'tariff_updated': 0,
            'tax_inserted': 0, 'tax_dedup': 0, 'urls': []}

    for code in country_codes:
        entry = TARIFF_SOURCE.get(code)
        if not entry:
            logger.warning('无 %s 税率来源', code)
            continue
        country = db.get_country(iso_alpha3=code)
        if not country:
            logger.warning('dim_country 无 %s', code)
            continue
        cid = country['country_id']
        stat['countries'] += 1
        site_url = f'{code.lower()}-customs'

        for t in entry['tariffs']:
            text = f"{t['source']}；{t.get('note', '')}"
            # 分档行显式 goods_scope（注明排量档位）优先；否则按规范判定
            if t.get('goods_scope'):
                goods_scope, evidence = t['goods_scope'], ''
            else:
                goods_scope, evidence = judge_goods_scope(text, t['hs_code'])
            conf = t['confidence']
            # 仅真正判定为 '新车'/'二手车' 时降档；'通用（档位说明）' 仍视为通用不降
            if goods_scope in ('新车', '二手车'):
                conf = _downgrade(conf)
            t0 = time.time()
            tid, is_new = db.upsert_tariff_rate(
                country_id=cid, hs_code=t['hs_code'], goods_scope=goods_scope,
                tariff_type=t['tariff_type'], rate_pct=t['rate_pct'],
                duty_base=t['duty_base'], currency=t['currency'],
                effective_date=t['effective_date'], source=t['source'],
                url=t['url'], confidence=conf)
            dur = int((time.time() - t0) * 1000)
            status = '成功' if is_new else '去重跳过'
            if is_new:
                stat['tariff_inserted'] += 1
                stat['urls'].append(t['url'])
            else:
                stat['tariff_updated'] += 1
            db.log_crawl(cid, entry['site'], 'LIGHT', '结构化税率落库',
                         t['url'], 'tariff', status, duration_ms=dur)
            logger.info('[%s] tariff_rate hs=%s rate=%s%% scope=%s -> %s%s',
                        code, t['hs_code'], t['rate_pct'], goods_scope, status,
                        f' 依据:{evidence}' if evidence else '')

        # 关联 policy_doc（同国种子文档），供 tax_rule.source_doc_id 引用
        doc_id = db.get_seed_doc(cid)
        for tr in entry['tax_rules']:
            t0 = time.time()
            tid, is_new = db.upsert_tax_rule(
                country_id=cid, tax_type=tr['tax_type'], rate=tr['rate'],
                basis=tr['basis'], effective_date=tr['effective_date'],
                source_doc_id=doc_id, confidence=tr['confidence'])
            dur = int((time.time() - t0) * 1000)
            status = '成功' if is_new else '去重跳过'
            if is_new:
                stat['tax_inserted'] += 1
            else:
                stat['tax_dedup'] += 1
            db.log_crawl(cid, entry['site'], 'LIGHT', '附加税费落库',
                         f'{code.lower()}-taxrule-{tr["tax_type"]}-{tr["rate"]}',
                         'tariff', status, duration_ms=dur)
            logger.info('[%s] tax_rule %s %s%% basis=%s -> %s（%s）',
                        code, tr['tax_type'], tr['rate'], tr['basis'], status, tr['note'])
    return stat


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    print(crawl_tariff())
