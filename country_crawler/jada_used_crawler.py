# -*- coding: utf-8 -*-
"""日本 JP 二手车爬虫: JADA 中古車登録台数（月度）
口径: 新規登録+所有権移転登録+使用者名変更登録 合算（注册手续数）
XLS 多sheet按月(YYYYMM), 每sheet '総合計' 行 = 全国中古车注册手续总数。
存 market_used_vehicle_monthly (brand='ALL' 行业总量)。
"""
import io
import re
import time
import requests
from datetime import datetime, date
import pandas as pd
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

JP_USE_PAGE = 'https://www.jada.or.jp/pages/114/'


class JadaUsedCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('jada_jp_used_car_registrations_monthly', 'JP')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        })

    def _fetch(self, url, timeout=60):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r
            except Exception:
                pass
            time.sleep(2)
        return None

    def discover_xls_url(self):
        """从页面找最新月度 XLS(当月+历史)。返回 [(ym_key, url), ...]"""
        r = self._fetch(JP_USE_PAGE)
        if not r:
            return []
        r.encoding = r.apparent_encoding
        links = []
        seen = set()
        for m in re.finditer(r'href="([^"]+\.(?:xls|xlsx))"', r.text):
            url = m.group(1)
            if not url.startswith('http'):
                url = 'https://www.jada.or.jp' + url
            if url in seen:
                continue
            seen.add(url)
            links.append(url)
        return links

    def parse_xls(self, content):
        """解析XLS, 返回 {(y,m): {'passenger': qty, 'total': qty}}"""
        xl = pd.ExcelFile(io.BytesIO(content))
        result = {}
        for sheet in xl.sheet_names:
            m = re.match(r'^(\d{4})(\d{2})$', sheet)
            if not m:
                continue
            y, mon = int(m.group(1)), int(m.group(2))
            df = pd.read_excel(io.BytesIO(content), sheet_name=sheet, header=None)
            passenger = None
            total = None
            for i in range(len(df)):
                v1 = df.iloc[i, 1]
                if v1 is None or (isinstance(v1, float) and v1 != v1):
                    continue
                s = str(v1).replace(' ', '').replace('\u3000', '')
                if s.startswith('総合計') or s.startswith('综合計'):
                    total = _to_int(df.iloc[i, 2])
                elif s in ('普通乗用車', '小型乗用車') or '乗用車' in s and '小計' not in s:
                    if passenger is None:
                        passenger = 0
                    passenger += _to_int(df.iloc[i, 2])
            result[(y, mon)] = {'passenger': passenger, 'total': total}
        return result

    def crawl_month(self, year, month):
        """爬指定月(从最新XLS取), 返回 {'records': n, 'total': t}"""
        links = self.discover_xls_url()
        if not links:
            return {'records': 0, 'total': None}
        # 最新文件(第一个)含当月+历史sheet
        url = links[0]
        r = self._fetch(url)
        if not r or len(r.content) < 5000:
            return {'records': 0, 'total': None}
        data = self.parse_xls(r.content)
        key = (year, month)
        if key not in data:
            return {'records': 0, 'total': None}
        rec = data[key]
        total = rec['total']
        n = 0
        # 行业总量行
        self._save_total(year, month, total)
        n += 1
        # 乘用车行
        self._save_passenger(year, month, rec['passenger'])
        n += 1
        return {'records': n, 'total': total}

    def _save_total(self, year, month, qty):
        conn, cur = self.get_connection()
        cur.execute("""
            INSERT INTO market_used_vehicle_monthly
                (country_code, source_month, brand_name_raw, brand_id, vehicle_type,
                 used_volume, used_import_volume, data_source, notes)
            VALUES (%s, %s, 'ALL', NULL, 'passenger', %s, NULL, 'jada_jp_used_car_registrations_monthly', 'JADA 中古車登録台数 総合計 (新規+移転+使用者変更)')
            ON CONFLICT (country_code, source_month, brand_name_raw, vehicle_type, data_source)
            DO UPDATE SET used_volume = EXCLUDED.used_volume, notes = EXCLUDED.notes
        """, ('JP', date(year, month, 1), qty))
        conn.commit()

    def _save_passenger(self, year, month, qty):
        if qty is None:
            return
        conn, cur = self.get_connection()
        cur.execute("""
            INSERT INTO market_used_vehicle_monthly
                (country_code, source_month, brand_name_raw, brand_id, vehicle_type,
                 used_volume, used_import_volume, data_source, notes)
            VALUES (%s, %s, 'JAPAN PASSENGER', NULL, 'passenger', %s, NULL, 'jada_jp_used_car_registrations_monthly', 'JADA 中古車登録台数 乗用車(普通+小型)')
            ON CONFLICT (country_code, source_month, brand_name_raw, vehicle_type, data_source)
            DO UPDATE SET used_volume = EXCLUDED.used_volume, notes = EXCLUDED.notes
        """, ('JP', date(year, month, 1), qty))
        conn.commit()

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_used_vehicle_monthly WHERE country_code='JP'")
        row = cur.fetchone()
        m = row['m'] if isinstance(row, dict) else row[0]
        return m

    def crawl_incremental(self):
        """探测最新月(从XLS sheet), >库MAX则爬"""
        links = self.discover_xls_url()
        if not links:
            return 0
        r = self._fetch(links[0])
        if not r:
            return 0
        data = self.parse_xls(r.content)
        max_m = self._get_db_max_month()
        saved = 0
        for (y, m) in sorted(data.keys()):
            sm = date(y, m, 1)
            if max_m is None or sm > max_m:
                res = self.crawl_month(y, m)
                saved += res['records']
        return saved


def _to_int(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if v != v:  # NaN
            return None
        return int(v)
    s = str(v).replace(',', '').replace(' ', '').replace('\u3000', '')
    try:
        return int(float(s))
    except ValueError:
        return None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--incremental', action='store_true')
    args = ap.parse_args()
    c = JadaUsedCrawler()
    if args.incremental:
        n = c.crawl_incremental()
        print(f'JP used incremental saved: {n}')
    else:
        links = c.discover_xls_url()
        print('xls links:', len(links))
        if links:
            r = c._fetch(links[0])
            data = c.parse_xls(r.content)
            for k in sorted(data.keys()):
                print(k, data[k])


if __name__ == '__main__':
    main()
