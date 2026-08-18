# -*- coding: utf-8 -*-
"""泰国 TH 爬虫: autolifethailand.tv WP-JSON 品牌/车型注册报告
口径: ยอดจดทะเบียน (DLT 注册量)。数据来自 tag 5316 系列:
  - 全品牌季度报告: car-register-brands-thailand-qN-YYYY  (Top35 品牌)
  - 全品牌年度报告: car-register-thailand-YYYY-overall
  - 全品牌前三季:   all-brands-register-3quarters-YYYY
  - EV 月度报告:     ev-bev-register-thailand-{month}-YYYY (车型级 Top30, energy=BEV)
"""
import re
import time
import sys
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

TH_BASE = 'https://autolifethailand.tv'
TH_API = 'https://autolifethailand.tv/wp-json/wp/v2/posts'

# 英文月份词(全称+缩写, 用于 slug 解析) -> 月份数字
EN_MONTHS = {
    'january': 1, 'jan': 1, 'february': 2, 'feb': 2, 'march': 3, 'mar': 3,
    'april': 4, 'apr': 4, 'may': 5, 'june': 6, 'jun': 6, 'july': 7, 'jul': 7,
    'august': 8, 'aug': 8, 'september': 9, 'sep': 9, 'sept': 9, 'october': 10,
    'oct': 10, 'november': 11, 'nov': 11, 'december': 12, 'dec': 12,
}


class ThCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('autolifethailand_tv', 'TH')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en,th;q=0.9,en-US;q=0.8',
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

    def discover_all_reports(self):
        """tags=5316(ยอดจดทะเบียน) 遍历全部报告, 分类。
        返回 dict: {'quarter': {(y,q):slug}, 'annual': {y:slug}, 'q3': {y:slug}, 'ev': {(y,m):slug}}
        """
        out = {'quarter': {}, 'annual': {}, 'q3': {}, 'ev': {}}
        pat_q = re.compile(r'car-register-brands-thailand-q([1-4])-(\d{4})')
        pat_annual = re.compile(r'car-register-thailand-(\d{4})-overall')
        pat_q3 = re.compile(r'all-brands-register-3quarters-(\d{4})')
        pat_ev = re.compile(r'(?:ev-bev-register|ev-register|register-ev-bev)[^/]*(?:-(\d{4}))?')
        # EV slug 月份: 前缀(可选月份词) + 年份, 如 ev-bev-register-thailand-july-2026
        pat_ev_ym = re.compile(r'(?:ev-bev-register|ev-register|register-ev-bev).*?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*-(\d{4})')

        for page in range(1, 20):
            url = f'{TH_API}?tags=5316&per_page=100&page={page}'
            data = self._fetch_json(url)
            if not data or len(data) == 0:
                break
            for p in data:
                slug = p.get('slug', '')
                m = pat_q.search(slug)
                if m:
                    q, y = int(m.group(1)), int(m.group(2))
                    out['quarter'][(y, q)] = slug
                    continue
                m = pat_annual.search(slug)
                if m:
                    out['annual'][int(m.group(1))] = slug
                    continue
                m = pat_q3.search(slug)
                if m:
                    out['q3'][int(m.group(1))] = slug
                    continue
                m = pat_ev_ym.search(slug)
                if m:
                    mon = EN_MONTHS.get(m.group(1).lower())
                    y = int(m.group(2))
                    if mon and 2000 <= y <= 2030:
                        out['ev'][(y, mon)] = slug
                    continue
            if len(data) < 100:
                break
            time.sleep(0.6)
        return out

    def _fetch_post(self, slug):
        url = f'{TH_API}?slug={slug}'
        data = self._fetch_json(url)
        if data and len(data) > 0:
            return data[0]
        return None

    def _lines(self, post):
        content = post.get('content', {}).get('rendered', '')
        txt = re.sub(r'<[^>]+>', '\n', content)
        txt = re.sub(r'&[a-z]+;', ' ', txt)
        return [l.strip() for l in txt.split('\n') if l.strip()]

    def parse_brand_report(self, post):
        """品牌级报告, 返回 [(brand, qty)] 和 total"""
        if not post:
            return [], None
        lines = self._lines(post)
        txt = '\n'.join(lines)
        total = None
        m = re.search(r'รวม\s+([\d,\.]+)\s*คัน', txt)
        if m:
            total = int(m.group(1).replace(',', '').replace('.', ''))
        brands = []
        for ln in lines:
            m = re.match(r'^([A-Za-z0-9\s\-\.&]+?)\s{1,3}([\d,\.]+)\s*คัน$', ln)
            if m:
                brand = m.group(1).strip()
                try:
                    qty = int(m.group(2).replace(',', '').replace('.', ''))
                except ValueError:
                    continue
                if brand.upper().startswith('OTHERS') or brand.upper() in ('TOTAL', 'TOTALS'):
                    continue
                brands.append((brand, qty))
        return brands, total

    def parse_ev_report(self, post):
        """EV 月度报告(车型级 Top30), 返回 [(brand, model, qty)] 和 total。
        品牌=车型名首词; energy_type 固定 'BEV'。
        支持两种格式:
          单行: อันดับ 1 BYD Dolphin 2,825 คัน
          双行(2022旧): อันดับ 1 ORA Good Cat  /  : 2,083 คัน
        """
        if not post:
            return [], None
        lines = self._lines(post)
        txt = '\n'.join(lines)
        total = None
        m = re.search(r'รวม\s+([\d,\.]+)\s*คัน', txt)
        if m:
            total = int(m.group(1).replace(',', '').replace('.', ''))
        items = []
        # 归一 \xa0 -> 空格
        norm = [ln.replace('\xa0', ' ').strip() for ln in lines]
        i = 0
        n = len(norm)
        while i < n:
            ln = norm[i]
            # 排名标记: อันดับ N ... 或 纯数字 "1 BYD Dolphin ..."
            rest = None
            m = re.match(r'^อันดับ\s*(\d+)\s*[:\.]?\s*(.*)$', ln)
            if m:
                rest = m.group(2).strip()
            else:
                m = re.match(r'^(\d{1,2})[\.\)]?\s+(.+)$', ln)
                if m:
                    rest = m.group(2).strip()
            if rest is None:
                i += 1
                continue
            # 单行: rest = "车型 数量 คัน"
            m_single = re.match(r'^(.+?)\s+([\d,\.]+)\s*คัน\s*$', rest)
            if m_single:
                model = m_single.group(1).strip()
                try:
                    qty = int(m_single.group(2).replace(',', '').replace('.', ''))
                except ValueError:
                    i += 1
                    continue
                if not model.upper().startswith('OTHERS'):
                    brand = model.split()[0] if model.split() else model
                    items.append((brand, model, qty))
                i += 1
                continue
            # 双行(2022旧): 本行只有车型, 下一行 ": N คัน"
            if rest and not re.search(r'[\d,\.]+\s*คัน', rest):
                model = rest.strip()
                if i + 1 < n:
                    m_qty = re.match(r'^[:\.\s]*([\d,\.]+)\s*คัน', norm[i + 1])
                    if m_qty:
                        try:
                            qty = int(m_qty.group(1).replace(',', '').replace('.', ''))
                        except ValueError:
                            i += 1
                            continue
                        if not model.upper().startswith('OTHERS'):
                            brand = model.split()[0] if model.split() else model
                            items.append((brand, model, qty))
                        i += 2
                        continue
            i += 1
        return items, total

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

    def crawl_report(self, slug, source_month, energy_type=None, model_level=False, notes=''):
        post = self._fetch_post(slug)
        if not post:
            return 0
        if model_level:
            items, total = self.parse_ev_report(post)
            for brand, model, qty in items:
                rec = {
                    'country_code': 'TH',
                    'source_month': source_month,
                    'brand_name_raw': brand,
                    'brand_id': None,
                    'model_name': model,
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
                    'data_source': 'autolifethailand_tv',
                    'notes': notes,
                }
                self.save_sales(rec)
            return len(items)
        else:
            brands, total = self.parse_brand_report(post)
            for brand, qty in brands:
                rec = {
                    'country_code': 'TH',
                    'source_month': source_month,
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
                    'data_source': 'autolifethailand_tv',
                    'notes': notes,
                }
                self.save_sales(rec)
            return len(brands)

    def crawl_all(self, start_year=2022, end_year=2027):
        """全量: 全品牌季度/年度/前三季 + EV 月度"""
        reports = self.discover_all_reports()
        results = {'quarter': {}, 'annual': {}, 'q3': {}, 'ev': {}}
        for (y, q), slug in sorted(reports['quarter'].items()):
            if y < start_year or y > end_year:
                continue
            month = (q - 1) * 3 + 1
            n = self.crawl_report(slug, date(y, month, 1), notes=f'TH autolife Q{q} {y} brand registration (quarterly, source_month=quarter start)')
            results['quarter'][f'{y}Q{q}'] = n
            print(f'Q{q}/{y}: {n}')
            time.sleep(1)
        for y, slug in sorted(reports['annual'].items()):
            if y < start_year or y > end_year:
                continue
            n = self.crawl_report(slug, date(y, 12, 1), notes=f'TH autolife {y} full-year brand registration (source_month=Dec)')
            results['annual'][y] = n
            print(f'annual {y}: {n}')
            time.sleep(1)
        for y, slug in sorted(reports['q3'].items()):
            if y < start_year or y > end_year:
                continue
            n = self.crawl_report(slug, date(y, 9, 1), notes=f'TH autolife {y} first-3-quarters brand registration (source_month=Sep)')
            results['q3'][y] = n
            print(f'q3 {y}: {n}')
            time.sleep(1)
        for (y, m), slug in sorted(reports['ev'].items()):
            if y < start_year or y > end_year:
                continue
            n = self.crawl_report(slug, date(y, m, 1), energy_type='BEV', model_level=True,
                                  notes=f'TH autolife EV BEV monthly registration {y}-{m:02d} (model level)')
            results['ev'][f'{y}-{m:02d}'] = n
            print(f'EV {y}-{m:02d}: {n}')
            time.sleep(1)
        return results

    def crawl_incremental(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='TH'")
        row = cur.fetchone()
        max_m = row['m'] if isinstance(row, dict) else row[0]
        reports = self.discover_all_reports()
        saved = 0
        for (y, q), slug in sorted(reports['quarter'].items()):
            sm = date(y, (q - 1) * 3 + 1, 1)
            if max_m is None or sm > max_m:
                saved += self.crawl_report(slug, sm, notes=f'TH autolife Q{q} {y} brand registration')
        for y, slug in sorted(reports['annual'].items()):
            sm = date(y, 12, 1)
            if max_m is None or sm > max_m:
                saved += self.crawl_report(slug, sm, notes=f'TH autolife {y} annual brand registration')
        for (y, m), slug in sorted(reports['ev'].items()):
            sm = date(y, m, 1)
            if max_m is None or sm > max_m:
                saved += self.crawl_report(slug, sm, energy_type='BEV', model_level=True,
                                           notes=f'TH autolife EV monthly {y}-{m:02d}')
        return saved


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--incremental', action='store_true')
    ap.add_argument('--full', action='store_true')
    ap.add_argument('--y1', type=int, default=2022)
    ap.add_argument('--y2', type=int, default=2027)
    args = ap.parse_args()

    c = ThCrawler()
    if args.incremental:
        n = c.crawl_incremental()
        print(f'TH incremental saved: {n}')
    elif args.full:
        res = c.crawl_all(args.y1, args.y2)
        print('TH full done', res)
    else:
        reports = c.discover_all_reports()
        print('quarter:', len(reports['quarter']))
        print('annual:', len(reports['annual']))
        print('q3:', len(reports['q3']))
        print('ev:', len(reports['ev']))


if __name__ == '__main__':
    main()
