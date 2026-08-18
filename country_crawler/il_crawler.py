# -*- coding: utf-8 -*-
"""
I-VIA 以色列汽车销量爬虫
数据源：car-importers.org.il（以色列车辆进口商协会）
说明：月度品牌级数据，YTD累计口径（1月1日至当月），含M1/N1/Taxi与EV/Hybrid/PHEV维度
"""
import os
import sys
import io
import re
import requests
import pdfplumber
from datetime import datetime, date
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_crawler import BaseCrawler

BASE_URL = 'https://www.car-importers.org.il'
PRIVATE_PAGE = BASE_URL + '/Rishuy_en/private'

MONTHS = {
    'January': 1, 'February': 2, 'March': 3, 'April': 4,
    'May': 5, 'June': 6, 'July': 7, 'August': 8,
    'September': 9, 'October': 10, 'November': 11, 'December': 12
}


class ILCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('il_ivia_private', 'IL')
        self.base_url = BASE_URL
        self.page_url = PRIVATE_PAGE

    def get_headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en,zh;q=0.8',
        }

    def discover_pdf_urls(self):
        """解析页面，返回 {('brands'|'ev', month): url} 按月份去重"""
        headers = self.get_headers()
        r = requests.get(self.page_url, headers=headers, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        result = {}
        for a in soup.find_all('a'):
            href = a.get('href', '')
            if not href.lower().endswith('.pdf'):
                continue
            label = a.get_text(strip=True)
            m = re.match(r'^([A-Za-z]+)\s+(\d{4})\s*[-–]\s*(.+)$', label)
            if not m:
                continue
            month_name, year, kind = m.groups()
            if month_name not in MONTHS:
                continue
            month = MONTHS[month_name]
            year = int(year)
            key = 'brands' if 'Brands' in kind else 'ev'
            url = href if href.startswith('http') else BASE_URL + href
            result[(key, year, month)] = url
        return result

    def _clean_int(self, s):
        if s is None:
            return 0
        digits = re.sub(r'[^\d]', '', str(s))
        return int(digits) if digits else 0

    def _parse_brands_pdf(self, content):
        """品牌PDF：每品牌一条 Total 记录，notes 记录 M1/N1/Taxi 拆分
        兼容三种表头格式：
        A(1月): [空, Make, M1_2026, N1_2026, Taxi_2026, Total_2026, M1_2025, ...]（前导空列偏移）
        B(6月): [Make, M1_2026, N1_2026, Taxi_2026, Total_2026, M1_2025, ...]（无偏移）
        C(7月): 双行表头[空,2026(Jan1-Jul31),...,2025(...)] + [Make,M1,N1,Taxi,Total,M1,N1,Taxi,Total]
        通过识别含Make的列名行，结合'2026'/'2025'后缀或出现次序确定列索引。
        """
        records = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    col_idx = None  # {'make':i, 'cur':{name:i}, 'prev':{name:i}}
                    for row in table:
                        if not row:
                            continue
                        cells = [str(c).strip() if c else '' for c in row]
                        # 检测列名行：含 Make 且含 Total
                        if 'Make' in cells and any(c.lower().startswith('total') for c in cells):
                            col_idx = {'make': None, 'cur': {}, 'prev': {}}
                            for i, c in enumerate(cells):
                                lc = c.lower().replace(' ', '').replace('_', '')
                                if lc == 'make':
                                    col_idx['make'] = i
                                    continue
                                is_prev = '2025' in c or lc.endswith('2025')
                                is_cur = '2026' in c or lc.endswith('2026')
                                for name in ('m1', 'n1', 'taxi', 'total'):
                                    if lc.startswith(name):
                                        if is_prev:
                                            col_idx['prev'][name] = i
                                        elif is_cur:
                                            col_idx['cur'][name] = i
                                        else:
                                            # 无年份后缀：第一次出现=今年，第二次=去年
                                            if name in col_idx['cur']:
                                                col_idx['prev'][name] = i
                                            else:
                                                col_idx['cur'][name] = i
                                        break
                            continue
                        if col_idx is None or col_idx['make'] is None:
                            continue
                        make = cells[col_idx['make']]
                        if make in ('Make', '') or not make:
                            continue
                        if make.upper() in ('TOTAL', 'TOTALS', 'OTHER', 'OTHERS', 'ALL'):
                            continue
                        cur = col_idx['cur']
                        total = self._clean_int(cells[cur.get('total', col_idx['make'])])
                        prev_total = self._clean_int(cells[col_idx['prev']['total']]) if 'total' in col_idx['prev'] else 0
                        # M1/N1/Taxi：优先从合并单元格拆分，否则用分离列
                        m1_raw = cells[cur.get('m1', '')] if 'm1' in cur else ''
                        parts = re.findall(r'[\d,]+', m1_raw)
                        if len(parts) >= 2:
                            m1 = self._clean_int(parts[0])
                            n1 = self._clean_int(parts[1])
                            taxi = self._clean_int(parts[2]) if len(parts) > 2 else 0
                        else:
                            m1 = self._clean_int(m1_raw)
                            n1 = self._clean_int(cells[cur['n1']]) if 'n1' in cur else 0
                            taxi = self._clean_int(cells[cur['taxi']]) if 'taxi' in cur else 0
                        records.append({
                            'make': make,
                            'total': total,
                            'm1': m1,
                            'n1': n1,
                            'taxi': taxi,
                            'prev_total': prev_total,
                        })
        return records

    def _parse_ev_pdf(self, content):
        """EV PDF：每品牌按 energy_type 拆 3 条（EV/HEV/PHEV）"""
        records = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    for row in table:
                        if not row or not row[0]:
                            continue
                        make = str(row[0]).strip()
                        if make == 'Make' or len(row) < 4:
                            continue
                        if make.upper() in ('TOTAL', 'TOTALS', 'OTHER', 'OTHERS', 'ALL'):
                            continue
                        ev = self._clean_int(row[1])
                        hev = self._clean_int(row[2])
                        phev = self._clean_int(row[3])
                        clean_make = make.replace('_', ' ').strip()
                        records.append({'make': clean_make, 'ev': ev, 'hev': hev, 'phev': phev})
        return records

    def _make_record(self, country, sm, brand, qty, energy_type, notes, ds):
        return {
            'country_code': country,
            'source_month': sm,
            'brand_name_raw': brand,
            'brand_id': None,
            'model_name': None,
            'vehicle_type': 'passenger',
            'energy_type': energy_type,
            'segment': None,
            'raw_unit': 'units',
            'sales_volume_raw': qty,
            'sales_volume_normalized': qty,
            'revision_no': 1,
            'is_latest': True,
            'pub_date': None,
            'crawl_time': datetime.now(),
            'data_source': ds,
            'notes': notes,
        }

    def crawl_month(self, year, month, brand_url, ev_url):
        """爬单个月份，返回 {'records': n, 'brands': n, 'ev': n}"""
        headers = self.get_headers()
        n = 0
        n_brands = 0
        n_ev = 0
        sm = date(year, month, 1)
        ytd_note = f'I-VIA YTD累计(Jan 1-{month_name(month)} {year})'

        # 品牌PDF
        if brand_url:
            try:
                r = requests.get(brand_url, headers=headers, timeout=30)
                r.raise_for_status()
                for rec in self._parse_brands_pdf(r.content):
                    note = ytd_note + f'; M1={rec["m1"]}, N1={rec["n1"]}, Taxi={rec["taxi"]}; 上年同期Total={rec["prev_total"]}'
                    self.save_sales(self._make_record(
                        'IL', sm, rec['make'], rec['total'], None, note, 'il_ivia_private'))
                    n += 1
                    n_brands += 1
            except Exception as e:
                self.logger.error(f'品牌PDF解析失败 {brand_url}: {e}')

        # EV PDF
        if ev_url:
            try:
                r = requests.get(ev_url, headers=headers, timeout=30)
                r.raise_for_status()
                for rec in self._parse_ev_pdf(r.content):
                    for en, qty in (('BEV', rec['ev']), ('HEV', rec['hev']), ('PHEV', rec['phev'])):
                        note = ytd_note + f'; {en}'
                        self.save_sales(self._make_record(
                            'IL', sm, rec['make'], qty, en, note, 'il_ivia_private'))
                        n += 1
                        n_ev += 1
            except Exception as e:
                self.logger.error(f'EV PDF解析失败 {ev_url}: {e}')

        return {'records': n, 'brands': n_brands, 'ev': n_ev}

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='IL'")
        row = cur.fetchone()
        m = row['m'] if isinstance(row, dict) else row[0]
        return m.date() if hasattr(m, 'date') else m

    def crawl_incremental(self):
        max_m = self._get_db_max_month()
        urls = self.discover_pdf_urls()
        self.logger.info(f'发现 {len(urls)} 个PDF链接')
        saved = 0
        # 按 (year, month) 聚合品牌+EV链接
        grouped = {}
        for (key, year, month), url in urls.items():
            grouped.setdefault((year, month), {})[key] = url
        for (year, month), links in sorted(grouped.items()):
            sm = date(year, month, 1)
            if max_m is not None and sm <= max_m:
                continue
            self.logger.info(f'爬取 IL {year}-{month}')
            res = self.crawl_month(year, month, links.get('brands'), links.get('ev'))
            saved += res['records']
            self.logger.info(f'  保存 {res}')
            self.random_delay()
        return {'records': saved}


def month_name(m):
    names = {1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun',
             7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'}
    return names.get(m, str(m))


if __name__ == '__main__':
    c = ILCrawler()
    try:
        res = c.crawl_incremental()
        print(f'完成，保存 {res["records"]} 条记录')
    finally:
        c.close()