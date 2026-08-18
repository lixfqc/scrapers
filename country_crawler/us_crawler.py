# -*- coding: utf-8 -*-
import re
import random
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST


US_BASE_URL = 'https://www.goodcarbadcar.net'

US_BRANDS = [
    'toyota', 'honda', 'ford', 'chevrolet', 'bmw', 'hyundai', 'kia', 'nissan',
    'subaru', 'mazda', 'lexus', 'gmc', 'buick', 'cadillac', 'jeep', 'ram',
    'dodge', 'chrysler', 'audi', 'volkswagen', 'tesla', 'volvo', 'acura',
    'lincoln', 'genesis', 'mini', 'porsche', 'mitsubishi', 'land-rover',
    'infiniti', 'jaguar', 'bentley', 'maserati', 'fiat', 'alfa-romeo',
    'mercedes-benz', 'jaguar-land-rover',
]

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


class UsCrawler(BaseCrawler):
    def __init__(self, source_name='goodcarbadcar_us', country_code='US'):
        super().__init__(source_name, country_code)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': random.choice(UA_LIST)})
        self._brand_id_cache = {}

    def get_brand_id(self, brand_name_raw):
        if brand_name_raw in self._brand_id_cache:
            return self._brand_id_cache[brand_name_raw]
        conn, cur = self.get_connection()
        lookup = brand_name_raw.upper()
        cur.execute("""
            SELECT id FROM brand_name_mapping
            WHERE UPPER(canonical_name) = %s OR UPPER(brand_name_cn) = %s
            ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, id LIMIT 1
        """, (lookup, lookup))
        row = cur.fetchone()
        bid = row['id'] if row else None
        if bid is None:
            cur.execute("SELECT brand_id FROM brand_name_variant WHERE UPPER(variant_name) = %s LIMIT 1", (lookup,))
            row = cur.fetchone()
            bid = row['brand_id'] if row else None
        self._brand_id_cache[brand_name_raw] = bid
        return bid

    def save_sales(self, record):
        record['brand_id'] = self.get_brand_id(record['brand_name_raw'])
        return super().save_sales(record)

    def _fetch_page(self, url):
        r = self.retry_request(self.session.get, url, timeout=60)
        if r is None:
            return None
        r.raise_for_status()
        return r.text

    def discover_brand_urls(self):
        urls = []
        for slug in US_BRANDS:
            urls.append((slug, f'{US_BASE_URL}/{slug}-us-sales-figures/'))
        return urls

    def parse_brand_page(self, html, brand):
        soup = BeautifulSoup(html, 'html.parser')
        tables = soup.find_all('table')
        records = []
        if not tables:
            return records
        t = tables[0]
        rows = t.find_all('tr')
        if len(rows) < 3:
            return records
        header = [c.get_text(strip=True) for c in rows[1].find_all(['th', 'td'])]
        month_cols = {}
        for i, h in enumerate(header):
            if h in MONTHS:
                month_cols[h] = i
        if len(month_cols) < 12:
            return records
        for tr in rows[2:]:
            cells = [c.get_text(strip=True) for c in tr.find_all(['th', 'td'])]
            if not cells:
                continue
            y_text = cells[0]
            if not re.match(r'^(19|20)\d{2}$', y_text):
                continue
            year = int(y_text)
            for m_name, col in month_cols.items():
                if col >= len(cells):
                    continue
                v_text = cells[col].replace(',', '').strip()
                if not v_text or v_text == '0':
                    continue
                try:
                    qty = int(float(v_text))
                except ValueError:
                    continue
                if qty <= 0:
                    continue
                month = MONTHS.index(m_name) + 1
                records.append({
                    'country_code': 'US',
                    'source_month': date(year, month, 1),
                    'brand_name_raw': brand,
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
                    'data_source': self.source_name,
                    'notes': f'goodcarbadcar {brand} US monthly sales',
                })
        return records

    def crawl_brand(self, slug, brand):
        html = self._fetch_page(f'{US_BASE_URL}/{slug}-us-sales-figures/')
        if html is None:
            return 0
        records = self.parse_brand_page(html, brand)
        n = 0
        for rec in records:
            if self.save_sales(rec):
                n += 1
        return n

    def crawl_all(self):
        total = 0
        for slug, brand in [('toyota', 'TOYOTA'), ('honda', 'HONDA'), ('ford', 'FORD')]:
            pass
        for slug, url in self.discover_brand_urls():
            brand = slug.upper().replace('-', ' ')
            brand = re.sub(r'\s+', ' ', brand).strip()
            try:
                n = self.crawl_brand(slug, brand)
                total += n
                print(f'{slug}: {n}')
            except Exception as e:
                print(f'{slug}: ERROR {e}')
        return total


if __name__ == '__main__':
    c = UsCrawler()
    print('total saved:', c.crawl_all())
