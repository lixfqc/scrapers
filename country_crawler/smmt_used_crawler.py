# -*- coding: utf-8 -*-
"""英国 GB 二手车爬虫: SMMT Used Car Sales (DVLA 转让) 月度总量
页面: https://www.smmt.co.uk/vehicle-data/used-car-sales/
Table: 'Used Car Transactions for United Kingdom' Year|Jan..Dec|Total
"""
import re
import time
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

GB_USE_URL = 'https://www.smmt.co.uk/vehicle-data/used-car-sales/'
GB_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


class SmmtUsedCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('smmt_gb_used_car_transactions_monthly', 'GB')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        })

    def _fetch(self, url, timeout=40):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r.text
            except Exception as e:
                print(f'_fetch {url} err: {e}')
            time.sleep(2)
        return None

    def _to_int(self, s):
        try:
            return int(str(s).replace(',', '').strip())
        except Exception:
            return None

    def parse_monthly_table(self, html):
        """解析 'Used Car Transactions for United Kingdom' 月度表。
        返回 {(year, month): qty}。"""
        data = {}
        # 遍历所有 table, 找含标题 'Used Car Transactions' 的那个
        tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.S)
        for tab in tables:
            if 'Used Car Transactions for United Kingdom' not in tab:
                continue
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tab, re.S)
            for row in rows:
                cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S)
                cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                if not cells:
                    continue
                ym = re.match(r'^(\d{4})$', cells[0])
                if not ym:
                    continue
                year = int(ym.group(1))
                for i, mname in enumerate(GB_MONTHS):
                    if i + 1 < len(cells):
                        qty = self._to_int(cells[i + 1])
                        if qty is not None:
                            data[(year, i + 1)] = qty
            break
        return data

    def save_used(self, y, m, qty):
        """写 market_used_vehicle_monthly (行业总量行, brand='ALL')."""
        conn, cur = self.get_connection()
        cur.execute("""
            INSERT INTO market_used_vehicle_monthly
                (country_code, source_month, brand_name_raw, brand_id, vehicle_type,
                 used_volume, used_import_volume, data_source, notes, crawl_time, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (country_code, source_month, brand_name_raw, vehicle_type, data_source)
            DO UPDATE SET used_volume = EXCLUDED.used_volume,
                          crawl_time = EXCLUDED.crawl_time
        """, ('GB', date(y, m, 1), 'ALL', None, 'passenger',
              qty, None, 'smmt_gb_used_car_transactions_monthly',
              f'GB SMMT used car transactions (DVLA) {y}-{m:02d}', datetime.now()))
        conn.commit()

    def crawl_month(self, year, month):
        html = self._fetch(GB_USE_URL)
        if not html:
            return {'records': 0}
        data = self.parse_monthly_table(html)
        qty = data.get((year, month))
        if qty is None:
            return {'records': 0}
        self.save_used(year, month, qty)
        return {'records': 1}

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_used_vehicle_monthly WHERE country_code='GB'")
        row = cur.fetchone()
        m = row['m'] if isinstance(row, dict) else row[0]
        return m.date() if hasattr(m, 'date') else m

    def crawl_incremental(self):
        max_m = self._get_db_max_month()
        html = self._fetch(GB_USE_URL)
        if not html:
            return 0
        data = self.parse_monthly_table(html)
        saved = 0
        for (y, m) in sorted(data.keys()):
            sm = date(y, m, 1)
            if max_m is None or sm > max_m:
                self.save_used(y, m, data[(y, m)])
                saved += 1
        return saved

    def crawl_range(self, y1, m1, y2, m2):
        html = self._fetch(GB_USE_URL)
        if not html:
            return {}
        data = self.parse_monthly_table(html)
        results = {}
        for (y, m) in sorted(data.keys()):
            if (y, m) < (y1, m1) or (y, m) > (y2, m2):
                continue
            self.save_used(y, m, data[(y, m)])
            results[f'{y}-{m:02d}'] = data[(y, m)]
        return results


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--incremental', action='store_true')
    ap.add_argument('--y1', type=int, default=2020)
    ap.add_argument('--m1', type=int, default=1)
    ap.add_argument('--y2', type=int, default=2026)
    ap.add_argument('--m2', type=int, default=12)
    args = ap.parse_args()
    c = SmmtUsedCrawler()
    if args.incremental:
        n = c.crawl_incremental()
        print(f'GB used incremental saved: {n}')
    else:
        res = c.crawl_range(args.y1, args.m1, args.y2, args.m2)
        print(f'GB used range done: {len(res)} months')


if __name__ == '__main__':
    main()
