# -*- coding: utf-8 -*-
"""南非 ZA 爬虫: NAAMSA (naamsa.net) 月度 Flash PDF 品牌级新车销售
口径: 新车销售(New Vehicle Sales, 非注册)。PDF第2-3页 Total Vehicles Sales by Manufacturer。
"""
import re
import io
import time
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

ZA_BASE = 'https://naamsa.net'
ZA_PRESS = 'https://naamsa.net/press-releases/'

ZA_MONTHS = {'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
             'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12}

SKIP_BRANDS = ('TOTAL', 'TOTALS', 'INDUSTRY', 'GRAND TOTAL')


class ZaCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('naamsa_monthly_new_vehicle_sales', 'ZA')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        self._brand_cache = {}

    def _fetch(self, url, timeout=90):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r
            except Exception as e:
                print(f'_fetch {url} err: {e}')
            time.sleep(2)
        return None

    def discover_month_pdfs(self):
        """从 press-releases 页提取 Flash PDF 链接, 解析月份。
        返回 {(year, month): url}。URL模式多样, 多正则兜底。
        """
        found = {}
        r = self._fetch(ZA_PRESS)
        if not r:
            return found
        # 提取所有 pdf 链接 + 其锚文本(标题)
        links = re.findall(r'href="([^"]+\.pdf[^"]*)"[^>]*>(.*?)</a>', r.text, re.I)
        for href, anchor in links:
            hl = href.lower()
            if 'flash' not in hl:
                continue
            full = href if href.startswith('http') else ZA_BASE + href
            fname = href.split('/')[-1]
            ym = self._parse_flash_month(fname)
            if ym:
                found[ym] = full
        return found

    def _parse_flash_month(self, fname):
        """从 Flash 文件名解析 (year, month)。"""
        # FLASH_STD_202607 / FLASH_STD_202508-updated
        m = re.search(r'FLASH_STD_(\d{4})(\d{2})', fname, re.I)
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
            if 2000 <= y <= 2030 and 1 <= mo <= 12:
                return (y, mo)
        # Flash-Report-June-2026
        m = re.search(r'Flash[-_]Report[-_](?:Standard[-_])?([A-Za-z]+)[-_](\d{4})', fname, re.I)
        if m:
            mn = m.group(1).lower()
            if mn in ZA_MONTHS:
                y = int(m.group(2))
                if 2000 <= y <= 2030:
                    return (y, ZA_MONTHS[mn])
        # 日期前缀 20260701-Flash-Report-Standard.pdf
        m = re.match(r'(\d{4})(\d{2})\d{2}-', fname)
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
            if 2000 <= y <= 2030 and 1 <= mo <= 12:
                return (y, mo)
        return None

    def download_pdf(self, url):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=120)
                if r.status_code == 200 and len(r.content) > 10000:
                    return r.content
            except Exception:
                pass
            time.sleep(random_delay())
        return None

    def parse_flash_pdf(self, pdf_bytes, year, month):
        """解析品牌表。用 pdfplumber.extract_tables 结构化提取。
        优先完整表 'Total Vehicles Sales by Manufacturer' (Page 3, 38品牌):
          列 = [品牌, PassL, PassE, LCVL, LCVE, TotalL, TotalE]  (7值, Com段并入Total)
          当月总销量 = TotalL = 倒数第2个非None数字列。
        fallback Top15 精简表 (Page 1): 品牌|Local|Exp (3值)。
        返回 [(brand, total_local), ...]。
        """
        import pdfplumber
        # 先尝试 extract_tables 完整表
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    if not table or not table[0]:
                        continue
                    # 数据表表头: 第1行含 'Passenger' 与 'Total' 列标签
                    hdr_txt = ' '.join(str(c) for c in table[0] if c)
                    if 'PASSENGER' not in hdr_txt.upper() or 'TOTAL' not in hdr_txt.upper():
                        continue
                    if len(table) < 5:
                        continue
                    records = []
                    for row in table[1:]:
                        if not row or not row[0]:
                            continue
                        brand = str(row[0]).strip().rstrip('*').strip()
                        if not brand:
                            continue
                        bu = brand.upper()
                        if bu.startswith('NOTES'):
                            break
                        if bu.startswith('* SALES') or bu.startswith('** REPORTED') or bu in ('LOCAL', 'EXP'):
                            continue
                        # 列: [品牌, PassL, PassE, LCVL, LCVE, TotalL, TotalE]
                        # TotalL = row[-2](固定倒数第2个), 保留 '-' 位置(不能跳'-')
                        def _num(c):
                            if c is None:
                                return None
                            s = str(c).strip().replace(' ', '')
                            if s in ('', '-', 'None'):
                                return None
                            return int(s) if s.isdigit() else None
                        total_cell = _num(row[-2]) if len(row) >= 3 else None
                        if total_cell is None:
                            # 退化: 尝试倒数第3个(个别行结构差异)
                            total_cell = _num(row[-3]) if len(row) >= 4 else None
                        if total_cell is None:
                            continue
                        records.append((brand, total_cell))
                    if records:
                        return records
        # fallback: extract_text 完整表(旧PDF)
        return self._parse_flash_text(pdf_bytes)

    def get_brand_id(self, brand_raw):
        b = str(brand_raw).strip().upper()
        if b in self._brand_cache:
            return self._brand_cache[b]
        bid = None
        conn, cur = self.get_connection()
        cur.execute("SELECT id FROM brand_name_mapping WHERE UPPER(canonical_name)=%s ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, id LIMIT 1", (b,))
        row = cur.fetchone()
        if row:
            bid = row['id'] if isinstance(row, dict) else row[0]
        if bid is None:
            cur.execute("SELECT brand_id FROM brand_name_variant WHERE UPPER(variant_name)=%s ORDER BY id LIMIT 1", (b,))
            row = cur.fetchone()
            if row:
                bid = row['brand_id'] if isinstance(row, dict) else row[0]
        self._brand_cache[b] = bid
        return bid

    def save_sales(self, record):
        if record.get('brand_id') is None:
            record['brand_id'] = self.get_brand_id(record['brand_name_raw'])
        super().save_sales(record)

    def crawl_month(self, year, month):
        pdfs = self.discover_month_pdfs()
        url = pdfs.get((year, month))
        if not url:
            return {'records': 0, 'total': None}
        content = self.download_pdf(url)
        if not content:
            return {'records': 0, 'total': None}
        brands = self.parse_flash_pdf(content, year, month)
        n = 0
        for brand, qty in brands:
            rec = {
                'country_code': 'ZA',
                'source_month': date(year, month, 1),
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
                'data_source': 'naamsa_monthly_new_vehicle_sales',
                'notes': 'NAAMSA monthly new vehicle sales by manufacturer (incl passenger+LCV+commercial)',
            }
            self.save_sales(rec)
            n += 1
        return {'records': n}

    def _parse_flash_text(self, pdf_bytes):
        """extract_text 回退解析。优先完整表(复数 Vehicles), 品牌行=品牌+数字序列,
        Total Local = 序列中非'-'值的倒数第2个(Total Local)。fallback Top15(单数 Vehicle),
        Local = 前2个数字token千分位合并。
        """
        import pdfplumber
        lines_all = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ''
                lines_all.extend(l.strip() for l in t.split('\n') if l.strip())

        start = None
        is_top15 = False
        for i, ln in enumerate(lines_all):
            if 'TOTAL VEHICLES SALES BY MANUFACTURER' in ln.upper():
                start = i
                break
        if start is None:
            for i, ln in enumerate(lines_all):
                if 'TOTAL VEHICLE SALES BY MANUFACTURER (TOP 15)' in ln.upper():
                    start = i
                    is_top15 = True
                    break
        if start is None:
            return []
        records = []
        for ln in lines_all[start + 1:]:
            u = ln.strip()
            if not u:
                continue
            if u.upper().startswith('NOTES') or u.startswith('Notes') or u.startswith('Note:'):
                break
            if re.match(r'^[*\s]*SALES ARE ESTIMATES', u, re.I) or 'REPORTED AGGREGATE' in u.upper():
                continue
            if re.match(r'^(LOCAL|EXP|PASSENGER|LCV|COMMERCIAL|TOTAL|INDUSTRY|MANUFACTURER)', u.upper()):
                continue
            m = re.match(r'^([A-Z][A-Z0-9\.&\-\s\*]{1,45}?)\s+([\d\s\-]+)', u)
            if not m:
                continue
            brand = m.group(1).strip().rstrip('*').strip()
            if not brand or brand.upper().startswith('TOTAL'):
                continue
            num_part = m.group(2)
            toks = re.findall(r'\d+', num_part)
            if not toks:
                continue
            # 千分位合并: 1-2位 + 3位 => 同一数值; 但 74 564 (2位+3位) 也是独立数字
            # 用总Token数>4 时按完整表(7值结构)处理, 避免误合
            vals = []
            i = 0
            while i < len(toks):
                if len(toks) > 4 and i + 1 < len(toks) and len(toks[i]) <= 2 and len(toks[i + 1]) == 3 \
                        and i + 1 < len(toks) - 1:
                    vals.append(int(toks[i] + toks[i + 1]))
                    i += 2
                else:
                    vals.append(int(toks[i]))
                    i += 1
            if is_top15:
                qty = vals[0] if vals else 0
            else:
                if num_part.strip().endswith('-'):
                    qty = vals[-1] if vals else 0
                else:
                    qty = vals[-2] if len(vals) >= 2 else (vals[-1] if vals else 0)
            records.append((brand, qty))
        return records

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='ZA'")
        row = cur.fetchone()
        m = row['m'] if isinstance(row, dict) else row[0]
        return m.date() if hasattr(m, 'date') else m

    def crawl_incremental(self):
        max_m = self._get_db_max_month()
        pdfs = self.discover_month_pdfs()
        saved = 0
        for (y, m) in sorted(pdfs.keys()):
            sm = date(y, m, 1)
            if max_m is None or sm > max_m:
                res = self.crawl_month(y, m)
                saved += res['records']
        return saved

    def crawl_range(self, y1, m1, y2, m2):
        pdfs = self.discover_month_pdfs()
        results = {}
        for (y, m) in sorted(pdfs.keys()):
            if (y, m) < (y1, m1) or (y, m) > (y2, m2):
                continue
            res = self.crawl_month(y, m)
            results[f'{y}-{m:02d}'] = res
            print(f'{y}-{m:02d}: {res}')
            time.sleep(1)
        return results


def random_delay():
    import random
    return random.uniform(1.5, 3.5)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--incremental', action='store_true')
    ap.add_argument('--ym', type=str, default='', help='单月 2026-07')
    ap.add_argument('--y1', type=int, default=2020)
    ap.add_argument('--m1', type=int, default=1)
    ap.add_argument('--y2', type=int, default=2026)
    ap.add_argument('--m2', type=int, default=12)
    args = ap.parse_args()

    c = ZaCrawler()
    if args.ym:
        y, m = map(int, args.ym.split('-'))
        print(c.crawl_month(y, m))
    elif args.incremental:
        n = c.crawl_incremental()
        print(f'ZA incremental saved: {n}')
    else:
        pdfs = c.discover_month_pdfs()
        print('flash pdfs found:', len(pdfs))
        res = c.crawl_range(args.y1, args.m1, args.y2, args.m2)
        print('ZA range done')


if __name__ == '__main__':
    main()
