# -*- coding: utf-8 -*-
"""
UA Ukraine crawler - autocentre.ua TOP-10 brands monthly
data_source = 'autocentre_ua'
口径: 首注册新车 (первинна реєстрація), 转载自 Укравтопром/AUTO-Consulting
"""
import re
import sys
import time
import random
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_crawler import BaseCrawler, UA_LIST, DB_CONFIG


UA_BASE = 'https://www.autocentre.ua'
UA_SOBBY = 'https://www.autocentre.ua/news/sobytie/page/'
UA_SITEMAP_NEWS = 'https://www.autocentre.ua/sitemap-news.xml'

# 品牌名西里尔->拉丁 或直接拉丁保留 (autocentre 用拉丁品牌名)
# 正则提取 TOP-10: "N. Brand – QTY од. (±X%)"

class UkraineCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('autocentre_ua', 'UA')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': random.choice(UA_LIST),
            'Accept-Language': 'uk,ru;q=0.9,en;q=0.8',
        })
        self._brand_id_cache = {}

    # ---------- 发现 ----------
    # 月报 URL 特征: {月份形容词}-rynok-novykh-avto-...-lidery 或 ...-auktsaidery
    # 月份形容词: sichnevyi(1) liutyi(2) bereznevyi(3) kvitnevyi(4) travnevyi(5)
    #            chervnevyi(6) lypnevyi(7) serpnevyi(8) veresnevyi(9) zhovtnevyi(10)
    #            lystopadovyi(11) hrudnevyi(12)
    UA_MONTH_SLUG = {
        'sichnevyi': 1, 'lyutyi': 2, 'bereznevyi': 3, 'kvitnevyi': 4, 'travnevyi': 5,
        'chervnevyi': 6, 'lypnevyi': 7, 'serpnevyi': 8, 'veresnevyi': 9, 'zhovtnevyi': 10,
        'lystopadovyi': 11, 'hrudnevyi': 12,
    }

    def discover_article_urls(self, max_pages=None):
        """从 sitemap-news-1.xml 找月度市场报告文章(含TOP-10品牌列表)。
        返回 list[url]。"""
        urls = []
        for su in ['https://www.autocentre.ua/sitemap-news-1.xml',
                   'https://www.autocentre.ua/sitemap-news-2.xml']:
            try:
                r = self.retry_request(self.session.get, su, timeout=120)
                if not r:
                    continue
                for u in re.findall(r'<loc>([^<]+)</loc>', r.text):
                    # 月报: 月份形容词 + rynok-novykh-avto
                    for mslug in self.UA_MONTH_SLUG:
                        if f'-{mslug}-rynok-novykh-avto' in u or f'{mslug}-rynok-novykh-avto' in u:
                            if u not in urls:
                                urls.append(u)
                            break
            except Exception as e:
                print(f'discover sitemap error: {e}')
        return urls

    def _fetch(self, url):
        if not url.startswith('http'):
            url = UA_BASE + url
        r = self.retry_request(self.session.get, url, timeout=30)
        return r.text if r else None

    # ---------- 解析 ----------
    def parse_article(self, html_text):
        """解析月报文章，返回 (records, (year, month)或None)
        records: TOP-10 品牌级 + 总量
        """
        soup = BeautifulSoup(html_text, 'html.parser')
        # 把 span/strong 还原为纯文本 (防止 – 被拆行)
        for sp in soup.find_all(['span', 'strong', 'em']):
            if sp.parent is None:
                continue
            sp.replace_with(sp.get_text())
        text = soup.get_text(' ')
        text = re.sub(r'\s+', ' ', text)

        # 1. 找品牌列表区: "До ТОП-10 брендів ... увійшли:"
        brands = []
        msec = re.search(r'(ТОП-10 брендів|TOP-10 брендів|ТОП-10 марок)[^:]*:', text)
        if msec:
            start = msec.end()
            seg = text[start:start + 4000]
            # 品牌行: 1. Toyota – 986 од. (+20%) | 4. Renault – 345 од.
            pat = re.compile(r'(\d+)\.\s*([A-Za-z][\w\s\.\-]{0,30}?)\s*[–—-]\s*(\d[\d\s]*)\s*од\.')
            for m in pat.finditer(seg):
                brand = re.sub(r'\s+', ' ', m.group(2)).strip()
                qty = int(m.group(3).replace(' ', '').replace('\u00a0', ''))
                brands.append((brand, qty))
                if len(brands) >= 10:
                    break

        # 2. 总量: "придбали N нових легковика" / "реалізували N" / "продали N"
        total = None
        mtotal = re.search(r'(придбали|реалізували|продали|зареєстрували)\s+(\d[\d\s\xa0]*?)\s+нових', text)
        if mtotal:
            total = int(mtotal.group(2).replace(' ', '').replace('\u00a0', ''))

        # 3. 月份: 标题第一词是月份名 (Липневий=7月) - 数据月
        month = None
        year = None
        h1 = soup.find('h1')
        if h1:
            t = h1.get_text(strip=True).lower()
            mnames = {
                'січневий': 1, 'січні': 1, 'січень': 1,
                'лютневий': 2, 'лютому': 2, 'лютий': 2,
                'березневий': 3, 'березні': 3, 'березень': 3,
                'квітневий': 4, 'квітні': 4, 'квітень': 4,
                'травневий': 5, 'травні': 5, 'травень': 5,
                'червневий': 6, 'червні': 6, 'червень': 6,
                'липневий': 7, 'липні': 7, 'липень': 7,
                'серпневий': 8, 'серпні': 8, 'серпень': 8,
                'вересневий': 9, 'вересні': 9, 'вересень': 9,
                'жовтневий': 10, 'жовтні': 10, 'жовтень': 10,
                'листопадовий': 11, 'листопаді': 11, 'листопад': 11,
                'грудневий': 12, 'грудні': 12, 'грудень': 12,
            }
            for key, val in mnames.items():
                if key in t:
                    month = val
                    break
        # 日期行 fallback: "N місяця 2026" (发布日, 用于取年份)
        pub_month = None
        mdate = re.search(r'(\d{1,2})\s+(січн|лют|берез|квітн|трав|черв|липн|серпн|верес|жовтн|листоп|грудн)\w*\s+(\d{4})', text)
        if mdate:
            months = {'січн': 1, 'лют': 2, 'берез': 3, 'квітн': 4, 'трав': 5, 'черв': 6,
                      'липн': 7, 'серпн': 8, 'верес': 9, 'жовтн': 10, 'листоп': 11, 'грудн': 12}
            pub_month = months.get(mdate.group(2)[:5])
            year = int(mdate.group(3))
        # 若标题无月份词, 用发布月 (数据月=发布月, 通常发布在次月)
        if month is None:
            month = pub_month
        # 跨年修正: 发布月为1月而数据月为12月 -> 数据年 = 发布年-1
        if month == 12 and pub_month == 1 and year:
            year -= 1
        # 年份 fallback: "X року 20YY"
        if year is None:
            myr = re.search(r'(\d{4})\s+р(?:оку|оцi|оці)', text) or re.search(r'у\s+(\d{4})\s+році', text)
            if myr:
                year = int(myr.group(1))

        if month is None or year is None:
            return [], None

        records = []
        for brand, qty in brands:
            records.append({
                'country_code': 'UA', 'source_month': date(year, month, 1),
                'brand_name_raw': brand, 'model_name': None,
                'vehicle_type': 'passenger', 'energy_type': None,
                'segment': None, 'raw_unit': 'units',
                'sales_volume_raw': qty, 'sales_volume_normalized': qty,
                'revision_no': 1, 'is_latest': True,
                'pub_date': None, 'crawl_time': datetime.now(),
                'data_source': 'autocentre_ua',
                'notes': 'autocentre.ua TOP-10 (Укравтопром первинна реєстрація)',
            })
        return records, (year, month)

    # ---------- 品牌/存储 ----------
    def get_brand_id(self, brand_raw):
        if brand_raw in self._brand_id_cache:
            return self._brand_id_cache[brand_raw]
        conn, cur = self.get_connection()
        b = brand_raw.upper().strip()
        bid = None
        try:
            cur.execute("""
                SELECT id FROM brand_name_mapping
                WHERE UPPER(canonical_name)=%s OR UPPER(brand_name_cn)=%s
                ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, id LIMIT 1
            """, (b, b))
            row = cur.fetchone()
            if row:
                bid = row['id'] if 'id' in row else row[0]
            else:
                cur.execute("SELECT brand_id FROM brand_name_variant WHERE UPPER(variant_name)=%s LIMIT 1", (b,))
                row = cur.fetchone()
                if row:
                    bid = row['brand_id'] if 'brand_id' in row else row[0]
        except Exception:
            pass
        self._brand_id_cache[brand_raw] = bid
        return bid

    def save_sales(self, record):
        record['brand_id'] = self.get_brand_id(record['brand_name_raw'])
        super().save_sales(record)

    # ---------- 调度入口 ----------
    def crawl_month(self, year, month):
        """发现并解析指定年月，返回 {'records': n}"""
        urls = self.discover_article_urls()
        for url in urls:
            try:
                html_text = self._fetch(url)
                if not html_text:
                    continue
                records, ym = self.parse_article(html_text)
                if ym == (year, month):
                    for rec in records:
                        self.save_sales(rec)
                    return {'records': len(records)}
            except Exception as e:
                print(f'crawl_month {year}-{month} error: {e}')
        return {'records': 0}

    def crawl_incremental(self):
        max_m = self._get_db_max_month()
        urls = self.discover_article_urls()
        saved = 0
        for url in urls:
            try:
                html_text = self._fetch(url)
                if not html_text:
                    continue
                records, ym = self.parse_article(html_text)
                if not ym:
                    continue
                if max_m is None or date(*ym, 1) > max_m:
                    for rec in records:
                        self.save_sales(rec)
                    saved += len(records)
            except Exception as e:
                print(f'incremental error {url}: {e}')
        return saved

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        try:
            cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='UA'")
            row = cur.fetchone()
            m = row['m'] if 'm' in row else row[0]
            return m.date() if m and hasattr(m, 'date') else m
        except Exception:
            return None


if __name__ == '__main__':
    c = UkraineCrawler()
    mode = 'incremental'
    if '--incremental' in sys.argv:
        mode = 'incremental'
    if mode == 'incremental':
        n = c.crawl_incremental()
        print(f'UA incremental saved: {n}')
    else:
        import json
        urls = c.discover_article_urls()
        for url in urls[:5]:
            html_text = c._fetch(url)
            if not html_text:
                continue
            recs, ym = c.parse_article(html_text)
            print(url, '->', ym, len(recs))
