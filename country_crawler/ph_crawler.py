# -*- coding: utf-8 -*-
"""
菲律宾 PH 汽车销量爬虫
数据源：CAMPI-TMA（菲律宾汽车制造商商会）月度品牌销量，经 carguide.ph 发布
说明：月度品牌级数据，PC+CV 总销量口径（CAMPI会员），按新闻文章解析
"""
import os
import sys
import re
import html
import requests
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_crawler import BaseCrawler

BLOG = 'https://www.carguide.ph'

# 已知月度文章URL（2026-01 ~ 2026-06，更早月份可增量发现）
KNOWN_URLS = {
    (2026, 1): 'https://www.carguide.ph/2026/02/new-car-sales-dipped-10-percent-last.html',
    (2026, 2): 'https://www.carguide.ph/2026/03/february-2026-new-car-sales-drop-85.html',
    (2026, 3): 'https://www.carguide.ph/2026/04/thanks-to-energy-crisis-new-car-sales.html',
    (2026, 4): 'https://www.carguide.ph/2026/05/honda-hyundai-sales-tanked-last-april.html',
    (2026, 5): 'https://www.carguide.ph/2026/06/as-fuel-prices-stabilize-new-car-sales.html',
    (2026, 6): 'https://www.carguide.ph/2026/07/new-car-sales-surge-in-june-2026.html',
}

# li项品牌正则：品牌 – N units (share)
BRAND_RE = re.compile(r'^(.*?)\s*[–\-]\s*([\d,]+)\s*units?\s*(?:\(([^)]*)\))?$', re.IGNORECASE)


def clean_text(s):
    s = html.unescape(s)
    s = s.replace('\xa0', ' ')
    s = s.replace('\u2013', '-').replace('\u2014', '-').replace('\u2019', "'")
    return s.strip()


class PHCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('ph_campi_news', 'PH')
        self.blog = BLOG

    def get_headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en,zh;q=0.8',
        }

    # ---------- 文章获取 ----------
    def _fetch(self, url):
        r = requests.get(url, headers=self.get_headers(), timeout=30)
        r.raise_for_status()
        return r.text

    def _extract_lis(self, url):
        """提取页面所有 li 项文本"""
        r = requests.get(url, headers=self.get_headers(), timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        lis = []
        for li in soup.find_all('li'):
            t = clean_text(li.get_text(' ', strip=True))
            if t:
                lis.append(t)
        return lis

    def _parse_brand_item(self, text):
        m = BRAND_RE.match(text)
        if not m:
            return None
        brand = clean_text(m.group(1))
        try:
            qty = int(m.group(2).replace(',', ''))
        except ValueError:
            return None
        share = m.group(3).strip() if m.group(3) else ''
        return {'brand': brand, 'qty': qty, 'share': share}

    def _parse_main_list(self, lis):
        """从全部li项中定位主品牌排名列表
        规则：第一个 Toyota 且 share 以数字开头的 li 为 start；
        向后收集连续品牌项，遇重复品牌（第二次Toyota）或无法解析项即停。
        """
        items = []
        start = None
        for i, t in enumerate(lis):
            p = self._parse_brand_item(t)
            if not p:
                continue
            if start is None and p['brand'] == 'Toyota' and p['share'] and p['share'][0].isdigit():
                start = i
            items.append({'idx': i, 'parsed': p})
        if start is None:
            return []
        main = []
        seen = set()
        for it in items:
            if it['idx'] < start:
                continue
            p = it['parsed']
            if p['brand'] in seen:
                break
            seen.add(p['brand'])
            main.append(p)
        # 校验：主列表必须含 Toyota（最大份额）
        if not any(p['brand'] == 'Toyota' for p in main):
            return []
        return main

    # ---------- 文章发现 ----------
    def _find_article_url(self, year, month):
        """数据月M发布于M+1月20-27日。用 Blogger feed 窗口搜索标题含 sales 的文章"""
        pub_year, pub_month = (year, month + 1) if month < 12 else (year + 1, 1)
        first = date(pub_year, pub_month, 1)
        last = date(pub_year + (1 if pub_month == 12 else 0),
                    (1 if pub_month == 12 else pub_month + 1), 1) - timedelta(days=1)
        url = (f'{self.blog}/feeds/posts/default?alt=json&max-results=150'
               f'&published-min={first.isoformat()}T00:00:00'
               f'&published-max={last.isoformat()}T23:59:59')
        try:
            r = requests.get(url, headers=self.get_headers(), timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            self.logger.warning(f'feed搜索失败 {year}-{month}: {e}')
            return None
        for entry in data.get('feed', {}).get('entry', []):
            title = entry.get('title', {}).get('$t', '')
            if not re.search(r'sales|sold|cam', title, re.IGNORECASE):
                continue
            for link in entry.get('link', []):
                if link.get('rel') == 'alternate':
                    cand = link.get('href')
                    break
            else:
                continue
            try:
                lis = self._extract_lis(cand)
                if len(self._parse_main_list(lis)) >= 25:
                    self.logger.info(f'发现 {year}-{month} 文章: {cand}')
                    return cand
            except Exception:
                continue
        return None

    # ---------- 入库 ----------
    def _make_record(self, sm, brand, qty, notes):
        return {
            'country_code': 'PH',
            'source_month': sm,
            'brand_name_raw': brand,
            'brand_id': None,
            'model_name': None,
            'vehicle_type': 'passenger',
            'energy_type': None,
            'segment': None,
            'raw_unit': 'units',
            'sales_volume_raw': qty,
            'sales_volume_normalized': qty,
            'revision_no': 1,
            'is_latest': True,
            'pub_date': None,
            'crawl_time': datetime.now(),
            'data_source': 'ph_campi_news',
            'notes': notes,
        }

    def crawl_month(self, year, month, url):
        lis = self._extract_lis(url)
        main = self._parse_main_list(lis)
        if not main:
            self.logger.warning(f'{year}-{month} 未解析出主列表')
            return {'records': 0, 'brands': 0}
        total = sum(p['qty'] for p in main)
        sm = date(year, month, 1)
        n = 0
        for p in main:
            notes = f'CAMPI-TMA月度品牌销量; share={p["share"]}' if p['share'] else 'CAMPI-TMA月度品牌销量'
            self.save_sales(self._make_record(sm, p['brand'], p['qty'], notes))
            n += 1
        self.logger.info(f'{year}-{month}: {len(main)}品牌, 合计{total}')
        return {'records': n, 'brands': len(main), 'total': total}

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='PH'")
        row = cur.fetchone()
        m = row['m'] if isinstance(row, dict) else row[0]
        return m.date() if hasattr(m, 'date') else m

    def crawl_incremental(self):
        max_m = self._get_db_max_month()
        today = date.today()
        urls = dict(KNOWN_URLS)
        saved = 0
        for (year, month), u in sorted(urls.items()):
            sm = date(year, month, 1)
            if max_m is not None and sm <= max_m:
                continue
            self.logger.info(f'爬取 PH {year}-{month}')
            try:
                res = self.crawl_month(year, month, u)
                saved += res['records']
            except Exception as e:
                self.logger.error(f'失败 {year}-{month}: {e}')
            self.random_delay()
        # 增量发现后续月份（数据月+1月20日后发布）
        for (year, month) in sorted(urls.keys()):
            pass
        # 从已知最后月份之后继续尝试发现
        last_ym = max(urls.keys())
        probe = (last_ym[0], last_ym[1] + 1) if last_ym[1] < 12 else (last_ym[0] + 1, 1)
        sm = date(probe[0], probe[1], 1)
        while sm <= today.replace(day=1):
            if max_m is not None and sm <= max_m:
                pass
            else:
                u = self._find_article_url(probe[0], probe[1])
                if u:
                    try:
                        res = self.crawl_month(probe[0], probe[1], u)
                        saved += res['records']
                    except Exception as e:
                        self.logger.error(f'失败 {probe[0]}-{probe[1]}: {e}')
                    self.random_delay()
                else:
                    self.logger.info(f'{probe[0]}-{probe[1]} 未发现文章，停止')
                    break
            probe = (probe[0], probe[1] + 1) if probe[1] < 12 else (probe[0] + 1, 1)
            sm = date(probe[0], probe[1], 1)
        return {'records': saved}


if __name__ == '__main__':
    c = PHCrawler()
    try:
        res = c.crawl_incremental()
        print(f'完成，保存 {res["records"]} 条记录')
    finally:
        c.close()
