# -*- coding: utf-8 -*-
"""智利 CL 爬虫: ANAC (anac.cl) 月度《Informe del Mercado Automotor》PDF
品牌表: VENTAS A PÚBLICO POR MARCA EN {月} {年} - MERCADO DE LIVIANOS Y MEDIANOS
口径: 新车登记 (Ventas a público, 来源 Registro Civil)。
注意: WP REST API 401, 只能 HTML 解析入口页; 大文件限速 ~5KB/s 需断点续传;
      品牌表跨两页 (Parte 1/2 de 2), 每个品牌行最后三元组 = TOTAL 销量。
"""
import re
import io
import os
import time
import random
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

CL_BASE = 'https://www.anac.cl'
CL_ENTRY = 'https://www.anac.cl/category/estudio-de-mercado/'

# 西班牙语月份
CL_MONTHS = {'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
             'julio': 7, 'agosto': 8, 'septiembre': 9, 'setiembre': 9, 'octubre': 10,
             'noviembre': 11, 'diciembre': 12}

# 品牌跳过
CL_SKIP = ('OTROS', 'TOTAL', 'MARCA')


class ClCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('cl_anac_brand_monthly', 'CL')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': random.choice(UA_LIST),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'es,en;q=0.9',
        })
        self._brand_cache = {}
        self._dl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads', 'anac')
        os.makedirs(self._dl_dir, exist_ok=True)

    def _fetch(self, url, timeout=60):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r
            except Exception as e:
                print(f'_fetch {url} err: {e}')
            time.sleep(2)
        return None

    def _download_range(self, url, dest, timeout=180):
        """断点续传下载 (ANAC 限速 ~5KB/s), 内部自动重试续传直到完整。"""
        # 已知完整大小
        total_size = None
        try:
            hr = self.session.head(url, headers={'User-Agent': random.choice(UA_LIST)}, timeout=30)
            if hr.status_code == 200 and hr.headers.get('Content-Length'):
                total_size = int(hr.headers['Content-Length'])
        except Exception:
            pass
        for attempt in range(6):
            if os.path.exists(dest) and total_size is not None:
                if os.path.getsize(dest) >= total_size:
                    return dest
                downloaded = os.path.getsize(dest)
            else:
                downloaded = 0
            headers = {'User-Agent': random.choice(UA_LIST)}
            if downloaded:
                headers['Range'] = f'bytes={downloaded}-'
            try:
                r = self.session.get(url, headers=headers, timeout=timeout, stream=True)
                if r.status_code not in (200, 206):
                    print(f'download {url} status {r.status_code}')
                    return None
                mode = 'ab' if downloaded else 'wb'
                with open(dest, mode) as f:
                    for chunk in r.iter_content(65536):
                        if chunk:
                            f.write(chunk)
                if total_size is None:
                    if os.path.getsize(dest) > 100000:
                        return dest
                else:
                    if os.path.getsize(dest) >= total_size:
                        return dest
                    print(f'CL download incomplete {os.path.getsize(dest)}/{total_size}, retry')
            except Exception as e:
                print(f'download {url} err: {e}, retry {attempt + 1}')
            time.sleep(random.uniform(2, 4))
        return None

    def discover_pdf_urls(self):
        """从入口页(estudio-de-mercado)解析最新报告 PDF 直链。
        返回 {(year, month): url}。文件名含手工后缀变体, 必须从页面抓。
        """
        found = {}
        r = self._fetch(CL_ENTRY)
        if not r:
            return found
        # PDF 直链: .../uploads/{年}/{月}/{NN}-ANAC-Mercado-Automotor-{月}-{年}[后缀].pdf
        for href in re.findall(r'href="([^"]+\.pdf[^"]*)"', r.text):
            href = href.strip()
            hl = href.lower()
            if 'mercado-automotor' not in hl:
                continue
            fn = requests.utils.unquote(href.split('/')[-1])
            # 解析: {NN}-ANAC-Mercado-Automotor-{Mes}-{Año}[后缀].pdf
            m = re.search(r'mercado-automotor[-\s]*([a-z]+)[-\s]*(\d{4})', fn, re.I)
            if not m:
                continue
            mname = m.group(1).lower()
            month = CL_MONTHS.get(mname)
            year = int(m.group(2))
            if month and 2010 <= year <= 2030:
                full = href if href.startswith('http') else CL_BASE + href
                found[(year, month)] = full
        return found

    def parse_brand_table(self, pdf_bytes):
        """解析品牌表 (跨 Parte 1/2 两页), 返回 [(brand, qty), ...]。
        品牌行: 品牌 + 各segment (Rank Uni Part%) 三元组, 最后一个三元组 = TOTAL。
        """
        import pdfplumber
        records = []
        seen = set()
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ''
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                in_table = False
                for ln in lines:
                    u = ln.upper()
                    if 'VENTAS A PÚBLICO POR MARCA' in u or 'VENTAS A PUBLICO POR MARCA' in u:
                        in_table = True
                        continue
                    if not in_table:
                        continue
                    if u.startswith('MARCA') or u.startswith('SEGMENTOS'):
                        continue
                    if 'POWER BI' in u or 'FUENTE' in u or 'REGISTRO CIVIL' in u:
                        continue
                    if u.startswith('ACUMULADAS') or u.startswith('RANKING MODELOS'):
                        break
                    # 品牌行: ^(品牌) 后跟若干 (Rank Uni Part%) 三元组
                    m = re.match(r'^([A-Z][A-Z0-9\s\.&\-]{1,35}?)\s+(\d+\s+[\d\.]+\s+[\d,]+\%[^\n]*)$', ln)
                    if not m:
                        continue
                    brand = m.group(1).strip()
                    if brand in CL_SKIP or brand.startswith('OTROS'):
                        continue
                    # 提取所有三元组 (Rank Uni Part%)
                    triples = re.findall(r'(\d+)\s+([\d\.]+)\s+([\d,]+)\%', m.group(2))
                    if not triples:
                        continue
                    # TOTAL = 最后一个三元组的 Uni
                    qty_s = triples[-1][1].replace('.', '')
                    try:
                        qty = int(qty_s)
                    except ValueError:
                        continue
                    if brand not in seen and qty > 0:
                        seen.add(brand)
                        records.append((brand, qty))
        return records

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
        """爬指定月份, 返回 {'records': n}"""
        urls = self.discover_pdf_urls()
        pdf_url = urls.get((year, month))
        if not pdf_url:
            return {'records': 0}
        dest = os.path.join(self._dl_dir, f'{year}-{month:02d}.pdf')
        import pdfplumber
        content = None
        for attempt in range(3):
            path = self._download_range(pdf_url, dest)
            if not path:
                return {'records': 0}
            try:
                with open(path, 'rb') as f:
                    data = f.read()
                # 校验 PDF 完整性: 能打开且页数合理才解析
                with pdfplumber.open(io.BytesIO(data)) as pdf:
                    if len(pdf.pages) >= 2:
                        content = data
                        break
            except Exception:
                # 损坏或下载中断: 删除重下
                print(f'CL {year}-{month} PDF corrupt, re-download attempt {attempt + 1}')
                if os.path.exists(dest):
                    os.remove(dest)
        if content is None:
            return {'records': 0}
        brands = self.parse_brand_table(content)
        n = 0
        for brand, qty in brands:
            rec = {
                'country_code': 'CL',
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
                'data_source': 'cl_anac_brand_monthly',
                'notes': 'ANAC Mercado Automotor brand sales (Registro Civil)',
            }
            self.save_sales(rec)
            n += 1
        return {'records': n}

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='CL'")
        row = cur.fetchone()
        m = row['m'] if isinstance(row, dict) else row[0]
        return m.date() if hasattr(m, 'date') else m

    def crawl_incremental(self):
        max_m = self._get_db_max_month()
        urls = self.discover_pdf_urls()
        saved = 0
        for (y, m) in sorted(urls.keys()):
            sm = date(y, m, 1)
            if max_m is None or sm > max_m:
                res = self.crawl_month(y, m)
                saved += res['records']
        return saved

    def crawl_range(self, y1, m1, y2, m2):
        urls = self.discover_pdf_urls()
        results = {}
        for (y, m) in sorted(urls.keys()):
            if (y, m) < (y1, m1) or (y, m) > (y2, m2):
                continue
            res = self.crawl_month(y, m)
            results[f'{y}-{m:02d}'] = res
            print(f'{y}-{m:02d}: {res}')
            time.sleep(1)
        return results


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--incremental', action='store_true')
    ap.add_argument('--ym', type=str, default='', help='单月 2026-07')
    ap.add_argument('--y1', type=int, default=2026)
    ap.add_argument('--m1', type=int, default=1)
    ap.add_argument('--y2', type=int, default=2026)
    ap.add_argument('--m2', type=int, default=7)
    args = ap.parse_args()

    c = ClCrawler()
    if args.ym:
        y, m = map(int, args.ym.split('-'))
        print(c.crawl_month(y, m))
    elif args.incremental:
        n = c.crawl_incremental()
        print(f'CL incremental saved: {n}')
    else:
        urls = c.discover_pdf_urls()
        print('pdf urls found:', len(urls))
        res = c.crawl_range(args.y1, args.m1, args.y2, args.m2)
        print('CL range done')


if __name__ == '__main__':
    main()
