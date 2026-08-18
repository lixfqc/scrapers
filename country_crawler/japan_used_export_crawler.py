# -*- coding: utf-8 -*-
"""日本二手车出口爬虫: e-Stat 品別国別表(輸出) CSV
日本向全球各国出口二手车(中古乗用車) HS8703 9位码, 台数+金额(千円)。
数据源: 财务省贸易统计 e-Stat, CSV直链免登录, 发布滞后约1.5月。
CSV列: Exp or Imp,Year,HS,Country,Unit1,Unit2,Quantity1-Year,Quantity2-Year,Value-Year,
       Quantity1-Jan,Quantity2-Jan,Value-Jan,...(每3列一月, 全12月)
台数 = Quantity2列(Unit2='NO'), 金额 = Value列(千円), HS带引号, Country=日本3位代码。
"""
import re
import csv
import io
import time
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

JP_BASE = 'https://www.e-stat.go.jp'
JP_LIST_URL = ('https://www.e-stat.go.jp/stat-search/files?page=1&layout=datalist&toukei=00350300'
               '&tstat=000001013141&cycle=1&tclass1=000001013180&tclass2=000001013181'
               '&tclass3val=0&metadata=1&data=1')
JP_DL_URL = 'https://www.e-stat.go.jp/stat-search/file-download'

# 中古(Used)乘用车 9位 HS 码 (16个)
USED_HS_CODES = [
    '870321915', '870321925', '870322910', '870323915', '870323925', '870324910',
    '870331100', '870332915', '870332925', '870333910',
    '870340100', '870350100', '870360100', '870370100', '870380100', '870390100',
]

# 49国 ISO -> 日本統計国名3位代码
JP_CODE_MAP = {
    'KR': 103, 'CN': 105, 'TH': 111, 'SG': 112, 'MY': 113, 'PH': 117, 'ID': 118,
    'IN': 123, 'PK': 124, 'IR': 133, 'SA': 137, 'AE': 147,
    'RU': 224, 'PL': 223, 'HU': 227, 'RO': 231, 'BG': 232, 'EE': 235, 'LV': 236,
    'LT': 237, 'UA': 238, 'CZ': 245, 'SK': 246,
    'IS': 201, 'NO': 202, 'SE': 203, 'DK': 204, 'GB': 205, 'IE': 206, 'NL': 207,
    'BE': 208, 'FR': 210, 'DE': 213, 'CH': 215, 'PT': 217, 'ES': 218, 'IT': 220,
    'FI': 222, 'AT': 225, 'GR': 230, 'CY': 233, 'TR': 234, 'HR': 241, 'SI': 242,
    'CA': 302, 'US': 304, 'MX': 305, 'CO': 401, 'PE': 407, 'CL': 409, 'BR': 410,
    'AR': 413, 'MA': 501, 'EG': 506, 'NG': 524, 'KE': 541, 'ZA': 551,
    'AU': 601, 'NZ': 606,
}
# 反查: 日本代码 -> ISO
JP_CODE_REV = {v: k for k, v in JP_CODE_MAP.items()}


class JapanUsedExportCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('japan_used_export', 'JP')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'en,ja;q=0.9,en-US;q=0.8',
        })
        self._db_cache = {}
        self.conn, self.cur = self.get_connection()
        self._cur = self.cur

    def _fetch(self, url, timeout=90):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r
            except Exception as e:
                print(f'_fetch {url} err: {e}')
            time.sleep(2)
        return None

    # ---------- statInfId 发现 ----------
    def _find_stat_inf_ids(self, html):
        """从年月版页面提取全部 statInfId (22个, 按HS章节分块)。"""
        ids = set()
        for m in re.finditer(r'statInfId=(\d+)', html):
            ids.add(m.group(1))
        return sorted(ids)

    def discover_csv_ids(self, year=None, month=None):
        """发现最新年月版本的22个 statInfId。
        列表页(无直接ID) -> 提取最新 '&year=YYYY0&month=MMDDHHMM' 版本页链接 -> 提取22个statInfId。
        返回 list[str]。"""
        page = self._fetch(JP_LIST_URL)
        if not page:
            return []
        # 提取所有年月版链接 (href含 year=YYYY0&month=, HTML中&为&amp;)
        version_links = re.findall(
            r'href="([^"]*stat-search/files[^"]*&(?:amp;)?year=\d{5}&(?:amp;)?month=\d+[^"]*)"', page.text)
        if not version_links:
            return []
        # 用最新一个 (year最大, month最大) —— 数据文件是当年滚动版
        def key(v):
            ym = re.search(r'&(?:amp;)?year=(\d{5})&(?:amp;)?month=(\d+)', v)
            if not ym:
                return (0, 0)
            return (int(ym.group(1)), int(ym.group(2)))
        version_links.sort(key=key)
        latest = version_links[-1]
        # 进入最新版本页提取 statInfId
        if not latest.startswith('http'):
            latest = JP_BASE + latest
        latest = latest.replace('&amp;', '&')
        vp = self._fetch(latest)
        if not vp:
            return []
        return self._find_stat_inf_ids(vp.text)

    # ---------- 解析 ----------
    def parse_csv(self, csv_text, target_year=None, target_month=None):
        """解析8703中古车数据。返回 [(year, month, iso, hs, qty, value_jpy_k), ...]
        qty=台数(Quantity2), value=千円。"""
        rows = []
        reader = csv.reader(io.StringIO(csv_text))
        header = next(reader, None)
        if not header:
            return rows
        for row in reader:
            if len(row) < 12:
                continue
            try:
                exp_imp = row[0].strip()
                hs = row[2].strip().strip("'")
                country = row[3].strip()
            except Exception:
                continue
            if hs not in USED_HS_CODES:
                continue
            iso = JP_CODE_REV.get(int(country)) if country.isdigit() else None
            if not iso:
                continue
            for mi in range(12):
                base = 9 + mi * 3
                if base + 2 >= len(row):
                    break
                try:
                    qty = int(float(row[base + 1].replace(',', '') or 0))
                    val = int(float(row[base + 2].replace(',', '') or 0))
                except (ValueError, AttributeError):
                    qty, val = 0, 0
                if qty <= 0:
                    continue
                ym = target_month or (mi + 1)
                if target_month is not None and ym != target_month:
                    continue
                year = int(row[1].strip())
                if target_year is not None and year != target_year:
                    continue
                rows.append((year, mi + 1, iso, hs, qty, val))
        return rows

    # ---------- 入库 ----------
    def _insert(self, rec):
        cur = self._cur
        cur.execute("""
            INSERT INTO market_vehicle_trade_monthly
                (country_code, source_month, trade_type, partner_country, hs_code, new_used,
                 vehicle_type, energy_type, quantity, value_usd, data_source, notes, crawl_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
        """, rec)

    def crawl_latest(self):
        """下载最新CSV(全12月列), 解析全部中古车出口数据入库。
        返回 {'records': n}"""
        ids = self.discover_csv_ids(None, None)
        if not ids:
            print('no statInfId found')
            return {'records': 0}
        conn, cur = self.get_connection()
        self._conn, self._cur = conn, cur
        n = 0
        for sid in ids:
            url = f'{JP_DL_URL}?statInfId={sid}&fileKind=1'
            r = self._fetch(url)
            if not r:
                continue
            try:
                text = r.content.decode('utf-8-sig', errors='replace')
            except Exception:
                text = r.text
            # 找含8703的文件(第87章)
            if '8703219' not in text and '8703239' not in text:
                continue
            rows = self.parse_csv(text)
            for year, month, iso, hs, qty, val_k in rows:
                # 金额: 千円 -> USD (近似汇率 1 USD = 150 JPY)
                usd = int(val_k * 1000 / 150)
                rec = ('JP', date(year, month, 1), 'export', iso,
                       hs, 'used', 'passenger', None, qty, usd,
                       'japan_used_export', 'e-Stat 品別国別 中古乗用車 (HS8703 9位, 金额千円->USD@150)', datetime.now())
                self._insert(rec)
                n += 1
            conn.commit()
            time.sleep(0.5)
        print(f'crawl_latest saved {n} rows')
        return {'records': n}

    def crawl_incremental(self):
        return self.crawl_latest()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--incremental', action='store_true')
    args = ap.parse_args()
    c = JapanUsedExportCrawler()
    if args.incremental:
        print(c.crawl_incremental())
    else:
        ids = c.discover_csv_ids(None, None)
        print('statInfIds:', len(ids))


if __name__ == '__main__':
    main()
