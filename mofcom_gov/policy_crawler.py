# -*- coding: utf-8 -*-
"""
政策链路（T1）：遍历 mofcom 经商处子站栏目分页，标题+正文关键词过滤，
命中文章落 policy_doc + crawl_task_log。
无命中也记 crawl_task_log（result_doc_id=NULL）表示已搜索无内容。
"""
import re
import logging
import time

from config import SITES, POLICY_KEYWORDS, POLICY_BODY_KEYWORDS
from client import MofcomClient
from db import Db, checksum
from direction import check_direction

# 标题关键词：命中才抓详情
TITLE_RE = re.compile('|'.join(POLICY_KEYWORDS), re.I)
# 正文关键词：详情页正文须命中至少 1 个才落库（防止标题泛命中正文无关）
BODY_RE = re.compile('|'.join(POLICY_BODY_KEYWORDS), re.I)

# 过滤明显无关的高频词（"汽车" 广泛出现在经贸新闻中，仅标题含"汽车"但正文与政策无关的不落）
IRRELEVANT_RE = re.compile(r'车展|试驾|销量排行榜|上市发布|新车上市|汽车产业大会|汽博会', re.I)


def _title_hit(title):
    return bool(TITLE_RE.search(title or ''))


def _body_relevant(text):
    if not text:
        return False
    if IRRELEVANT_RE.search(text):
        return False
    return bool(BODY_RE.search(text))


def crawl_policy_for_country(country, site_code, columns, max_pages_per_col=5,
                             db=None, logger=None, delay_first=False):
    """
    爬一个国家的政策文章
    返回统计 dict: {scanned, hit, inserted, dedup, failed, urls:[]}
    """
    logger = logger or logging.getLogger('mofcom.policy')
    db = db or Db()
    client = MofcomClient(site_code, logger=logger)
    stat = {'scanned': 0, 'hit': 0, 'inserted': 0, 'dedup': 0,
            'direction_mismatch': 0, 'failed': 0, 'urls': []}
    country_id = country['country_id']

    for col, col_id in columns.items():
        if not col_id:
            col_id = client.get_col_id(col)
        if not col_id:
            logger.warning('[%s] 栏目 %s 无 ColId，跳过', site_code, col)
            db.log_crawl(country_id, f'mofcom_{site_code}', 'LIGHT', '栏目遍历',
                         f'http://{site_code}.mofcom.gov.cn/{col}/index.html',
                         'policy_list', '失败', error_msg='ColId 获取失败')
            continue
        logger.info('[%s] 栏目 %s 开始遍历', site_code, col)
        try:
            for item, page_no in client.iter_column(col_id, max_pages=max_pages_per_col):
                stat['scanned'] += 1
                if not _title_hit(item['title']):
                    continue
                stat['hit'] += 1
                t0 = time.time()
                art = client.fetch_article(item['url'])
                duration = int((time.time() - t0) * 1000)
                if not art:
                    stat['failed'] += 1
                    db.log_crawl(country_id, f'mofcom_{site_code}', 'LIGHT', '关键词过滤+详情',
                                 item['url'], 'policy_doc', '失败', duration_ms=duration,
                                 error_msg='详情抓取失败')
                    continue
                if not _body_relevant(art['content_text']):
                    logger.debug('正文不相关，跳过: %s', item['title'])
                    continue
                # 方向校验：中国单边零关税/产品输华/纯宏观新闻 不落库
                direction, reason = check_direction(art['title'], art['content_text'])
                if direction != 'OK':
                    stat['direction_mismatch'] += 1
                    db.log_crawl(country_id, f'mofcom_{site_code}', 'LIGHT', '关键词过滤+方向校验',
                                 art['url'], 'policy_doc', '方向不符', duration_ms=duration,
                                 error_msg=reason)
                    logger.info('[%s] 方向不符: %s（%s）', site_code, item['title'][:40], reason)
                    continue
                doc_id, is_new = db.upsert_policy_doc(
                    country_id=country_id,
                    title=art['title'] or item['title'],
                    url=art['url'],
                    source=f'mofcom_{site_code}子站',
                    content_text=art['content_text'],
                    doc_date=art['doc_date'] or (item['date'] or None),
                )
                status = '成功' if is_new else '去重跳过'
                if is_new:
                    stat['inserted'] += 1
                    stat['urls'].append(art['url'])
                else:
                    stat['dedup'] += 1
                db.log_crawl(country_id, f'mofcom_{site_code}', 'LIGHT', '关键词过滤+详情',
                             art['url'], 'policy_doc', status, duration_ms=duration,
                             result_doc_id=doc_id, content_checksum=checksum(art['content_text']))
                logger.info('[%s] %s: %s', site_code, status, item['title'][:40])
                # 详情页后延迟
                time.sleep(2)
        except Exception as e:
            logger.error('[%s] 栏目 %s 遍历异常: %s', site_code, col, e)
            db.log_crawl(country_id, f'mofcom_{site_code}', 'LIGHT', '栏目遍历',
                         f'http://{site_code}.mofcom.gov.cn/{col}/index.html',
                         'policy_list', '失败', error_msg=str(e)[:500])
    return stat