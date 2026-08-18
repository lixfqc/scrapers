# -*- coding: utf-8 -*-
"""阿根廷 AR 爬虫: ACARA《Informe de Mercado》月度 PDF 品牌级 TOP40 (零售注册口径)
获取路径: motormagazine.com.ar WP REST API 搜 slug 'asi-fueron-las-ventas-de-0-km-en-*'
→ 文章内嵌 PDF 'ACARA-Informe-de-Mercado-{Mes}-{Año}.pdf' → 解析 TABLA 2 (TOP40 Marcas Livianos)
口径: patentamientos 0km 上牌 = 零售新车注册
"""
import re
import io
import time
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

AR_BASE = 'https://motormagazine.com.ar'
AR_API = 'https://motormagazine.com.ar/wp-json/wp/v2/posts'

AR_MONTHS = {'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
             'julio': 7, 'agosto': 8, 'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12}


class ArCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('ar_acara_informe_de_mercado', 'AR')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'es-AR,es;q=0.9,en-US;q=0.8,en;q=0.7',
        })
        self._brand_cache = {}

    def _fetch_json(self, url, timeout=60):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
            except Exception as e:
                print(f'_fetch_json {url} err: {e}')
            time.sleep(2)
        return None

    def discover_month_urls(self):
        """WP search 'informe-de-mercado' 分页遍历, 找含 '0-km' slug 的文章。
        数据月 = slug 中的月份词+年份 (年份缺失时用发布年)。
        返回 {(year, month): pdf_url}。
        """
        found = {}
        seen_slugs = set()
        for page in range(1, 20):
            url = f'{AR_API}?search=informe-de-mercado&per_page=100&page={page}'
            data = self._fetch_json(url)
            if not data:
                break
            if len(data) == 0:
                break
            for p in data:
                slug = p.get('slug', '')
                if not re.search(r'0-?km', slug):
                    continue
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)
                # 发布年 (年份兜底)
                dstr = p.get('date', '') or ''
                m = re.match(r'(\d{4})-(\d{2})', dstr)
                pub_year = int(m.group(1)) if m else 2026
                # 数据月 = slug 月份词 + 年份
                m = re.search(r'0-?km-en-([a-z]+)(?:-(\d{4}))?', slug)
                if not m:
                    continue
                month = AR_MONTHS.get(m.group(1))
                if not month:
                    continue
                data_year = int(m.group(2)) if m.group(2) else pub_year
                if not (2015 <= data_year <= 2030):
                    continue
                # 提取文章内 PDF 链接 (含 ACARA/mercado)
                content = p.get('content', {}).get('rendered', '')
                pdfs = re.findall(r'href="([^"]+\.pdf[^"]*)"', content, re.I)
                pdf_url = None
                for href in pdfs:
                    if 'acara' in href.lower() and 'mercado' in href.lower():
                        pdf_url = href
                        break
                if not pdf_url and pdfs:
                    pdf_url = pdfs[0]
                if pdf_url:
                    if pdf_url.startswith('//'):
                        pdf_url = 'https:' + pdf_url
                    elif not pdf_url.startswith('http'):
                        pdf_url = AR_BASE + pdf_url
                    found[(data_year, month)] = pdf_url
            if len(data) < 100:
                break
            time.sleep(0.8)
        return found

    def _fetch(self, url, timeout=120):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200 and len(r.content) > 5000:
                    return r.content
            except Exception as e:
                print(f'_fetch {url} err: {e}')
            time.sleep(2)
        return None

    def parse_pdf(self, pdf_bytes):
        """解析 TABLA 2 (TOP40 Marcas Livianos)。返回 [(brand, qty)] 和 total。
        品牌行: 排名 品牌 当月销量 份额% ...
        """
        import pdfplumber
        brands = []
        total = None
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = ''
            for page in pdf.pages:
                t = page.extract_text() or ''
                text += t + '\n'
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        # 定位 TABLA 2 (TOP40 Marcas Livianos)
        in_tabla2 = False
        for ln in lines:
            u = ln.upper()
            # 开始: TABLA 2 ... MARCAS LIVIANOS
            if not in_tabla2 and 'MARCAS LIVIANOS' in u and ('TOP 40' in u or 'TABLA 2' in u or 'TOP40' in u):
                in_tabla2 = True
                continue
            if not in_tabla2:
                # 表头行 (含 JUL.2026 PART 等) 后开始
                if 'PART' in u and 'VAR%' in u and re.search(r'JUL\.\d{4}', u):
                    in_tabla2 = True
                    continue
            if not in_tabla2:
                continue
            # 结束: TABLA 3 (车型) 或 TABLA 4 (Pesados)
            if 'TABLA 3' in u or 'TABLA 4' in u or 'MODELOS MÁS' in u or 'MODELOS MAS' in u:
                break
            # 品牌行: [排名] 品牌 当月 份额%
            # 2026+格式带排名 (1 TOYOTA 7.102 17,3%), 2025年无排名 (VOLKSWAGEN 3.496 15,6%)
            m = re.match(r'^(?:\d{1,2}\s+)?([A-Z][A-Z0-9\s\.&\-]{1,35}?)\s+([\d\.]+)\s+[\d,]+%', ln)
            if m:
                brand = m.group(1).strip()
                qty_s = m.group(2).replace('.', '')
                try:
                    qty = int(qty_s)
                except ValueError:
                    continue
                if brand.upper() in ('TOTAL', 'TOTALES') or brand.upper().startswith('TOTAL'):
                    total = qty
                    continue
                brands.append((brand, qty))
        return brands, total

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
        """爬指定月份, 返回 {'records': n, 'total': t}"""
        urls = self.discover_month_urls()
        pdf_url = urls.get((year, month))
        if not pdf_url:
            return {'records': 0, 'total': None}
        content = self._fetch(pdf_url)
        if not content:
            return {'records': 0, 'total': None}
        brands, total = self.parse_pdf(content)
        n = 0
        for brand, qty in brands:
            rec = {
                'country_code': 'AR',
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
                'data_source': 'ar_acara_informe_de_mercado',
                'notes': 'ACARA Informe de Mercado brand TOP40 (retail registrations)',
            }
            self.save_sales(rec)
            n += 1
        return {'records': n, 'total': total}

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='AR'")
        row = cur.fetchone()
        m = row['m'] if isinstance(row, dict) else row[0]
        return m.date() if hasattr(m, 'date') else m

    def crawl_incremental(self):
        max_m = self._get_db_max_month()
        urls = self.discover_month_urls()
        saved = 0
        for (y, m) in sorted(urls.keys()):
            sm = date(y, m, 1)
            if max_m is None or sm > max_m:
                res = self.crawl_month(y, m)
                saved += res['records']
        return saved

    def crawl_range(self, y1, m1, y2, m2):
        urls = self.discover_month_urls()
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
    ap.add_argument('--y1', type=int, default=2019)
    ap.add_argument('--m1', type=int, default=1)
    ap.add_argument('--y2', type=int, default=2026)
    ap.add_argument('--m2', type=int, default=7)
    args = ap.parse_args()

    c = ArCrawler()
    if args.ym:
        y, m = map(int, args.ym.split('-'))
        print(c.crawl_month(y, m))
    elif args.incremental:
        n = c.crawl_incremental()
        print(f'AR incremental saved: {n}')
    else:
        urls = c.discover_month_urls()
        print('months found:', len(urls))
        res = c.crawl_range(args.y1, args.m1, args.y2, args.m2)
        print('AR range done')


if __name__ == '__main__':
    main()
