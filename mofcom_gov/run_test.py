# -*- coding: utf-8 -*-
"""
阶段A-0 测试编排：
T1 政策链路：埃塞 et 站栏目遍历 -> policy_doc
T2 关税链路：加纳（超龄罚款->tax_rule）+ 埃塞（默认'通用'）-> tariff_rate
T3 去重：原样重跑 T1/T2，验证无重复 + crawl_task_log 出现'去重跳过'
末尾输出回传统计（写报告文件 + 控制台）
"""
import logging
import json
import sys
import io
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from config import SITES
from db import Db
from policy_crawler import crawl_policy_for_country
from tariff_crawler import crawl_tariff


def stat_report(db, report):
    lines = []
    w = lines.append
    w('# 阶段A-0 测试回传报告')
    w('')
    w('## 一、policy_doc 新增（非种子）')
    w('- 非种子 policy_doc 总数: %s' % db.count_by('policy_doc', "CASE WHEN url LIKE 'seed-%%' THEN '种子' ELSE '爬取' END"))
    w('')
    w('## 二、tariff_rate')
    w('- 总数: %s' % db.count('tariff_rate'))
    w('- goods_scope 分布: %s' % db.count_by('tariff_rate', 'goods_scope'))
    db.cur.execute('SELECT country_id, hs_code, goods_scope, rate_pct, duty_base, currency, effective_date, source, url, confidence FROM tariff_rate ORDER BY tariff_id')
    for r in db.cur.fetchall():
        w('  - country_id=%s hs=%s scope=%s rate=%s%% base=%s cur=%s eff=%s source=%s url=%s conf=%s' % r)
    w('')
    w('## 三、tax_rule（附加税费）')
    w('- 总数: %s' % db.count('tax_rule'))
    db.cur.execute('SELECT country_id, tax_type, rate, basis, effective_date, confidence FROM tax_rule WHERE tax_type=%s ORDER BY tax_id', ('超龄罚款',))
    for r in db.cur.fetchall():
        w('  - country_id=%s type=%s rate=%s%% basis=%s eff=%s conf=%s' % r)
    w('')
    w('## 四、crawl_task_log')
    w('- 总数: %s' % db.count('crawl_task_log'))
    w('- 按 status: %s' % db.count_by('crawl_task_log', 'status'))
    w('')
    w('## 五、URL 样例')
    db.cur.execute("SELECT title, url, source, country_id FROM policy_doc WHERE url NOT LIKE 'seed-%%' ORDER BY doc_id DESC LIMIT 1")
    row = db.cur.fetchone()
    w('- policy_doc 样例: %s | %s | %s | country_id=%s' % row if row else '- 无')
    db.cur.execute('SELECT hs_code, url, country_id FROM tariff_rate ORDER BY tariff_id LIMIT 1')
    row = db.cur.fetchone()
    w('- tariff_rate 样例: hs=%s url=%s country_id=%s' % row if row else '- 无')
    w('')
    w('## 六、问题清单')
    for q in report['issues']:
        w('- %s' % q)
    return '\n'.join(lines)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    logger = logging.getLogger('stageA0')
    db = Db()
    issues = []
    report = {'issues': issues}
    phase1 = report.setdefault('T1_policy', {})
    phase2 = report.setdefault('T2_tariff', {})
    phase3 = report.setdefault('T3_dedup', {})

    # T1: 埃塞政策链路
    et = db.get_country(iso_alpha3='ETH')
    logger.info('== T1 埃塞政策链路 ==')
    st = crawl_policy_for_country(et, 'et', SITES['et']['columns'],
                                  max_pages_per_col=10, db=db, logger=logger)
    phase1.update(st)
    logger.info('T1 stat: %s', st)
    if not st['inserted']:
        issues.append('T1 埃塞未命中政策文章（期望至少1篇，已知 jmxw page=3 有内燃机禁令）')

    # T2: 关税链路（加纳超龄罚款 + 埃塞通用）
    logger.info('== T2 关税链路 ==')
    st2 = crawl_tariff(('GHA', 'ETH'), db=db, logger=logger)
    phase2.update(st2)
    logger.info('T2 stat: %s', st2)
    if not st2['tax_inserted']:
        issues.append('T2 加纳超龄罚款未入库（期望 tax_rule 3条）')

    # T3: 原样重跑
    logger.info('== T3 重跑去重 ==')
    st3 = crawl_policy_for_country(et, 'et', SITES['et']['columns'],
                                   max_pages_per_col=10, db=db, logger=logger)
    phase3.update(st3)
    st3b = crawl_tariff(('GHA', 'ETH'), db=db, logger=logger)
    phase3.update({'tariff_' + k: v for k, v in st3b.items()})
    logger.info('T3 policy stat: %s; tariff stat: %s', st3, st3b)

    # 去重验证：重跑后 inserted 应为 0（全部去重跳过或已存在）
    if st3['inserted'] != 0:
        issues.append('T3 政策重跑仍有新增（去重失败）')

    report_txt = stat_report(db, report)
    with open('stageA0_report.md', 'w', encoding='utf-8') as f:
        f.write(report_txt)
    print(report_txt)

    db.close()


if __name__ == '__main__':
    main()
