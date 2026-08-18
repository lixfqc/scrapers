# -*- coding: utf-8 -*-
"""中国 CN 二手车爬虫: CADA 中国汽车流通协会月度交易量 JSON
口径: 二手车月度交易量(万辆)。接口返回滚动最近12个月。
"""
import re
import time
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

CN_USE_URL = 'http://data.cada.cn/usedCar/monthTradingVolume.do'


class CadaUsedCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('cada_cn_used_car_transactions_monthly', 'CN')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        })

    def _fetch_json(self, url, timeout=30):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
            except Exception as e:
                print(f'_fetch_json {url} err: {e}')
            time.sleep(2)
        return None

    def _parse_window(self, data):
        """解析滚动12个月窗口。返回 {(year, month): 交易量(辆)}。
        xAxis 中 '2026年1月' 带年份标记 -> 确定年份; 其余推断为连续月份。
        """
        xaxis = data.get('xAxis', [])
        series = data.get('series', [])
        vol = None
        mom = None
        for s in series:
            if s.get('name') == '交易量':
                vol = s.get('data', [])
            elif s.get('name') == '环比':
                mom = s.get('data', [])
        if not vol or len(vol) != len(xaxis):
            return {}
        # 确定基准: 找带 "YYYY年" 的标记项
        anchor_ym = None
        for i, x in enumerate(xaxis):
            m = re.match(r'^(\d{4})年(\d{1,2})月$', x)
            if m:
                anchor_ym = (int(m.group(1)), int(m.group(2)), i)
                break
        result = {}
        if anchor_ym:
            ay, am, ai = anchor_ym
            # 窗口内月份: 从锚点往前/后推算
            for i, x in enumerate(xaxis):
                if i == ai:
                    y, mth = ay, am
                elif i > ai:
                    # 锚点之后的月份 (连续递增)
                    y, mth = ay, am + (i - ai)
                else:
                    y, mth = ay, am + (i - ai)
                while mth > 12:
                    y += 1
                    mth -= 12
                while mth < 1:
                    y -= 1
                    mth += 12
                try:
                    q = float(vol[i]) * 10000  # 万辆 -> 辆
                except (TypeError, ValueError):
                    continue
                result[(y, mth)] = int(q)
        return result

    def crawl_incremental(self):
        """拉取滚动窗口, 只入库 > 库MAX 的月份。"""
        d = self._fetch_json(CN_USE_URL)
        if not d or d.get('code') != 200:
            return 0
        window = self._parse_window(d.get('data') or {})
        # 库中MAX
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_used_vehicle_monthly WHERE country_code='CN'")
        row = cur.fetchone()
        max_m = row['m'] if isinstance(row, dict) else row[0]
        if hasattr(max_m, 'date'):
            max_m = max_m.date() if not isinstance(max_m, date) else max_m
        saved = 0
        for (y, mth) in sorted(window.keys()):
            sm = date(y, mth, 1)
            if max_m is None or sm > max_m:
                vol = window[(y, mth)]
                cur.execute("""
                    INSERT INTO market_used_vehicle_monthly
                        (country_code, source_month, brand_name_raw, brand_id, vehicle_type,
                         used_volume, used_import_volume, data_source, notes, crawl_time)
                    VALUES (%s,%s,%s,NULL,%s,%s,NULL,%s,%s,%s)
                    ON CONFLICT (country_code, source_month, brand_name_raw, vehicle_type, data_source)
                    DO UPDATE SET used_volume=EXCLUDED.used_volume, crawl_time=EXCLUDED.crawl_time
                """, ('CN', sm, 'ALL', 'passenger', vol, 'cada_cn_used_car_transactions_monthly',
                      'CADA monthly used car transactions (万辆*10000)', datetime.now()))
                saved += 1
        conn.commit()
        return saved


def main():
    c = CadaUsedCrawler()
    d = c._fetch_json(CN_USE_URL)
    if d and d.get('code') == 200:
        w = c._parse_window(d.get('data') or {})
        print('window months:', len(w))
        for k in sorted(w.keys())[-4:]:
            print(k, w[k])
        n = c.crawl_incremental()
        print('incremental saved:', n)


if __name__ == '__main__':
    main()
