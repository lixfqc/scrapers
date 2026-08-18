# -*- coding: utf-8 -*-
"""
mofcom 子站请求客户端
- 列表页动态渲染，通过 /api-gateway/jpaas-publish-server/front/page/build/unit 接口取
- 详情页静态 HTML，utf-8
- 反爬策略：LIGHT 档（UA 轮换 + 3-8s 延迟 + 指数退避重试 + 403 标记反爬拦截）
"""
import re
import time
import json
import random
import logging

import requests
from bs4 import BeautifulSoup

from config import SITES, TPL_SET_ID, API_LIST, LIGHT


class MofcomClient:
    """mofcom 子站客户端，一次实例对应一个站点（国家）"""

    def __init__(self, site_code, logger=None):
        self.site = site_code
        self.web_id = SITES[site_code]['webId']
        self.logger = logger or logging.getLogger(f'mofcom.{site_code}')
        self.session = requests.Session()
        self.failure_count = 0
        self.page_count = 0

    # ---------- 基础请求 ----------
    def _get(self, url, timeout=15, params=None):
        """GET 请求：UA 轮换 + 指数退避重试，返回 Response 或 None（连续失败熔断）"""
        for attempt in range(LIGHT['max_retries']):
            try:
                resp = self.session.get(url, headers=self._headers(), params=params, timeout=timeout)
                if resp.status_code == 403:
                    self.logger.warning('HTTP 403 反爬拦截: %s', url)
                    return resp  # 交由调用方记 status='反爬拦截'
                if resp.status_code == 200:
                    self.failure_count = 0
                    self.page_count += 1
                    return resp
                self.logger.warning('HTTP %s: %s', resp.status_code, url)
                if resp.status_code in (404, 500):
                    return resp
            except Exception as e:
                self.logger.warning('请求异常（%s/%s）: %s', attempt + 1, LIGHT['max_retries'], e)
            wait = (2 ** attempt) + random.uniform(0, 1)
            time.sleep(wait)
        self.failure_count += 1
        if self.failure_count >= LIGHT['failure_threshold']:
            self.logger.error('连续失败 %d 次，触发熔断', self.failure_count)
        return None

    def _headers(self):
        return {
            'User-Agent': random.choice([
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
                'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
            ]),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': f'http://{self.site}.mofcom.gov.cn/',
        }

    def _random_delay(self):
        delay = random.uniform(LIGHT['delay_min'], LIGHT['delay_max'])
        time.sleep(delay)
        return int(delay * 1000)

    # ---------- 栏目标识 ----------
    def get_col_id(self, column):
        """从栏目页 index.html 的 meta name="ColId" 提取栏目 ID"""
        url = f'http://{self.site}.mofcom.gov.cn/{column}/index.html'
        resp = self._get(url)
        if not resp or resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.content, 'html.parser')
        meta = soup.find('meta', attrs={'name': re.compile('ColId', re.I)})
        if meta and meta.get('content'):
            return meta['content'].strip()
        # 兜底：script 里找 ColId
        m = re.search(r'ColId["\']?\s*[:=]\s*["\']([A-Za-z0-9]+)["\']', resp.text)
        return m.group(1) if m else None

    # ---------- 列表 ----------
    def fetch_list_page(self, col_id, page_no, page_size=15):
        """
        取栏目某页文章列表
        返回 (items, total) 或 (None, None) 失败
        items: [{'url': '/jmxw/art/2026/art_xxx.html', 'title': '...', 'date': '2026-07-14'}]
        """
        params = {
            'parseType': 'bulidstatic',
            'webId': self.web_id,
            'tplSetId': TPL_SET_ID,
            'pageType': 'column',
            'tagId': '信息列表',
            'editType': 'null',
            'pageId': col_id,
            'paramJson': json.dumps({'pageNo': page_no, 'pageSize': page_size}, ensure_ascii=False),
        }
        resp = self._get(API_LIST.format(site=self.site), params=params)
        if not resp or resp.status_code != 200:
            return None, None
        try:
            data = resp.json()
        except Exception:
            self.logger.warning('列表接口非 JSON: page=%s col=%s', page_no, col_id)
            return None, None
        html = (data.get('data') or {}).get('html') or ''
        # 总数：从分页 div 的 count 属性取
        total = None
        m = re.search(r'count=["\']?(\d+)', html)
        if m:
            total = int(m.group(1))
        items = []
        for li in BeautifulSoup(html, 'html.parser').find_all('li'):
            a = li.find('a')
            if not a or not a.get('href'):
                continue
            date_raw = li.get_text(strip=True).replace(a.get_text(strip=True), '').strip()
            items.append({
                'url': a['href'].strip(),
                'title': a.get_text(strip=True),
                'date': date_raw[:10] if len(date_raw) >= 10 else date_raw,
            })
        return items, total

    def iter_column(self, col_id, max_pages=None):
        """
        遍历栏目全部分页，逐条 yield (item, page_no)
        内置每页间随机延迟；max_pages 限制页数（None=全部）
        """
        page_no = 1
        while True:
            if max_pages and page_no > max_pages:
                return
            items, total = self.fetch_list_page(col_id, page_no)
            if not items:
                self.logger.info('栏目结束: page=%d 无数据', page_no)
                return
            for item in items:
                yield item, page_no
            # 判断是否还有下一页
            if total and page_no * 15 >= total:
                return
            if not total and len(items) < 15:
                return
            page_no += 1
            self._random_delay()

    # ---------- 详情 ----------
    def fetch_article(self, url):
        """
        抓文章详情页（url 可为相对路径或完整 URL）
        返回 dict 或 None:
        {title, url, source, doc_date, content_text}
        """
        if url.startswith('http'):
            full_url = url
        else:
            full_url = f'http://{self.site}.mofcom.gov.cn{url}'
        resp = self._get(full_url)
        if not resp or resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.content, 'html.parser')
        # 标题：优先 <h1>/<title>
        title = ''
        h1 = soup.find('h1')
        if h1:
            title = h1.get_text(strip=True)
        if not title:
            t = soup.find('title')
            title = t.get_text(strip=True) if t else ''
        # 正文：去 script/style，取 body 全部文本
        for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
            tag.decompose()
        body = soup.find('body') or soup
        content_text = body.get_text('\n', strip=True)
        # 来源/日期：从正文文本提取（避免匹配页面其它区域的日期）
        source = ''
        m = re.search(r'来源[：:]\s*([^\s，。；;]+)', content_text)
        if m:
            source = m.group(1).strip()
        doc_date = None
        m = re.search(r'(20\d{2})[-/年]\s*(\d{1,2})[-/月]\s*(\d{1,2})', content_text)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2000 <= y <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31:
                doc_date = f'{y:04d}-{mo:02d}-{d:02d}'
        return {
            'title': title,
            'url': full_url,
            'source': source,
            'doc_date': doc_date,
            'content_text': content_text,
        }