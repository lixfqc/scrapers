# -*- coding: utf-8 -*-
"""
34 国优先批次批量执行：
- 政策：mofcom 子站动态发现栏目 -> crawl_policy_for_country（含方向校验）
- 关税：TARIFF_SOURCE 已核实国家落库；未核实国家跳过并记录
- 每批生成 batch_report.md 回传（行数/方向不符/URL样例/问题清单）
用法：
  python run_batch.py --codes DZA,AGO,EGY,KEN,NGA,TZA --policy-pages 10
"""
import argparse
import logging
import time

from db import Db
from client import MofcomClient
from policy_crawler import crawl_policy_for_country
from tariff_crawler import crawl_tariff

# 34 国优先批次清单（iso_alpha3，业务关注人工标记）
CODES34 = [
    'BHR', 'MMR', 'KHM', 'IDN', 'JOR', 'LAO', 'MNG', 'PHL', 'QAT', 'SAU',
    'THA', 'TUR', 'ARE', 'VNM', 'KAZ', 'KGZ', 'TJK', 'UZB', 'GEO', 'AZE',
    'DZA', 'AGO', 'EGY', 'ETH', 'GHA', 'KEN', 'NGA', 'TZA',
    'BLR', 'RUS', 'UKR', 'ARG', 'CHL', 'MEX',
]

# 政策种子已建国家：不必重复爬政策原文，可直接进阶段B（关税仍可做）
SEED_POLICY_CODES = {'GHA', 'KAZ', 'RUS', 'UZB', 'GEO'}

# 政策已完成国家（阶段A-0 已爬）：重跑仅去重
DONE_POLICY_CODES = {'ETH'}

# 关税已落库国家（阶段A-0 + 批次累计，重跑幂等）
DONE_TARIFF_CODES = {'GHA', 'ETH', 'DZA', 'AGO', 'EGY', 'KEN', 'NGA', 'TZA',
                     'BHR', 'KHM', 'IDN', 'JOR', 'LAO', 'MNG',
                     'QAT', 'SAU', 'THA', 'TUR', 'ARE', 'VNM',
                     'KAZ', 'KGZ', 'UZB', 'GEO',
                     'BLR', 'RUS', 'UKR', 'ARG', 'CHL', 'MEX'}

# 图片类栏目无政策文章，跳过
SKIP_COLS = {'tpjj', 'tpzj', 'tppd'}

# mofcom 子站域名与 ISO 码不一致的国家映射（code -> 子站标识）
SITE_CODE_MAP = {'KHM': 'cb'}

# 国家代码别名（34国清单用旧名，映射到 ISO 3166 alpha3）
COUNTRY_CODE_MAP = {'KSA': 'SAU'}

# 重点栏目优先（政策法规/重要通知/经贸新闻 在前）
PRIORITY_COLS = ['zcfg', 'zytz', 'jmxw', 'zajm', 'zahz', 'jstx', 'tzzn', 'yjts',
                 'ggxx', 'xxfb', 'ztdy', 'sqfb', 'scdy', 'zajm', 'qyhz']


def _ordered_columns(cols):
    """重点栏目优先排序，仅保留站点实际存在的栏目，过滤图片栏目"""
    ordered = []
    seen = set()
    cols = [c for c in cols if c not in SKIP_COLS]
    for c in PRIORITY_COLS:
        if c in cols and c not in seen:
            seen.add(c)
            ordered.append(c)
    for c in sorted(cols):
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def crawl_policy_batch(codes, db, logger, max_pages_per_col=10):
    """多国政策爬取，返回 {code: stat}"""
    stat = {}
    for code in codes:
        country = db.get_country(iso_alpha3=COUNTRY_CODE_MAP.get(code, code))
        if not country:
            stat[code] = {'error': 'dim_country 无该国'}
            continue
        cid = country['country_id']
        if code in SEED_POLICY_CODES:
            stat[code] = {'skipped': '种子政策已有，跳过原文爬取'}
            logger.info('[%s] 种子国跳过政策原文', code)
            continue
        a2 = SITE_CODE_MAP.get(code, country['iso_alpha2'].lower())
        client = MofcomClient(a2, logger=logger)
        cols = client.discover_columns()
        if not cols:
            db.log_crawl(cid, f'mofcom_{a2}', 'LIGHT', '站点探测',
                         f'http://{a2}.mofcom.gov.cn/', 'policy_list', '失败',
                         error_msg='首页不可达或无栏目')
            stat[code] = {'site_fail': '首页不可达或无栏目'}
            logger.error('[%s] 站点探测失败', code)
            continue
        columns = {c: None for c in _ordered_columns(cols)}
        st = crawl_policy_for_country(country, a2, columns,
                                      max_pages_per_col=max_pages_per_col,
                                      db=db, logger=logger)
        st['site'] = f'http://{a2}.mofcom.gov.cn/'
        st['columns'] = len(columns)
        stat[code] = st
    return stat


def write_report(batch_name, codes, policy_stat, tariff_stat, db, issues):
    lines = []
    w = lines.append
    w(f'# {batch_name} 回传报告')
    w('')
    w('## 一、政策（policy_doc）')
    w('| 国家 | 扫描 | 命中 | 新增 | 去重 | 方向不符 | 失败 | 站点 | 栏目数 |')
    w('|------|------|------|------|------|----------|------|------|--------|')
    for code in codes:
        st = policy_stat.get(code) or {}
        if 'error' in st or 'site_fail' in st or 'skipped' in st:
            w(f'| {code} | {st} |')
            continue
        w(f'| {code} | {st.get("scanned", 0)} | {st.get("hit", 0)} | '
          f'{st.get("inserted", 0)} | {st.get("dedup", 0)} | '
          f'{st.get("direction_mismatch", 0)} | {st.get("failed", 0)} | '
          f'{st.get("site", "")} | {st.get("columns", 0)} |')
    w('')
    w('## 二、关税（tariff_rate）')
    w('- 新增: %s, 更新(去重): %s, 附加税费新增: %s, 附加税费去重: %s' % (
        tariff_stat.get('tariff_inserted', 0), tariff_stat.get('tariff_updated', 0),
        tariff_stat.get('tax_inserted', 0), tariff_stat.get('tax_dedup', 0)))
    db.cur.execute("""SELECT t.country_id, c.country_name, t.hs_code, t.goods_scope,
                             t.rate_pct, t.effective_date, t.confidence
                      FROM tariff_rate t JOIN dim_country c ON c.country_id=t.country_id
                      WHERE t.country_id IN (SELECT country_id FROM tariff_rate)
                      ORDER BY t.country_id, t.hs_code""")
    for r in db.cur.fetchall():
        w('  - cid=%s %s hs=%s scope=%s rate=%s%% eff=%s conf=%s' % r)
    w('')
    w('## 三、crawl_task_log 按 status')
    for r in db.count_by('crawl_task_log', 'status'):
        w(f'- {r[0]} = {r[1]}')
    w('')
    w('## 四、URL 样例（本批新增 policy_doc）')
    db.cur.execute("""SELECT p.title, p.url, p.country_id FROM policy_doc p
                      WHERE p.url NOT LIKE 'seed-%%'
                      ORDER BY p.doc_id DESC LIMIT 5""")
    for r in db.cur.fetchall():
        w(f'- {r[2]} | {r[0][:40]} | {r[1]}')
    w('')
    w('## 五、问题清单')
    for q in issues:
        w(f'- {q}')
    txt = '\n'.join(lines)
    with open(f'{batch_name}.md', 'w', encoding='utf-8') as f:
        f.write(txt)
    return txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--codes', required=True, help='逗号分隔 iso_alpha3')
    ap.add_argument('--batch', default='batch_report', help='批次名（报告文件名）')
    ap.add_argument('--policy-pages', type=int, default=10, help='每栏目最多页数')
    ap.add_argument('--tariff', action='store_true', help='同时跑关税（TARIFF_SOURCE 内国家）')
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    logger = logging.getLogger('batch')
    db = Db()
    issues = []
    codes = [c.strip().upper() for c in args.codes.split(',') if c.strip()]

    t0 = time.time()
    policy_stat = crawl_policy_batch(codes, db, logger, args.policy_pages)
    issues.append('政策批耗时 %.1f 分钟' % ((time.time() - t0) / 60))

    tariff_stat = {}
    if args.tariff:
        tt_codes = [c for c in codes if c in DONE_TARIFF_CODES]  # 已核实来源国家
        if tt_codes:
            tariff_stat = crawl_tariff(tuple(tt_codes), db=db, logger=logger)

    txt = write_report(args.batch, codes, policy_stat, tariff_stat, db, issues)
    print(txt)
    db.close()


if __name__ == '__main__':
    main()
