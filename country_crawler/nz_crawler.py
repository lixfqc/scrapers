# -*- coding: utf-8 -*-
"""新西兰 NZ 爬虫: NZTA Motor Vehicle Register (ArcGIS Hub MVR) 月度快照
口径: 首次注册(FIRST_NZ_REGISTRATION_YEAR/MONTH), 含新车/二手车(IMPORT_STATUS)与进口来源国(PREVIOUS_COUNTRY)。
注意: MVR 是时点存量快照, 重建的月度流漏计已注销/转卖车辆(与官方流量口径有偏差)。
"""
import re
import time
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

# MVR 月度快照 REST 服务 (每月更新, 版本名如 MVR_Mar26)
NZ_LAYER = 'https://services.arcgis.com/CXBb7LAjgIIdcsPt/arcgis/rest/services/MVR_{ver}/FeatureServer/0'
NZ_VER = 'Mar26'  # 当前快照版本(2026-03), 需定期更新

# 乘用车 CLASS 编码
NZ_PASSENGER_CLASS = ('MA',)


class NzCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('nzta_mvr_monthly_snapshot', 'NZ')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        self._brand_cache = {}

    def _query(self, where, group_by, timeout=120):
        """REST 聚合查询, 返回 features 列表"""
        url = NZ_LAYER.format(ver=NZ_VER) + '/query'
        params = {
            'where': where,
            'outFields': '*',
            'groupByFieldsForStatistics': group_by,
            'outStatistics': '[{"statisticType":"sum","onStatisticField":"1","outStatisticFieldName":"cnt"}]',
            'returnGeometry': 'false',
            'f': 'json',
        }
        r = self.session.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json().get('features', [])
        return []

    def fetch_month(self, year, month):
        """抓取指定月的注册流 (MA乘用车), 按 MAKE x IMPORT_STATUS x PREVIOUS_COUNTRY。
        返回 {brand: {status: qty}} 品牌级汇总 + 各品牌按状态计数。
        """
        features = self._query(
            f"FIRST_NZ_REGISTRATION_MONTH = {month} AND FIRST_NZ_REGISTRATION_YEAR = {year} "
            f"AND CLASS IN ('MA')",
            'MAKE,IMPORT_STATUS,PREVIOUS_COUNTRY')
        agg = {}  # brand -> {status: total}
        for f in features:
            a = f['attributes']
            make = (a.get('MAKE') or 'UNKNOWN').strip().upper()
            status = (a.get('IMPORT_STATUS') or 'UNKNOWN').strip()
            cnt = a.get('cnt') or 0
            d = agg.setdefault(make, {})
            d[status] = d.get(status, 0) + cnt
        return agg

    def _make_records(self, agg, year, month):
        """聚合结果 -> 记录列表。
        品牌级: 每品牌一条总记录 (NEW+USED 合计), notes 标注二手占比。
        另存二手来源国维度到 notes (主要来源国)。
        """
        records = []
        sm = date(year, month, 1)
        for brand in sorted(agg.keys()):
            statuses = agg[brand]
            total = sum(statuses.values())
            used = statuses.get('USED', 0)
            new = statuses.get('NEW', 0)
            notes = f'NZTA MVR {year}-{month:02d} MA registrations (NEW {new}/USED {used})'
            rec = {
                'country_code': 'NZ',
                'source_month': sm,
                'brand_name_raw': brand,
                'brand_id': None,
                'model_name': None,
                'vehicle_type': 'passenger',
                'energy_type': None,
                'segment': None,
                'raw_unit': 'units',
                'sales_volume_raw': total,
                'sales_volume_normalized': total,
                'revision_no': 1,
                'is_latest': True,
                'pub_date': None,
                'crawl_time': datetime.now(),
                'data_source': 'nzta_mvr_monthly_snapshot',
                'notes': notes,
            }
            records.append(rec)
        return records

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
        """爬指定月, 返回 {'records': n, 'total': t}"""
        agg = self.fetch_month(year, month)
        if not agg:
            return {'records': 0, 'total': None}
        records = self._make_records(agg, year, month)
        total = sum(r['sales_volume_normalized'] for r in records)
        for rec in records:
            self.save_sales(rec)
        return {'records': len(records), 'total': total}

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='NZ'")
        row = cur.fetchone()
        m = row['m'] if isinstance(row, dict) else row[0]
        return m.date() if hasattr(m, 'date') else m

    def crawl_incremental(self):
        max_m = self._get_db_max_month()
        # MVR 快照最新月
        latest = self._latest_available_month()
        saved = 0
        if latest and (max_m is None or latest > max_m):
            res = self.crawl_month(latest.year, latest.month)
            saved = res['records']
        return saved

    def _latest_available_month(self):
        """探测 MVR 快照中最新有数据的月份"""
        # 探测最近12个月(含当年+去年), 找第一个非空月
        today = date.today()
        for offset in range(0, 14):
            y = today.year
            m = today.month - offset
            while m <= 0:
                m += 12
                y -= 1
            if y < 2000:
                break
            agg = self.fetch_month(y, m)
            if agg:
                return date(y, m, 1)
        return None

    def crawl_range(self, y1, m1, y2, m2):
        results = {}
        for y in range(y1, y2 + 1):
            for m in range(1, 13):
                if (y, m) < (y1, m1) or (y, m) > (y2, m2):
                    continue
                res = self.crawl_month(y, m)
                results[f'{y}-{m:02d}'] = res
                print(f'{y}-{m:02d}: {res}')
                time.sleep(0.5)
        return results


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--incremental', action='store_true')
    ap.add_argument('--ym', type=str, default='', help='单月 2026-03')
    ap.add_argument('--y1', type=int, default=2020)
    ap.add_argument('--m1', type=int, default=1)
    ap.add_argument('--y2', type=int, default=2026)
    ap.add_argument('--m2', type=int, default=7)
    args = ap.parse_args()

    c = NzCrawler()
    if args.ym:
        y, m = map(int, args.ym.split('-'))
        print(c.crawl_month(y, m))
    elif args.incremental:
        n = c.crawl_incremental()
        print(f'NZ incremental saved: {n}')
    else:
        res = c.crawl_range(args.y1, args.m1, args.y2, args.m2)
        print('NZ range done')


if __name__ == '__main__':
    main()
