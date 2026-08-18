# -*- coding: utf-8 -*-
import re, io, os
import requests
import pdfplumber
from datetime import date, datetime

from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

RO_BASE_URL = 'https://www.apia.ro'
RO_LIST_URLS = [
    'https://www.apia.ro/comunicate-de-presa/comunicate-de-presa-lunare-2026/',
    'https://www.apia.ro/comunicate-de-presa/comunicate-de-presa-lunare-2025/',
    'https://www.apia.ro/comunicate-de-presa/comunicate-de-presa-lunare-2024/',
    'https://www.apia.ro/comunicate-de-presa/comunicate-de-presa-lunare-2023/',
]
RO_MONTH_MAP = {
    'ianuarie': 1, 'februarie': 2, 'martie': 3, 'aprilie': 4, 'mai': 5,
    'iunie': 6, 'iulie': 7, 'august': 8, 'septembrie': 9, 'octombrie': 10,
    'noiembrie': 11, 'decembrie': 12,
}
SKIP_BRANDS = {'TOTAL', 'ALTE MĂRCI', 'ALTE MARCI', 'TOTAL PIATA', 'TOTAL PIAȚĂ', 'REST', 'RESTUL', 'MARCA'}


def _to_int(v):
    if v is None:
        return 0
    s = str(v).strip()
    s = s.replace('.', '').replace(' ', '').replace(',', '')
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


class RoCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('apia', 'RO')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
            'Accept-Language': 'ro,en;q=0.8',
        })
        self._brand_id_cache = {}
        self._file_index = None

    def _fetch(self, url, timeout=60):
        try:
            r = self.session.get(url, timeout=timeout)
            if r.status_code == 200:
                return r
        except Exception:
            pass
        return None

    def _build_file_index(self):
        if self._file_index is not None:
            return self._file_index
        index = {}
        for list_url in RO_LIST_URLS:
            r = self._fetch(list_url)
            if not r:
                continue
            r.encoding = r.apparent_encoding or 'utf-8'
            html = r.text
            for m in re.finditer(r'href="([^"]+\.pdf[^"]*)"', html, re.I):
                url = m.group(1)
                if not url.startswith('http'):
                    url = RO_BASE_URL + url
                ym = self._month_from_url(url)
                if ym:
                    index[ym] = url
        self._file_index = index
        return index

    def _month_from_url(self, url):
        # urls like .../Comunicat-de-presa-IULIE-2026.pdf or .../iulie-2026...
        for m in re.finditer(r'([a-zA-ZăâîșțĂÂÎȘȚ]+)[\-_\.]?(\d{4})', url):
            mn, yr = m.group(1).lower(), m.group(2)
            if mn in RO_MONTH_MAP and int(yr) >= 2000:
                return (int(yr), RO_MONTH_MAP[mn])
        return None

    def latest_available_month(self):
        idx = self._build_file_index()
        if not idx:
            return None
        return max(idx.keys())

    def get_file_url(self, year, month):
        idx = self._build_file_index()
        return idx.get((year, month))

    def download_pdf(self, url):
        r = self._fetch(url)
        if not r:
            return None
        content = r.content
        if len(content) < 1000:
            return None
        return content

    def parse_pdf(self, content):
        """Parse brand table from APIA PDF. Returns (brands, total).

        Handles 3 layouts:
        - 2025+: 'TOP MĂRCI AUTOTURISME' section (P2)
        - 2023:   'Top inmatriculari autoturisme - marci' section (dual-column, take left col)
        - 2024:   standalone 'MARCA' header then brand rows until 'MARCA MODEL'
        """
        brands = []
        total = 0
        seen = set()
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ''
                    lines = text.split('\n')
                    section = None
                    # layout 1: TOP MĂRCI AUTOTURISME (2025+)
                    for i, ln in enumerate(lines):
                        if 'TOP' in ln and 'MĂRCI' in ln and 'AUTOTURISME' in ln:
                            section = self._slice_section(lines, i, ['Surs', 'MODEL', 'Segmentarea', 'platforma'])
                            break
                    if section is None:
                        # layout 2: Top inmatriculari autoturisme - marci (2023)
                        for i, ln in enumerate(lines):
                            if 'autoturisme' in ln.lower() and '- marci' in ln.lower():
                                # find header MARCA row after title
                                for j in range(i, min(i + 5, len(lines))):
                                    if 'MARCA' in lines[j]:
                                        section = self._slice_section(lines, j, ['- modele', 'Top inmatriculari', 'MODEL', 'Surs'])
                                        break
                                break
                    if section is None:
                        # layout 3: MARCA header row (2024, 'MARCA' or 'MARCA sim.') - only the
                        # main brand table (next rows contain 'unități...anterior' header), NOT energy tables
                        for i, ln in enumerate(lines):
                            u = ln.strip().upper()
                            if u.startswith('MARCA') and 'MODEL' not in u and len(u) < 20:
                                window = lines[i + 1:i + 4]
                                has_units = any('unități' in w or 'unitati' in w.lower() or 'sim.' in w.lower() for w in window)
                                has_data = any(re.match(r'^[A-ZĂÂÎȘȚ][\w\s\.\-]*?\s+\d', w) for w in window)
                                if has_units and has_data:
                                    section = self._slice_section(lines, i, ['MARCA MODEL', 'MODEL', 'Surs'])
                                break
                    if not section:
                        continue
                    in_brands = False
                    for ln in section:
                        if 'MARCA' in ln or 'unități' in ln or 'COTA' in ln or 'iulie' in ln.lower():
                            in_brands = True
                            continue
                        if not in_brands:
                            continue
                        m = re.match(r'^([A-ZĂÂÎȘȚ][\w\s\.\-]*?)\s+(\d[\d\.]*)\b', ln)
                        if not m:
                            continue
                        bname = m.group(1).strip()
                        qty = _to_int(m.group(2))
                        if not bname or qty is None:
                            continue
                        up = bname.upper()
                        if up in SKIP_BRANDS or up.startswith('TOTAL') or up.startswith('ALTE'):
                            if up.startswith('TOTAL') and not up.startswith('TOTAL PIATA'):
                                total = qty
                            continue
                        # filter fragmented text rows (e.g. 'A TO lte T M AL ă rci' = split 'Alte Mărci')
                        single_letters = len(re.findall(r'(?:^|\s)[A-ZĂÂÎȘȚ](?:\s|$)', bname))
                        if single_letters >= 3:
                            continue
                        if bname in seen:
                            continue
                        seen.add(bname)
                        brands.append((bname, qty))
                    if brands:
                        return brands, total
        except Exception as e:
            print(f'parse_pdf error: {e}')
        return brands, total

    def _slice_section(self, lines, start, end_markers):
        end = len(lines)
        for j in range(start + 1, len(lines)):
            l = lines[j]
            low = l.lower()
            if any(k.lower() in low for k in end_markers):
                end = j
                break
        return lines[start:end]

    def get_brand_id(self, brand_raw):
        if not brand_raw:
            return None
        key = brand_raw.strip().upper()
        if key in self._brand_id_cache:
            return self._brand_id_cache[key]
        conn, cur = self.get_connection()
        bid = None
        try:
            cur.execute("""
                SELECT id FROM brand_name_mapping
                WHERE UPPER(canonical_name) = %s OR UPPER(brand_name_cn) = %s
                ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, id LIMIT 1
            """, (key, key))
            row = cur.fetchone()
            if row:
                bid = row['id']
            else:
                cur.execute("SELECT brand_id FROM brand_name_variant WHERE UPPER(variant_name) = %s LIMIT 1", (key,))
                row = cur.fetchone()
                if row:
                    bid = row['brand_id']
        except Exception as e:
            print(f'get_brand_id error {brand_raw}: {e}')
        self._brand_id_cache[key] = bid
        return bid

    def save_sales(self, record):
        bid = self.get_brand_id(record.get('brand_name_raw'))
        record['brand_id'] = bid
        return super().save_sales(record)

    def crawl_month(self, year, month):
        url = self.get_file_url(year, month)
        if not url:
            return {'records': 0, 'note': 'no file in index'}
        content = self.download_pdf(url)
        if not content:
            return {'records': 0, 'note': 'download failed'}
        brands, total = self.parse_pdf(content)
        n = 0
        for brand, qty in brands:
            rec = {
                'country_code': 'RO',
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
                'data_source': 'apia',
                'notes': 'APIA new car registrations by brand (TOP5+Alte Marci)',
            }
            try:
                self.save_sales(rec)
                n += 1
            except Exception as e:
                print(f'save error {brand}: {e}')
        return {'records': n, 'total': total}

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='RO'")
        row = cur.fetchone()
        m = row['m'] if row else None
        return m.date() if m and isinstance(m, datetime) else m

    def crawl_incremental(self):
        latest = self.latest_available_month()
        if not latest:
            return 0
        latest_date = date(latest[0], latest[1], 1)
        max_m = self._get_db_max_month()
        if max_m is not None and latest_date <= max_m:
            return 0
        r = self.crawl_month(latest[0], latest[1])
        return r.get('records', 0)

    def crawl_range(self, start_year, start_month, end_year, end_month):
        results = {}
        y, m = start_year, start_month
        while (y, m) <= (end_year, end_month):
            results[f'{y}-{m:02d}'] = self.crawl_month(y, m)
            m += 1
            if m > 12:
                m = 1
                y += 1
        return results


if __name__ == '__main__':
    c = RoCrawler()
    idx = c._build_file_index()
    print(f'RO index months: {len(idx)}')
    if idx:
        latest = max(idx.keys())
        print(f'latest: {latest}')
        r = c.crawl_month(latest[0], latest[1])
        print(r)
