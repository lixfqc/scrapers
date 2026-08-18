# -*- coding: utf-8 -*-
import re
import random
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST


AU_BASE_URL = 'https://www.carexpert.com.au'
AU_CATEGORY_URL = f'{AU_BASE_URL}/category/vfacts/'

MONTH_NAMES = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
}

AU_FUEL_MAP = {
    'PETROL': 'GASOLINE',
    'DIESEL': 'DIESEL',
    'ELECTRIC': 'BEV',
    'HYBRID': 'HEV',
    'PHEV': 'PHEV',
    'LPG': 'LPG',
    'CNG': 'CNG',
    'FCEV': 'FCEV',
}


class AuCrawler(BaseCrawler):
    def __init__(self, source_name='carexpert_vfacts', country_code='AU'):
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

    def _fetch(self, url):
        if not url.startswith('http'):
            url = AU_BASE_URL + url
        r = self.retry_request(self.session.get, url, timeout=60)
        if r is None:
            return None
        r.raise_for_status()
        return r.text

    def discover_article_urls(self, max_pages=20):
        urls = []
        for page in range(1, max_pages + 1):
            url = AU_CATEGORY_URL if page == 1 else f'{AU_CATEGORY_URL}page/{page}/'
            html = self._fetch(url)
            if html is None:
                break
            soup = BeautifulSoup(html, 'html.parser')
            found = 0
            for a in soup.find_all('a', href=True):
                h = a['href']
                if '/car-news/vfacts-' in h and h not in urls:
                    urls.append(h)
                    found += 1
            if found == 0:
                break
        return urls

    def _parse_month_from_url(self, url):
        m = re.search(r'vfacts-([a-z]+)-(\d{4})', url)
        if m:
            month_name = m.group(1)
            year = int(m.group(2))
            if month_name in MONTH_NAMES:
                return (year, MONTH_NAMES[month_name])
        return None

    def parse_article(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        tables = soup.find_all('table')
        records = []
        month_info = None
        # month from title
        title = soup.find('h1')
        if title:
            t = title.get_text()
            m = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})', t, re.I)
            if m:
                month_info = (int(m.group(2)), MONTH_NAMES[m.group(1).lower()])
        if month_info is None:
            return records, None
        year, month = month_info
        if len(tables) < 1:
            return records, month_info
        # brand table = first table with Brand header
        brand_records = []
        for t in tables:
            rows = t.find_all('tr')
            if not rows:
                continue
            head = [c.get_text(strip=True).lower() for c in rows[0].find_all(['th', 'td'])]
            if 'brand' in head and any(('deliveries' in h) or ('sales' in h) for h in head):
                for tr in rows[1:]:
                    cells = [c.get_text(strip=True) for c in tr.find_all(['th', 'td'])]
                    if len(cells) < 2:
                        continue
                    brand = cells[0]
                    v = cells[1].replace(',', '').strip()
                    if not brand or not re.match(r'^[\d\s]+$', v):
                        continue
                    try:
                        qty = int(float(v))
                    except ValueError:
                        continue
                    if qty <= 0:
                        continue
                    brand_records.append((brand, qty))
                break
        # fuel table
        fuel_records = []
        for t in tables:
            rows = t.find_all('tr')
            if not rows:
                continue
            head = [c.get_text(strip=True).lower() for c in rows[0].find_all(['th', 'td'])]
            if any('fuel' in h for h in head) and any('sales' in h for h in head):
                for tr in rows[1:]:
                    cells = [c.get_text(strip=True) for c in tr.find_all(['th', 'td'])]
                    if len(cells) < 2:
                        continue
                    fuel = cells[0].upper()
                    v = cells[1].replace(',', '').strip()
                    if not fuel or not re.match(r'^[\d\s]+$', v):
                        continue
                    try:
                        qty = int(float(v))
                    except ValueError:
                        continue
                    if qty <= 0:
                        continue
                    et = AU_FUEL_MAP.get(fuel)
                    if et:
                        fuel_records.append((fuel, qty, et))
                break
        for brand, qty in brand_records:
            records.append({
                'country_code': 'AU',
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
                'notes': 'CarExpert VFACTS brand deliveries',
            })
        for fuel, qty, et in fuel_records:
            records.append({
                'country_code': 'AU',
                'source_month': date(year, month, 1),
                'brand_name_raw': 'AU INDUSTRY',
                'model_name': None,
                'vehicle_type': 'passenger',
                'energy_type': et,
                'segment': None,
                'raw_unit': 'units',
                'sales_volume_raw': qty,
                'sales_volume_normalized': qty,
                'revision_no': 1,
                'is_latest': True,
                'pub_date': None,
                'crawl_time': datetime.now(),
                'data_source': self.source_name,
                'notes': f'CarExpert VFACTS fuel {fuel}',
            })
        return records, month_info

    def crawl_all(self, max_pages=20):
        urls = self.discover_article_urls(max_pages=max_pages)
        print('discovered articles:', len(urls))
        total = 0
        for u in urls:
            html = self._fetch(u)
            if html is None:
                continue
            records, mi = self.parse_article(html)
            if not records or mi is None:
                continue
            n = 0
            for rec in records:
                if self.save_sales(rec):
                    n += 1
            total += n
            print(f'{mi[0]}-{mi[1]:02d}: {n} records', flush=True)
        return total


if __name__ == '__main__':
    c = AuCrawler()
    print('total saved:', c.crawl_all(max_pages=20))
