# -*- coding: utf-8 -*-
"""UN Comtrade 全球汽车进出口爬虫 (HS 8703 乘用车, 月度)
端点: https://comtradeapi.un.org/public/v1/preview/C/M/HS
免费 preview 无需 key。用父码 8703 避开 500 行上限。
写入 market_vehicle_trade_monthly (trade_type=import/export, new_used=all)。
"""
import io
import re
import sys
import time
import json
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

CT_BASE = 'https://comtradeapi.un.org/public/v1/preview/C/M/HS'
CT_GETDA = 'https://comtradeapi.un.org/public/v1/getDA/C/M/HS'
CT_REF = 'https://comtradeapi.un.org/files/v1/app/reference/'

# 目标国家(与 market_sales_monthly 已覆盖国家 + 主要贸易国)
TARGET_COUNTRIES = {
    'AT': 40, 'AU': 36, 'BE': 56, 'BR': 76, 'CA': 124, 'CH': 757, 'CL': 152,
    'CZ': 203, 'DE': 276, 'DK': 208, 'ES': 724, 'FI': 246, 'FR': 251, 'GB': 826,
    'GR': 300, 'HU': 348, 'IE': 372, 'IT': 381, 'JP': 392, 'KR': 410, 'MX': 484,
    'MY': 458, 'NL': 528, 'NO': 578, 'PL': 616, 'PT': 620, 'RO': 642, 'RU': 643,
    'SE': 752, 'SK': 703, 'TH': 764, 'TR': 792, 'UA': 804, 'US': 842, 'VN': 704,
    'AR': 32, 'IN': 699, 'ZA': 710, 'NZ': 554, 'ID': 360, 'SA': 682, 'AE': 784,
    'EG': 818, 'MA': 504, 'NG': 566, 'KE': 404, 'KZ': 398, 'IR': 364,
}


class ComtradeCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('un_comtrade_8703', None)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36',
        })
        self._reporters = None
        self._partners = None

    def _get_json(self, url, timeout=60):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 429:
                    time.sleep(30)
                    continue
            except Exception as e:
                print(f'_get_json {url[:100]} err: {e}')
            time.sleep(2)
        return None

    def _load_ref(self, name):
        data = self._get_json(CT_REF + name + '.json')
        if data and 'results' in data:
            return {int(r['id']): r['text'] for r in data['results']}
        return {}

    def _partner_name(self, code):
        if self._partners is None:
            self._partners = self._load_ref('partnerAreas')
        if self._partners is None:
            return str(code)
        return self._partners.get(int(code), str(code))

    def data_available(self, year, month, reporter_code):
        """getDA 门控: 该月数据是否已发布"""
        url = f'{CT_GETDA}?period={year}{month:02d}&reporterCode={reporter_code}&cmdCode=8703'
        data = self._get_json(url)
        if not data:
            return False
        for row in data.get('data', []):
            if row.get('dataAvailable'):
                return True
        return False

    def fetch_flow(self, year, month, reporter_code, flow):
        """拉取某国某月某方向 8703 partner 维度数据。返回 [(partner_code, partner_name, qty, value_usd)]"""
        url = (f'{CT_BASE}?period={year}{month:02d}&reporterCode={reporter_code}'
               f'&cmdCode=8703&flowCode={flow}')
        data = self._get_json(url)
        if not data:
            return []
        out = []
        for row in data.get('data', []):
            p = row.get('partnerCode')
            if p is None or p == 0:  # 0=World 汇总行
                continue
            qty = row.get('qty') or 0
            val = row.get('primaryValue') or 0
            out.append((p, self._partner_name(p), int(qty), float(val)))
        return out

    def crawl_month(self, year, month, countries=None):
        """爬某月全部目标国进出口, 写入 trade 表。返回 {'records': n, 'countries': n}"""
        countries = countries or TARGET_COUNTRIES
        total = 0
        done_c = 0
        conn, cur = self.get_connection()
        # 缓存已存在组合 (country, month, trade_type, partner, new_used)
        cur.execute("""
            SELECT DISTINCT country_code, trade_type, partner_country
            FROM market_vehicle_trade_monthly
            WHERE source_month=%s AND data_source='un_comtrade_8703'
        """, (date(year, month, 1),))
        existing = {(r['country_code'], r['trade_type'], r['partner_country']) for r in cur.fetchall()}

        for cc, code in countries.items():
            ok = False
            for flow, tt in (('M', 'import'), ('X', 'export')):
                rows = self.fetch_flow(year, month, code, flow)
                n = 0
                for pcode, pname, qty, val in rows:
                    key = (cc, tt, pname)
                    if key in existing:
                        continue
                    rec = {
                        'country_code': cc,
                        'source_month': date(year, month, 1),
                        'trade_type': tt,
                        'partner_country': pname,
                        'hs_code': '8703',
                        'new_used': 'all',
                        'vehicle_type': 'passenger',
                        'energy_type': None,
                        'quantity': qty if qty else None,
                        'value_usd': val if val else None,
                        'data_source': 'un_comtrade_8703',
                        'notes': f'UN Comtrade HS8703 {year}-{month} {tt} (all new/used)',
                    }
                    self._insert_trade(conn, cur, rec)
                    existing.add(key)
                    n += 1
                total += n
                if rows:
                    ok = True
            if ok:
                done_c += 1
            time.sleep(0.5)
        conn.commit()
        return {'records': total, 'countries': done_c}

    def _insert_trade(self, conn, cur, rec):
        cur.execute("""
            INSERT INTO market_vehicle_trade_monthly
                (country_code, source_month, trade_type, partner_country, hs_code,
                 new_used, vehicle_type, energy_type, quantity, value_usd,
                 data_source, notes, crawl_time)
            VALUES (%(country_code)s, %(source_month)s, %(trade_type)s, %(partner_country)s,
                 %(hs_code)s, %(new_used)s, %(vehicle_type)s, %(energy_type)s,
                 %(quantity)s, %(value_usd)s, %(data_source)s, %(notes)s, %(crawl_time)s)
            ON CONFLICT DO NOTHING
        """, {**rec, 'crawl_time': datetime.now()})

    def crawl_incremental(self, back_months=6):
        """探测最近月份(目标国已发布), 增量拉取。返回 {'records': n}"""
        today = date.today()
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_vehicle_trade_monthly WHERE data_source='un_comtrade_8703'")
        row = cur.fetchone()
        max_m = (row['m'] if isinstance(row, dict) else row[0])
        if max_m is None:
            max_m = date(today.year - 1, 1, 1)
        total = 0
        # 从 max_m+1 到 today-2月 逐个尝试(数据滞后1-2月)
        ym = date(max_m.year, max_m.month, 1)
        target = date(today.year, today.month, 1)
        while ym < target:
            ny, nm = (ym.year + 1, 1) if ym.month == 12 else (ym.year, ym.month + 1)
            ym = date(ny, nm, 1)
            res = self.crawl_month(ym.year, ym.month)
            total += res['records']
            if res['countries'] == 0:
                break  # 最新月无数据, 不再前进
        return {'records': total}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--ym', type=str, default='', help='指定月 2024-12')
    ap.add_argument('--incremental', action='store_true')
    args = ap.parse_args()
    c = ComtradeCrawler()
    if args.ym:
        y, m = map(int, args.ym.split('-'))
        print(c.crawl_month(y, m))
    elif args.incremental:
        print(c.crawl_incremental())
    else:
        print('USAGE: --ym 2024-12 | --incremental')


if __name__ == '__main__':
    main()
