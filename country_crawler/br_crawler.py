# -*- coding: utf-8 -*-
import sys, io, os, re, time, random
import requests
import pdfplumber
from datetime import datetime, date
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

BR_API_URL = 'https://www.fenabrave.org.br/portalv2/api/Emplacamentos'
BR_DL_URL = 'https://www.fenabrave.org.br/portal/files/'
BR_FUEL_MAP = {}
SKIP_BRANDS = {'TOTAL', 'OUTROS', 'OUTRAS', 'SUB-TOTAL', 'SUBTOTAL'}

# 葡萄牙语月份
BR_MONTHS = {'janeiro': 1, 'fevereiro': 2, 'março': 3, 'abril': 4, 'maio': 5, 'junho': 6,
             'julho': 7, 'agosto': 8, 'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12}

class BrCrawler(BaseCrawler):
    def __init__(self, source_name='fenabrave_emplacamentos', country_code='BR'):
        super().__init__(source_name, country_code)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': random.choice(UA_LIST),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
        })
        self._brand_id_cache = {}
        self._dl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads', 'fenabrave')
        os.makedirs(self._dl_dir, exist_ok=True)

    def _to_int(self, v):
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        # 去千分位点，逗号转点（小数）
        s = s.replace('.', '').replace(',', '.')
        try:
            return int(float(s))
        except Exception:
            return None

    def get_file_index(self, year):
        """POST API 获取某年所有月份PDF链接"""
        try:
            r = self.session.post(BR_API_URL, data={'ano': str(year)}, timeout=60)
            j = r.json()
            out = []
            for b in j.get('data', {}).get('blocos', []):
                link = b.get('link')
                m = b.get('data') or ''
                # data 如 '2026-07-01'
                ym = re.match(r'(\d{4})-(\d{2})', str(m))
                if link and ym:
                    out.append((int(ym.group(1)), int(ym.group(2)), link))
            return out
        except Exception as e:
            print(f'[BR] get_file_index({year}) error: {e}')
            return []

    def download_pdf(self, year, month, link):
        """断点续传下载PDF，返回本地路径或None"""
        url = BR_DL_URL + link
        fpath = os.path.join(self._dl_dir, f'{year}_{month:02d}.pdf')
        if os.path.exists(fpath) and os.path.getsize(fpath) > 100000:
            return fpath
        # 获取文件大小
        try:
            h = self.session.get(url, headers={'Range': 'bytes=0-0'}, timeout=30)
            clen = h.headers.get('Content-Range', '')
            total = int(clen.split('/')[-1]) if '/' in clen else 0
        except Exception:
            total = 0
        downloaded = os.path.getsize(fpath) if os.path.exists(fpath) else 0
        for attempt in range(5):
            try:
                hdr = {'Range': f'bytes={downloaded}-'}
                if downloaded == 0:
                    hdr = {}
                r = self.session.get(url, headers=hdr, stream=True, timeout=60)
                if r.status_code in (200, 206):
                    with open(fpath, 'ab') as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                    if total and downloaded >= total * 0.95:
                        return fpath
                    # 已下载完
                    if not r.headers.get('Content-Range') and downloaded > 0:
                        return fpath
                else:
                    return None
            except Exception as e:
                print(f'[BR] download {year}-{month} attempt{attempt} error: {e}')
                time.sleep(3)
        return fpath if os.path.exists(fpath) and os.path.getsize(fpath) > 100000 else None

    def parse_pdf(self, fpath, year, month):
        """解析PDF P8 AUTOMÓVEIS 品牌级（左栏）"""
        brands = []
        try:
            with pdfplumber.open(fpath) as pdf:
                for page in pdf.pages:
                    txt = page.extract_text() or ''
                    if 'Ranking por marca' not in txt:
                        continue
                    lines = txt.split('\n')
                    in_auto = False
                    for line in lines:
                        lu = line.upper()
                        # 合并栏标题（含+），AUTOMÓVEIS栏结束
                        if 'AUTOMÓVEIS + COMERCIAIS' in lu:
                            break
                        # 栏标题行（不含合并+，含AUTOMÓVEIS）
                        if 'AUTOMÓVEIS' in lu and 'RANKING' not in lu and 'marca' not in line.lower() and 'º' not in line:
                            in_auto = True
                            continue
                        if in_auto:
                            # 行格式: 1º VW 36.183 17,01% 1º FIAT 23.890 45,07%
                            m = re.match(r'^(\d+)º\s+([A-ZÀ-Ú0-9\.\-\s]+?)\s+([\d\.]+)\s+([\d,]+)%', line)
                            if m:
                                bname = m.group(2).strip()
                                qty = self._to_int(m.group(3))
                                if bname and qty and bname.upper() not in SKIP_BRANDS:
                                    brands.append((bname, qty))
                                continue
                            # 无份额的格式（早期）
                            m2 = re.match(r'^(\d+)º\s+([A-ZÀ-Ú0-9\.\-\s]+?)\s+([\d\.]+)$', line)
                            if m2 and m2.group(2).strip().upper() not in SKIP_BRANDS:
                                bname = m2.group(2).strip()
                                qty = self._to_int(m2.group(3))
                                if bname and qty:
                                    brands.append((bname, qty))
                    if brands:
                        break
        except Exception as e:
            print(f'[BR] parse_pdf {year}-{month} error: {e}')
        return brands

    def get_brand_id(self, brand_raw):
        if not brand_raw:
            return None
        key = brand_raw.upper()
        if key in self._brand_id_cache:
            return self._brand_id_cache[key]
        bid = None
        try:
            conn, cur = self.get_connection()
            # 先查mapping（canonical/brand_name_cn），不限制status
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
            print(f'[BR] get_brand_id({brand_raw}) error: {e}')
        self._brand_id_cache[key] = bid
        return bid

    def save_sales(self, record):
        record['brand_id'] = self.get_brand_id(record.get('brand_name_raw'))
        super().save_sales(record)

    def crawl_month(self, year, month):
        idx = self.get_file_index(year)
        link = None
        for y, m, l in idx:
            if y == year and m == month:
                link = l
                break
        if not link:
            return {'records': 0, 'msg': 'no file'}
        fpath = self.download_pdf(year, month, link)
        if not fpath:
            return {'records': 0, 'msg': 'download fail'}
        brands = self.parse_pdf(fpath, year, month)
        n = 0
        for bname, qty in brands:
            rec = {
                'country_code': 'BR', 'source_month': date(year, month, 1),
                'brand_name_raw': bname, 'brand_id': None, 'model_name': None,
                'vehicle_type': 'passenger', 'energy_type': None, 'segment': None,
                'raw_unit': 'units', 'sales_volume_raw': qty, 'sales_volume_normalized': qty,
                'revision_no': 1, 'is_latest': True, 'pub_date': None,
                'crawl_time': datetime.now(), 'created_at': datetime.now(),
                'data_source': self.source_name,
                'notes': 'Fenabrave emplacamentos por marca (Automóveis)',
            }
            self.save_sales(rec)
            n += 1
        return {'records': n}

    def crawl_range(self, start_year, start_month, end_year, end_month):
        results = {}
        for y in range(start_year, end_year + 1):
            for m in range(1, 13):
                if (y, m) < (start_year, start_month) or (y, m) > (end_year, end_month):
                    continue
                r = self.crawl_month(y, m)
                results[f'{y}-{m:02d}'] = r
                print(f'[BR] {y}-{m:02d}: {r}')
                time.sleep(2)
        return results

    def crawl_incremental(self):
        from datetime import date
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='BR'")
        row = cur.fetchone()
        max_m = row['m'] if row else None
        # 探测最新可用月份
        latest = None
        for y in (2026, 2025):
            idx = self.get_file_index(y)
            for yy, mm, _ in idx:
                if latest is None or (yy, mm) > latest:
                    latest = (yy, mm)
        if not latest:
            return 0
        latest_date = date(latest[0], latest[1], 1)
        if max_m and latest_date <= max_m:
            return 0
        r = self.crawl_month(latest[0], latest[1])
        return r.get('records', 0)

    def main(self):
        r = self.crawl_incremental()
        print(f'BR crawl_incremental saved: {r}')

if __name__ == '__main__':
    c = BrCrawler()
    c.main()
