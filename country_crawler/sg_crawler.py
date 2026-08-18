# -*- coding: utf-8 -*-
"""
新加坡 SG 汽车销量爬虫
数据源：LTA data.gov.sg 数据集（新车注册 by make）
说明：品牌级月度注册量，含燃料维度（BEV/HEV/PHEV），数据滞后约14个月
"""
import os
import sys
import re
import time
from datetime import datetime, date
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_crawler import BaseCrawler

RESOURCE_ID = 'd_d3f4d708e1d0a37b4365414e2fad3a07'
BASE = 'https://data.gov.sg/api/action/datastore_search'
API_URL = f'{BASE}?resource_id={RESOURCE_ID}'

# 燃料类型 -> energy_type（只有新能源细分；燃油合并为 None）
FUEL_MAP = {
    'Electric': 'BEV',
    'Petrol-Electric': 'HEV',
    'Petrol-Electric (Plug-In)': 'PHEV',
    'Diesel-Electric': 'HEV',
    'Diesel-Electric (Plug-In)': 'PHEV',
}


class SGCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('sg_lta_registration', 'SG')
        self.api_url = API_URL

    def get_headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
        }

    def _clean_int(self, s):
        if s is None:
            return 0
        digits = re.sub(r'[^\d]', '', str(s))
        return int(digits) if digits else 0

    def fetch_all(self):
        """分页拉取全量，返回 {month: {'brand': total, 'BEV': {...}, 'HEV': {...}, 'PHEV': {...}}}
        带重试，遇到502等服务器错误时等待后重试"""
        data = {}
        offset = 0
        while True:
            url = f'{self.api_url}&limit=1000&offset={offset}'
            for attempt in range(3):
                try:
                    r = requests.get(url, headers=self.get_headers(), timeout=30)
                    r.raise_for_status()
                    recs = r.json().get('result', {}).get('records', [])
                    break
                except Exception as e:
                    self.logger.warning(f'拉取 offset={offset} 失败（{attempt+1}/3）：{e}')
                    if attempt == 2:
                        raise
                    time.sleep(3)
            if not recs:
                break
            for x in recs:
                month = x.get('month')
                make = (x.get('make') or '').strip().upper()
                if not month or not make:
                    continue
                qty = self._clean_int(x.get('number'))
                d = data.setdefault(month, {})
                d['brand'] = d.get('brand', {})
                d['brand'][make] = d['brand'].get(make, 0) + qty
                ft = x.get('fuel_type')
                en = FUEL_MAP.get(ft) if ft else None
                if en:
                    d.setdefault(en, {})
                    d[en][make] = d[en].get(make, 0) + qty
            offset += len(recs)
            if offset % 10000 == 0:
                self.logger.info(f'已拉取 {offset} 条')
            if offset >= 51669:
                break
        return data

    def _make_record(self, sm, brand, qty, energy_type, notes):
        return {
            'country_code': 'SG',
            'source_month': sm,
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
            'data_source': 'sg_lta_registration',
            'notes': notes,
        }

    def _bulk_save_records(self, records):
        """单事务批量保存：先查已存在(brand,energy)组合，只插入不存在的"""
        if not records:
            return 0
        conn, cur = self.get_connection()
        try:
            # 已存在的组合
            existing = set()
            cur.execute("""
                SELECT brand_name_raw, energy_type FROM market_sales_monthly
                WHERE country_code = %s AND source_month = %s AND model_name IS NULL
            """, (records[0]['country_code'], records[0]['source_month']))
            for r in cur.fetchall():
                existing.add((r['brand_name_raw'], r['energy_type']))
            to_insert = [rec for rec in records if (rec['brand_name_raw'], rec['energy_type']) not in existing]
            if to_insert:
                cur.executemany("""
                    INSERT INTO market_sales_monthly
                        (country_code, source_month, brand_name_raw, brand_id,
                         model_name, vehicle_type, energy_type, segment,
                         raw_unit, sales_volume_raw, sales_volume_normalized,
                         revision_no, is_latest, pub_date, crawl_time,
                         data_source, notes)
                    VALUES
                        (%(country_code)s, %(source_month)s, %(brand_name_raw)s, %(brand_id)s,
                         %(model_name)s, %(vehicle_type)s, %(energy_type)s, %(segment)s,
                         %(raw_unit)s, %(sales_volume_raw)s, %(sales_volume_normalized)s,
                         %(revision_no)s, %(is_latest)s, %(pub_date)s, %(crawl_time)s,
                         %(data_source)s, %(notes)s)
                """, to_insert)
            conn.commit()
            return len(to_insert)
        except Exception as e:
            conn.rollback()
            self.logger.error(f'批量保存失败: {e}')
            return 0

    def crawl_month(self, year, month, d):
        """入库单月聚合数据。d = {brand: {...}, 'BEV': {...}, ...}"""
        sm = date(year, month, 1)
        records = []
        brands = d.get('brand', {})
        for brand, qty in sorted(brands.items()):
            notes = 'LTA新车注册量(品牌级,含AMD+PI)'
            records.append(self._make_record(sm, brand, qty, None, notes))
        for en in ('BEV', 'HEV', 'PHEV'):
            for brand, qty in d.get(en, {}).items():
                if qty <= 0:
                    continue
                notes = f'LTA新车注册量; {en}'
                records.append(self._make_record(sm, brand, qty, en, notes))
        n = self._bulk_save_records(records)
        return {'records': n, 'brands': len(brands)}

    def crawl_all(self):
        data = self.fetch_all()
        self.logger.info(f'拉取完成，{len(data)} 个月份')
        saved = 0
        for month in sorted(data.keys()):
            y, m = map(int, month.split('-'))
            res = self.crawl_month(y, m, data[month])
            saved += res['records']
        return {'records': saved, 'months': len(data)}

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='SG'")
        row = cur.fetchone()
        m = row['m'] if isinstance(row, dict) else row[0]
        return m.date() if hasattr(m, 'date') else m

    def crawl_incremental(self):
        max_m = self._get_db_max_month()
        data = self.fetch_all()
        saved = 0
        for month in sorted(data.keys()):
            y, m = map(int, month.split('-'))
            sm = date(y, m, 1)
            if max_m is not None and sm <= max_m:
                continue
            res = self.crawl_month(y, m, data[month])
            saved += res['records']
        return {'records': saved, 'months': len(data)}


if __name__ == '__main__':
    c = SGCrawler()
    try:
        res = c.crawl_incremental()
        print(f'完成，保存 {res["records"]} 条记录，{res["months"]} 个月份')
    finally:
        c.close()