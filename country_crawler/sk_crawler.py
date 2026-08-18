# -*- coding: utf-8 -*-
"""斯洛伐克 SK 月度新车登记爬虫 (ZAP SR / zapsr.sk)
品牌级Top12(份额换算) + 行业能源级
"""
import sys, io, re, time, random, unicodedata
from datetime import date, datetime
import requests
import pdfplumber

from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

SK_BASE_URL = 'https://zapsr.sk'
SK_STATS_URL = f'{SK_BASE_URL}/statistiky/'

SK_FUEL_MAP = {
    'BEV': 'BEV', 'DIESEL': 'DIESEL', 'DIESEL+HEV': 'HEV',
    'DIESEL+PHEV': 'PHEV', 'PETROL': 'GASOLINE', 'PETROL+HEV': 'HEV',
    'PETROL+LPG': 'LPG', 'PETROL+LPG+HEV': 'HEV', 'PETROL+PHEV': 'PHEV',
    'CNG': 'CNG', 'PETROL+LPG+PHEV': 'PHEV', 'LPG': 'LPG',
    'HYDROGEN': 'FCEV', 'ELECTRIC': 'BEV',
}
SK_BRAND_SKIP = {'TOTAL', 'CELKOM', 'SPOLU', 'OTHER', 'OSTATNÉ', 'OSTATNE'}

def _to_int(value):
    if value is None:
        return 0
    s = str(value).replace('\xa0', ' ').replace(' ', '').strip()
    s = re.sub(r'[^\d-]', '', s)
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        return 0

def _norm_brand(b):
    s = unicodedata.normalize('NFKD', str(b).strip().upper())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s

class SkCrawler(BaseCrawler):
    def __init__(self, source_name='sk_zapsr_monthly_registrations', country_code='SK'):
        super().__init__(source_name, country_code)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': random.choice(UA_LIST), 'Referer': SK_BASE_URL})
        self._brand_id_cache = {}
        self._file_index = None

    # ---------- 文件索引 ----------
    def _build_file_index(self):
        r = self.retry_request(self.session.get, SK_STATS_URL, timeout=60)
        r.raise_for_status()
        idx = {}
        for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>', r.text):
            url = m.group(1)
            if not url.startswith('http'):
                url = SK_BASE_URL + url
            mm = re.search(r'registracie-aut[-_]?(\d{1,2})[-_]*(\d{4})', url, re.I)
            if mm:
                y, mo = int(mm.group(2)), int(mm.group(1))
                idx[(y, mo)] = url
                continue
            mm2 = re.search(r'statistika(\d{1,2})_(\d{2})[^/]*\.pdf', url, re.I)
            if mm2:
                y, mo = int('20' + mm2.group(2)), int(mm2.group(1))
                idx[(y, mo)] = url
        self._file_index = idx
        return idx

    def latest_available_month(self):
        if self._file_index is None:
            self._build_file_index()
        if not self._file_index:
            return None
        return max(self._file_index.keys())

    def discover_download_url(self, year, month):
        if self._file_index is None:
            self._build_file_index()
        return self._file_index.get((year, month))

    # ---------- 下载与解析 ----------
    def download_pdf(self, url):
        r = self.retry_request(self.session.get, url, timeout=90)
        r.raise_for_status()
        return r.content

    def parse_pdf(self, content, year, month):
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = [p.extract_text() or '' for p in pdf.pages]
        full = '\n'.join(pages)

        # 1. 月度总量
        total = 0
        mm = re.search(r'celkovým\s+počtom\s+([\d\s]+)\s+vozidiel', full, re.I)
        if mm:
            total = _to_int(mm.group(1))
        if total <= 0:
            mm = re.search(r'celkový\s+počet\s+([\d\s]+)', full, re.I)
            if mm:
                total = _to_int(mm.group(1))
        if total <= 0:
            return [], total

        # 2. 品牌Top12 (M1区)
        brands = []
        # 2021版 M1/N1 品牌行交错无法可靠区分，品牌级跳过（仅能源级+总量）
        if year >= 2022:
            m1_section = full
            if 'Kategória M1' in full:
                m1_section = full.split('Kategória M1', 1)[1]
                if 'Kategória nákladných' in m1_section:
                    m1_section = m1_section.split('Kategória nákladných', 1)[0]
            elif 'Registrácie jednotlivých' in full:
                m1_section = full.split('Registrácie jednotlivých', 1)[1]
            # 每行取第一个品牌对（M1在并排行左侧；2021版品牌/份额跨行也兼容）
            brand_rows = []
            for line in m1_section.split('\n'):
                mm = re.search(r'(?:(\d+)\.\s*)?(.+?)\s+(\d{1,2}[.,]\d{2})\s*%', line)
                if mm:
                    brand_rows.append(mm)
                if len(brand_rows) >= 12:
                    break
            for mm in brand_rows:
                bname = mm.group(2).strip()
                if bname.upper() in SK_BRAND_SKIP:
                    continue
                # 过滤2023-01等品牌名/排名/份额跨行的脏行（含%或箭头或数字开头）
                if re.search(r'[%↓↑]', bname) or re.match(r'^\d', bname):
                    continue
                try:
                    share = float(mm.group(3).replace(',', '.'))
                except ValueError:
                    continue
                qty = round(total * share / 100.0)
                brands.append((bname, qty))
            # 去重保序
            seen = set()
            unique = []
            for b, q in brands:
                if b not in seen:
                    seen.add(b)
                    unique.append((b, q))
            brands = unique

        # 3. 能源表(行业级)
        fuels = []
        if 'Typ paliva' in full:
            fs = full.split('Typ paliva', 1)[1]
            if 'Kategória nákladných' in fs:
                fs = fs.split('Kategória nákladných', 1)[0]
            for mm in re.finditer(r'^([A-Z][A-Z+]*)+\s+([\d\s]+)\s+[\d.,]+\s*%', fs, re.M):
                fname = mm.group(1).strip().upper()
                qty = _to_int(mm.group(2))
                if fname and qty > 0:
                    fuels.append((fname, qty))
        return brands, total, fuels

    def get_brand_id(self, brand_raw):
        b = _norm_brand(brand_raw)
        if b in self._brand_id_cache:
            return self._brand_id_cache[b]
        conn, cur = self.get_connection()
        try:
            cur.execute("SELECT id FROM brand_name_mapping WHERE UPPER(canonical_name)=%s OR UPPER(brand_name_cn)=%s ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, id LIMIT 1", (b, b))
            row = cur.fetchone()
            bid = row['id'] if row else None
            if bid is None:
                cur.execute("SELECT brand_id FROM brand_name_variant WHERE UPPER(variant_name)=%s LIMIT 1", (b,))
                row = cur.fetchone()
                bid = row['brand_id'] if row else None
            self._brand_id_cache[b] = bid
            return bid
        finally:
            pass

    def save_sales(self, record):
        record['brand_id'] = self.get_brand_id(record['brand_name_raw'])
        super().save_sales(record)

    def crawl_month(self, year, month):
        url = self.discover_download_url(year, month)
        if not url:
            return {'records': 0, 'total': 0}
        content = self.download_pdf(url)
        brands, total, fuels = self.parse_pdf(content, year, month)
        n = 0
        for bname, qty in brands:
            rec = {
                'country_code': self.country_code, 'source_month': date(year, month, 1),
                'brand_name_raw': bname, 'brand_id': None, 'model_name': None,
                'vehicle_type': 'passenger', 'energy_type': None, 'segment': None,
                'raw_unit': 'units', 'sales_volume_raw': qty,
                'sales_volume_normalized': qty, 'revision_no': 1, 'is_latest': True,
                'pub_date': None, 'crawl_time': datetime.now(), 'data_source': self.source_name,
                'notes': f'ZAP SR registrácie nových vozidiel M1 (top12, share-based) {year}-{month:02d}',
            }
            self.save_sales(rec)
            n += 1
        for fname, qty in fuels:
            et = SK_FUEL_MAP.get(fname)
            if et is None:
                et = 'OTHER'
            rec = {
                'country_code': self.country_code, 'source_month': date(year, month, 1),
                'brand_name_raw': 'SK INDUSTRY', 'brand_id': None, 'model_name': None,
                'vehicle_type': 'passenger', 'energy_type': et, 'segment': None,
                'raw_unit': 'units', 'sales_volume_raw': qty,
                'sales_volume_normalized': qty, 'revision_no': 1, 'is_latest': True,
                'pub_date': None, 'crawl_time': datetime.now(), 'data_source': self.source_name,
                'notes': f'ZAP SR registrácie podľa typu paliva {year}-{month:02d}',
            }
            self.save_sales(rec)
            n += 1
        return {'records': n, 'total': total}

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code=%s", (self.country_code,))
        row = cur.fetchone()
        m = row['m'] if row else None
        return m.date() if m and isinstance(m, datetime) else m

    def crawl_incremental(self):
        conn, cur = self.get_connection()
        max_m = self._get_db_max_month()
        latest = self.latest_available_month()
        if not latest:
            return 0
        ly, lm = latest
        if max_m and date(ly, lm, 1) <= max_m:
            return 0
        res = self.crawl_month(ly, lm)
        return res['records']

    def crawl_range(self, start_year, start_month, end_year, end_month):
        self._build_file_index()
        results = {}
        y, m = start_year, start_month
        while (y, m) <= (end_year, end_month):
            results[f'{y}-{m:02d}'] = self.crawl_month(y, m)
            self.random_delay()
            m += 1
            if m > 12:
                m = 1
                y += 1
        return results


if __name__ == '__main__':
    c = SkCrawler()
    if len(sys.argv) > 1 and sys.argv[1] == 'full':
        res = c.crawl_range(2021, 1, 2026, 7)
        for k, v in res.items():
            print(k, v)
    else:
        c.crawl_incremental()
