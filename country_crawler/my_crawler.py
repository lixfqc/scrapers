# -*- coding: utf-8 -*-
"""马来西亚 MY 月度汽车注册量爬虫。
数据源: paultan.org /car-sales-data (聚合自 data.gov.my JPJ 注册交易, 2000-至今)
口径: registration (注册量). 品牌级 group=maker, 车型级 group=model.
"""
import sys, os, io, re, time, random
import csv
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

MY_API = 'https://paultan.org/car-sales-data/api.php'

def _to_int(v):
    try:
        return int(str(v).replace(',', '').replace(' ', '').strip())
    except Exception:
        return None

class MyCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('paultan_org_car_sales_data_maker', 'MY')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': random.choice(UA_LIST),
            'Referer': 'https://paultan.org/car-sales-data/',
        })
        self._brand_id_cache = {}

    # ---------- 探测最新可用月 ----------
    def latest_available_month(self):
        """paultan 无列表页, 用当月(可能无数据)与上月探测; 返回 (y,m) 或 None."""
        today = date.today()
        for dy, dm in [(today.year, today.month), ]:
            pass
        # 当月和上月
        for offset in (0, 1):
            y = today.year
            m = today.month - offset
            if m <= 0:
                m += 12
                y -= 1
            data = self._fetch_month(y, m, 'maker')
            if data:
                return (y, m)
        return None

    def _fetch_month(self, year, month, group):
        """拉取指定年月品牌级(maker)或车型级(model)数据。
        返回: maker -> [(name, qty)]; model -> [(make, model, qty)].
        """
        url = (f'{MY_API}?action=rankings&group={group}&format=csv'
               f'&from={year}-{month:02d}&to={year}-{month:02d}')
        try:
            r = self.retry_request(self.session.get, url, timeout=30)
            if not r:
                return None
            if 'text/csv' not in r.headers.get('Content-Type', '') and not r.text.lstrip().startswith('rank'):
                return None
            rows = []
            reader = csv.reader(io.StringIO(r.text))
            header = None
            for ln in reader:
                if header is None:
                    header = [h.strip().lower() for h in ln]
                    if 'rank' not in header:
                        return None
                    continue
                parts = [p.strip() for p in ln]
                if not parts or parts[0] == '':
                    continue
                try:
                    int(parts[0])  # rank 必须数字
                except Exception:
                    continue
                # maker: rank,make,units,share_pct ; model: rank,make,model,units,share_pct
                if group == 'maker':
                    if len(parts) < 3:
                        continue
                    name, qty = parts[1], _to_int(parts[2])
                    if qty and qty > 0 and name.upper() not in ('TOTAL', 'OTHERS', 'OTHER'):
                        rows.append((name, qty))
                else:
                    if len(parts) < 4:
                        continue
                    make, model = parts[1], parts[2]
                    qty = _to_int(parts[3])
                    if qty and qty > 0 and make.upper() not in ('TOTAL', 'OTHERS', 'OTHER'):
                        rows.append((make, model, qty))
            return rows
        except Exception as e:
            print(f'fetch {year}-{month} {group} error: {e}')
            return None
        except Exception as e:
            print(f'fetch {year}-{month} {group} error: {e}')
            return None

    # ---------- 品牌匹配 ----------
    def get_brand_id(self, brand_raw):
        if brand_raw in self._brand_id_cache:
            return self._brand_id_cache[brand_raw]
        conn, cur = self.get_connection()
        try:
            u = brand_raw.upper().strip()
            cur.execute("""
                SELECT id FROM brand_name_mapping
                WHERE UPPER(canonical_name)=%s OR UPPER(brand_name_cn)=%s
                ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, id LIMIT 1
            """, (u, u))
            row = cur.fetchone()
            bid = row['id'] if row else None
            if not bid:
                cur.execute("SELECT brand_id FROM brand_name_variant WHERE UPPER(variant_name)=%s LIMIT 1", (u,))
                row = cur.fetchone()
                bid = row['brand_id'] if row else None
            self._brand_id_cache[brand_raw] = bid
            return bid
        finally:
            pass

    def save_sales(self, record):
        record['brand_id'] = self.get_brand_id(record['brand_name_raw'])
        super().save_sales(record)

    # ---------- 入库 ----------
    def crawl_month(self, year, month, include_model=True):
        rows = self._fetch_month(year, month, 'maker')
        if not rows:
            return {'records': 0}
        n = 0
        for name, qty in rows:
            rec = {
                'country_code': 'MY', 'source_month': date(year, month, 1),
                'brand_name_raw': name, 'model_name': None,
                'vehicle_type': 'passenger', 'energy_type': None,
                'segment': None, 'raw_unit': 'units',
                'sales_volume_raw': qty, 'sales_volume_normalized': qty,
                'revision_no': 1, 'is_latest': True, 'pub_date': None,
                'crawl_time': datetime.now(),
                'data_source': 'paultan_org_car_sales_data_maker',
                'notes': 'Paultan (data.gov.my JPJ) registration by maker',
            }
            self.save_sales(rec)
            n += 1
        # 车型级
        if include_model:
            mrows = self._fetch_month(year, month, 'model')
            if mrows:
                for make, model, qty in mrows:
                    rec = {
                        'country_code': 'MY', 'source_month': date(year, month, 1),
                        'brand_name_raw': make, 'model_name': model,
                        'vehicle_type': 'passenger', 'energy_type': None,
                        'segment': None, 'raw_unit': 'units',
                        'sales_volume_raw': qty, 'sales_volume_normalized': qty,
                        'revision_no': 1, 'is_latest': True, 'pub_date': None,
                        'crawl_time': datetime.now(),
                        'data_source': 'paultan_org_car_sales_data_model',
                        'notes': 'Paultan (data.gov.my JPJ) registration by model',
                    }
                    self.save_sales(rec)
                    n += 1
        return {'records': n}

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='MY'")
        row = cur.fetchone()
        m = row['m'] if row else None
        return m.date() if m and hasattr(m, 'date') else m

    def crawl_incremental(self):
        latest = self.latest_available_month()
        if not latest:
            return 0
        max_m = self._get_db_max_month()
        if max_m and date(latest[0], latest[1], 1) <= max_m:
            print(f'MY skip: latest {latest} <= DB max {max_m}')
            return 0
        res = self.crawl_month(latest[0], latest[1])
        return res.get('records', 0)

    def crawl_range(self, start_year, start_month, end_year, end_month):
        total = 0
        y, m = start_year, start_month
        while (y, m) <= (end_year, end_month):
            res = self.crawl_month(y, m)
            print(f'MY {y}-{m:02d}: {res}')
            total += res.get('records', 0)
            m += 1
            if m > 12:
                m = 1
                y += 1
            time.sleep(1)
        return total

if __name__ == '__main__':
    mode = 'incremental'
    if len(sys.argv) > 1:
        mode = sys.argv[1]
    c = MyCrawler()
    if mode == 'incremental':
        n = c.crawl_incremental()
        print(f'MY incremental saved: {n}')
    elif mode == 'test':
        print('latest:', c.latest_available_month())
    else:
        # 全量: python my_crawler.py full 2000 2026
        y1 = int(sys.argv[2]) if len(sys.argv) > 2 else 2024
        y2 = int(sys.argv[3]) if len(sys.argv) > 3 else 2026
        total = c.crawl_range(y1, 1, y2, 12)
        print(f'MY full {y1}-{y2} total: {total}')
