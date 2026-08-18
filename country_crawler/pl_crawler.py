# -*- coding: utf-8 -*-
"""波兰 PL 汽车月度销量爬虫：pzpm.org.pl（PZPM，新车首次注册品牌级）"""
import re
import io
import sys
import random
import requests
from datetime import date, datetime

from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

PL_BASE_URL = 'https://www.pzpm.org.pl'
PL_LIST_URL = PL_BASE_URL + '/pl/Rynek-motoryzacyjny/Rejestracje-Pojazdow/OSOBOWE-i-DOSTAWCZE'

PL_MONTH_MAP = {
    'styczen': 1, 'luty': 2, 'marzec': 3, 'kwiecien': 4, 'maj': 5,
    'czerwiec': 6, 'lipiec': 7, 'sierpien': 8, 'wrzesien': 9,
    'pazdziernik': 10, 'listopad': 11, 'grudzien': 12,
}

SKIP_BRANDS = ('RAZEM', 'POZOSTALE', 'TOTA', 'OGOLEM')


def _to_int(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    s = str(value).strip().replace(' ', '').replace('\u00a0', '')
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


class PolandCrawler(BaseCrawler):
    def __init__(self, source_name='pzpm', country_code='PL'):
        super().__init__(source_name, country_code)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': random.choice(UA_LIST),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'pl,en;q=0.8',
        })
        self._brand_id_cache = {}

    # ---------- 发现 ----------
    def _get_year_url(self, year):
        """年份页 URL，容忍 2 后缀变体。"""
        for suffix in ('', '2'):
            url = f'{PL_LIST_URL}/Rok-{year}{suffix}'
            try:
                r = self.session.get(url, timeout=30, allow_redirects=True)
                if r.status_code == 200 and f'Rok-{year}' in r.url:
                    return url
            except Exception:
                continue
        return None

    def _build_year_index(self, year):
        """遍历当年全部月份页，以【文件名中的真实月份】为键收集 {（YYYY,MM): url}。

        PZPM 站点月份 URL 与文件内容存在错位（如 Styczeń 页放的是 2 月文件），
        因此必须以文件名 PZPM_SOiSD_MM_YYYY 中的 MM/YYYY 为准。
        """
        yurl = self._get_year_url(year)
        if not yurl:
            return {}
        r = self.session.get(yurl, timeout=30)
        if r.status_code != 200:
            return {}
        pat = re.compile(r'href="([^"]*Rok-%s\d*/[A-Za-z]+-%s[^"]*)"' % (year, year), re.I)
        month_pages = set(murl if murl.startswith('http') else PL_BASE_URL + murl
                          for murl in re.findall(pat, r.text))
        index = {}
        for purl in month_pages:
            try:
                pr = self.session.get(purl, timeout=30)
                if pr.status_code != 200:
                    continue
                names = re.findall(r'PZPM_SOiSD_(\d{2})_(\d{4})[^"\']*\.(?:xlsx|xls)', pr.text, re.I)
                for mm, yy in names:
                    key = (int(yy), int(mm))
                    if key not in index:
                        index[key] = purl
            except Exception:
                continue
        return index

    def discover_download_url(self, year, month):
        """从当年月份页索引中按真实文件名月份取 xlsx 下载 URL。"""
        index = getattr(self, '_year_index', None)
        if index is None or index.get('_year') != year:
            index = self._build_year_index(year)
            index['_year'] = year
            self._year_index = index
        purl = index.get((year, month))
        if not purl:
            return None
        r = self.session.get(purl, timeout=30)
        pat = re.compile(r'href="([^"]*content/download/[^"]*/file/PZPM_SOiSD_%02d_%d[^"/]*\.(?:xlsx|xls))"' % (month, year), re.I)
        links = set(re.findall(pat, r.text))
        if not links:
            return None
        url = sorted(links)[0]
        if url.startswith('http'):
            return url
        return PL_BASE_URL + url

    # ---------- 下载 ----------
    def download_excel(self, url):
        r = self.session.get(url, timeout=60)
        r.raise_for_status()
        return r.content

    # ---------- 解析 ----------
    def parse_brand_excel(self, content, year, month):
        """解析 PZPM_SOiSD_MM_YYYY 的 'Samochody osobowe' sheet 品牌级（支持 .xlsx 与旧 .xls OLE 格式）。

        结构：表头区 Pozycja/Marka/月份，随后品牌行；RAZEM 行（品牌在 col1 合并单元格）为品牌区结束。
        """
        import pandas as pd
        from io import BytesIO

        # 区分 .xls (OLE magic d0cf11e0) 与 .xlsx (zip PK)
        if content[:4] == b'PK\x03\x04':
            sheets = pd.ExcelFile(BytesIO(content)).sheet_names
        else:
            sheets = pd.ExcelFile(BytesIO(content), engine='xlrd').sheet_names

        ws_name = None
        for sn in sheets:
            s = sn.strip()
            if s == 'Samochody osobowe':
                ws_name = sn
                break
            if s.startswith('Samochody osobowe ') and not re.search(r'(REGON|INDYW|dostawcze)', s, re.I):
                ws_name = sn
                break
        if ws_name is None:
            return []
        try:
            df = pd.read_excel(BytesIO(content), sheet_name=ws_name, header=None,
                               engine='openpyxl' if content[:4] == b'PK\x03\x04' else 'xlrd')
        except Exception:
            return []
        # 定位表头行：找到含 'Marka'/'Make' 的行，其列索引即品牌列；销量列=品牌列右侧第1个数值列
        header_idx = None
        brand_col = None
        qty_col = None
        for ri in range(min(12, len(df))):
            row = list(df.iloc[ri])
            for ci, cell in enumerate(row):
                if cell is None:
                    continue
                s = str(cell).strip().upper()
                if s in ('MARKA', 'MAKE', 'MARCA'):
                    header_idx = ri
                    brand_col = ci
                    # 销量列：表头行该列右侧第1个有 'Ogółem'/'Total' 文本的列；找不到则 brand_col+1
                    for cj in range(ci + 1, len(row)):
                        t = str(row[cj]).strip().upper()
                        if t in ('OGÓŁEM', 'OGOLEM', 'TOTAL'):
                            qty_col = cj
                            break
                    if qty_col is None:
                        qty_col = ci + 1
                    break
            if header_idx is not None:
                break
        if header_idx is None or brand_col is None:
            return []
        records = []
        rank_col = brand_col - 1 if brand_col > 0 else None
        seen_brand = False
        for _, row in df.iloc[header_idx + 1:].iterrows():
            vals = list(row)
            if brand_col >= len(vals):
                continue
            v1 = vals[brand_col] if brand_col < len(vals) else None
            c1 = str(v1).strip() if v1 is not None and pd.notna(v1) and str(v1).strip().lower() not in ('nan', 'none') else ''
            if not c1:
                # 品牌列空：RAZEM/Pozostałe/Total 汇总行 → 品牌区结束（已出现过品牌行）
                if seen_brand:
                    break
                continue
            # 品牌列非空：若排名列是数字则视为品牌行；排名列可能为空（个别品牌行）也接受
            if rank_col is not None:
                rv = vals[rank_col] if rank_col < len(vals) else None
                rank_ok = rv is not None and pd.notna(rv) and str(rv).strip().isdigit()
                if not rank_ok and not c1:
                    continue
            b_upper = c1.upper()
            if b_upper in SKIP_BRANDS or b_upper.startswith('POZOSTALE') or b_upper in ('POZYCJA', 'NO.', 'NO', 'MODEL', 'MAKE', 'MARKA'):
                continue
            seen_brand = True
            q = _to_int(vals[qty_col] if qty_col < len(vals) else None)
            if q is None or q == 0:
                continue
            records.append({
                'country_code': 'PL',
                'source_month': date(year, month, 1),
                'brand_name_raw': c1,
                'brand_id': None,
                'model_name': None,
                'vehicle_type': 'passenger',
                'energy_type': None,
                'segment': None,
                'raw_unit': 'units',
                'sales_volume_raw': q,
                'sales_volume_normalized': q,
                'revision_no': 1,
                'is_latest': True,
                'pub_date': None,
                'crawl_time': datetime.now(),
                'data_source': 'pzpm',
                'notes': 'PZPM nowe rejestracje samochodow osobowych (brand)',
            })
        return records

    # ---------- 品牌匹配 ----------
    def get_brand_id(self, brand_name_raw):
        cache_key = brand_name_raw.upper()
        if cache_key in self._brand_id_cache:
            return self._brand_id_cache[cache_key]
        conn, cur = self.get_connection()
        lookup = brand_name_raw.strip().upper()
        cur.execute("SELECT id FROM brand_name_mapping WHERE UPPER(canonical_name)=%s OR UPPER(brand_name_cn)=%s LIMIT 1", (lookup, lookup))
        row = cur.fetchone()
        bid = row['id'] if row else None
        if bid is None:
            cur.execute("SELECT brand_id FROM brand_name_variant WHERE UPPER(variant_name)=%s LIMIT 1", (lookup,))
            row = cur.fetchone()
            bid = row['brand_id'] if row else None
        self._brand_id_cache[cache_key] = bid
        return bid

    def save_sales(self, record):
        record['brand_id'] = self.get_brand_id(record['brand_name_raw'])
        super().save_sales(record)

    # ---------- 增量入口 ----------
    def latest_available_month(self):
        """探测最新可用月：GET 分类页（自动重定向到最新月页），从 URL 解析年月。"""
        try:
            r = self.session.get(PL_LIST_URL, timeout=30, allow_redirects=True)
            m = re.search(r'/Rok-(\d{4})/([A-Za-z]+)-\1', r.url)
            if not m:
                return None
            year = int(m.group(1))
            month_name = m.group(2).lower()
            month = PL_MONTH_MAP.get(month_name)
            if month is None:
                return None
            return (year, month)
        except Exception:
            return None

    def _get_db_max_month(self):
        try:
            conn, cur = self.get_connection()
            cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='PL'")
            row = cur.fetchone()
            return row['m'] if row and row['m'] else None
        except Exception:
            return None

    def crawl_month(self, year, month):
        url = self.discover_download_url(year, month)
        if not url:
            return {'records': 0}
        content = self.download_excel(url)
        records = self.parse_brand_excel(content, year, month)
        for rec in records:
            self.save_sales(rec)
        self.conn.commit()
        return {'records': len(records)}

    def crawl_incremental(self):
        latest = self.latest_available_month()
        if not latest:
            return 0
        max_m = self._get_db_max_month()
        latest_date = date(latest[0], latest[1], 1)
        if max_m is not None and latest_date <= max_m:
            return 0
        result = self.crawl_month(latest[0], latest[1])
        return result.get('records', 0)

    def crawl_range(self, start_year, start_month, end_year, end_month):
        total = 0
        y, m = start_year, start_month
        while (y, m) <= (end_year, end_month):
            result = self.crawl_month(y, m)
            total += result.get('records', 0)
            m += 1
            if m > 12:
                m = 1
                y += 1
        return total


def main():
    c = PolandCrawler()
    n = c.crawl_incremental()
    print('PL incremental saved:', n)


if __name__ == '__main__':
    main()
