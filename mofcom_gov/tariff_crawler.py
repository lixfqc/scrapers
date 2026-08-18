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
        'tariffs': [
            {'hs_code': '8703', 'rate_pct': 10.0, 'duty_base': 'CIF', 'currency': None,
             'effective_date': '2026-01-01', 'tariff_type': 'MFN最惠国',
             'source': '加纳海关GRA车辆进口税表（ECOWAS CET，8703按排量分档：汽油≤1000cc/柴油≤1500cc 5%，汽油1000-3000cc/柴油1500-2500cc 10%，>3000cc/>2500cc 20%）',
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
            goods_scope, evidence = judge_goods_scope(text, t['hs_code'])
            conf = t['confidence']
            if goods_scope != '通用':
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
