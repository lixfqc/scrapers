# -*- coding: utf-8 -*-
"""哈萨克斯坦 KZ 爬虫: kao.kz (КАО 哈萨克斯坦汽车联盟) 月度品牌级销量
口径: 官方经销商渠道 (新轻型+轻型商用车), 不含灰色进口。
URL: https://kao.kz/ru/novosti/{id}/ (id=96→1 连续归档, 2026-07→2023-11)
HTML <table> 品牌级矩阵: col0=品牌/col1=当月去年/col2=当月今年(当月销量)/col3=同比%/col4-6=YTD
"""
import re
import io
import time
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

KZ_BASE = 'https://kao.kz/ru/novosti'

# 俄语月份词 → 月份 (表格 row0)
KZ_MONTHS = {
    'ЯНВАРЬ': 1, 'ФЕВРАЛЬ': 2, 'МАРТ': 3, 'АПРЕЛЬ': 4, 'МАЙ': 5, 'ИЮНЬ': 6,
    'ИЮЛЬ': 7, 'АВГУСТ': 8, 'СЕНТЯБРЬ': 9, 'ОКТЯБРЬ': 10, 'НОЯБРЬ': 11, 'ДЕКАБРЬ': 12,
}
KZ_SKIP = ('ИТОГО', 'ВСЕГО', 'ТОТАЛ', 'TOTAL', 'МАРКА', 'BRAND', 'ОБЩИЙ ИТОГ', 'ОБЩИЙ', 'ДРУГИЕ', 'ДРУГИ')


class KzCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('kz_kao_monthly_brand', 'KZ')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'ru,en;q=0.9',
        })
        self._brand_cache = {}

    def _fetch(self, url, timeout=30):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r
            except Exception as e:
                print(f'_fetch {url} err: {e}')
            time.sleep(2)
        return None

    def _to_int(self, s):
        try:
            return int(str(s).replace(' ', '').replace('\u00a0', '').replace(',', '').replace('.', ''))
        except ValueError:
            return None

    def discover_month_ids(self, max_id=120):
        """从最新(id 最大)往回找可用的月度报告 id。
        返回 {id: (year, month)}。实际最新 id 通过连续探测确定。"""
        found = {}
        # 先探测最新 id: 从大往小, 找第一个 200 且有品牌表的
        for i in range(max_id, 0, -1):
            r = self._fetch(f'{KZ_BASE}/{i}/')
            if not r:
                continue
            ym = self.parse_ym(r.text)
            if ym:
                found[i] = ym
                break
        latest = i if found else 0
        # 从 latest 往下连续收集
        for i in range(latest - 1, 0, -1):
            r = self._fetch(f'{KZ_BASE}/{i}/')
            if not r:
                continue
            ym = self.parse_ym(r.text)
            if ym:
                found[i] = ym
            time.sleep(0.5)
        return found

    def parse_ym(self, html):
        """从表格 row0 提取 (year, month)。"""
        tables = re.findall(r'<table[^>]*>.*?</table>', html, re.S | re.I)
        if not tables:
            return None
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tables[0], re.S | re.I)
        month = None
        year = None
        for row in rows[:4]:
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S | re.I)
            clean = [re.sub(r'<[^>]+>', '', c).replace('&nbsp;', '').strip() for c in cells]
            # row0: [&nbsp;, ИЮЛЬ, ЯНВАРЬ-ИЮЛЬ] -> 月份词
            for c in clean:
                for k in KZ_MONTHS:
                    if c.upper() == k:
                        month = KZ_MONTHS[k]
                        break
                if month:
                    break
            # row1: [2025, 2026, %, 2025, 2026, %] -> col2 是今年
            ys = [int(c) for c in clean if re.fullmatch(r'20\d\d', c)]
            if ys:
                year = ys[0] + 1  # col1 去年, col2 今年
                break
        if month is None or year is None:
            return None
        return (year, month)

    def parse_brand_table(self, html):
        """解析品牌级矩阵 table。返回 [(brand, month_qty), ...]"""
        tables = re.findall(r'<table[^>]*>.*?</table>', html, re.S | re.I)
        if not tables:
            return []
        brands = []
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tables[0], re.S | re.I)
        for row in rows:
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S | re.I)
            clean = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if len(clean) < 3:
                continue
            brand = clean[0].replace('&nbsp;', '').strip()
            if not brand or brand.upper() in KZ_SKIP or brand.upper().startswith(('ИТОГО', 'ВСЕГО', 'МАРКА')):
                continue
            # col1=当月去年, col2=当月今年(当月销量)
            qty = self._to_int(clean[2])
            if qty is None or qty <= 0:
                continue
            brands.append((brand, qty))
        return brands

    def get_brand_id(self, brand_raw):
        b = str(brand_raw).strip().upper()
        if b in self._brand_cache:
            return self._brand_cache[b]
        bid = None
        conn, cur = self.get_connection()
        cur.execute("SELECT id FROM brand_name_mapping WHERE UPPER(canonical_name)=%s OR UPPER(brand_name_cn)=%s ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, id LIMIT 1", (b, b))
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

    def crawl_id(self, rid):
        """爬指定 id, 返回 {'records': n, 'ym': (y,m)}"""
        r = self._fetch(f'{KZ_BASE}/{rid}/')
        if not r:
            return {'records': 0, 'ym': None}
        ym = self.parse_ym(r.text)
        if not ym:
            return {'records': 0, 'ym': None}
        y, m = ym
        brands = self.parse_brand_table(r.text)
        n = 0
        for brand, qty in brands:
            rec = {
                'country_code': 'KZ',
                'source_month': date(y, m, 1),
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
                'data_source': 'kz_kao_monthly_brand',
                'notes': 'KZ KAO monthly brand sales (official dealer channel, excl grey import)',
            }
            self.save_sales(rec)
            n += 1
        return {'records': n, 'ym': ym}

    def crawl_incremental(self):
        ids = self.discover_month_ids()
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='KZ'")
        row = cur.fetchone()
        max_m = row['m'] if isinstance(row, dict) else row[0]
        if hasattr(max_m, 'date'):
            max_m = max_m.date()
        saved = 0
        for rid, (y, m) in sorted(ids.items(), key=lambda x: x[1]):
            sm = date(y, m, 1)
            if max_m is not None and sm <= max_m:
                continue
            res = self.crawl_id(rid)
            saved += res['records']
        return saved

    def crawl_range(self, y1, m1, y2, m2):
        ids = self.discover_month_ids()
        results = {}
        for rid, (y, m) in ids.items():
            if (y, m) < (y1, m1) or (y, m) > (y2, m2):
                continue
            res = self.crawl_id(rid)
            results[f'{y}-{m:02d}'] = res
            print(f'{y}-{m:02d}: {res}')
            time.sleep(0.8)
        return results


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--incremental', action='store_true')
    ap.add_argument('--test', action='store_true')
    ap.add_argument('--y1', type=int, default=2023)
    ap.add_argument('--m1', type=int, default=11)
    ap.add_argument('--y2', type=int, default=2026)
    ap.add_argument('--m2', type=int, default=7)
    args = ap.parse_args()

    c = KzCrawler()
    if args.test:
        ids = c.discover_month_ids()
        print('months found:', len(ids))
        for rid in sorted(ids, reverse=True)[:5]:
            res = c.crawl_id(rid)
            print(f'id {rid} -> {res["ym"]}: {res["records"]}')
    elif args.incremental:
        n = c.crawl_incremental()
        print(f'KZ incremental saved: {n}')
    else:
        res = c.crawl_range(args.y1, args.m1, args.y2, args.m2)
        print('KZ range done')


if __name__ == '__main__':
    main()
