# -*- coding: utf-8 -*-
"""匈牙利 HU 爬虫: KSH STADAT 品牌级首次登记(含进口二手车口径)
季度 sza0070 + 年度 sza0024, 品牌表=新车+进口二手车(二手约占51%)。
notes 标注口径, source_month=季度首月/年度首月。
"""
import re
import io
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

HU_BASE = 'https://www.ksh.hu/stadat_files/sza/hu'
SZA0070 = f'{HU_BASE}/sza0070.csv'   # 季度品牌
SZA0024 = f'{HU_BASE}/sza0024.csv'   # 年度品牌

QUARTERS = {'Q1': 1, 'Q2': 4, 'Q3': 7, 'Q4': 10}


class HuCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('ksh_stadat_sza', 'HU')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'en,hu;q=0.9',
        })
        self._brand_cache = {}

    def _fetch_csv(self, url):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=60)
                if r.status_code == 200:
                    return r.content  # latin-1 bytes
            except Exception as e:
                print(f'_fetch_csv {url} err: {e}')
            import time
            time.sleep(2)
        return None

    def _parse_brand_csv(self, content):
        """解析品牌表 CSV(latin-1, 分号分隔)。返回 [(period_key, brand, qty), ...]
        period_key: 季度 '2022 Q1' / 年度 '2022'。跳过 Total/Of which: 行。
        """
        text = content.decode('latin-1')
        lines = [l.rstrip('\r\n') for l in text.split('\n') if l.strip()]
        if len(lines) < 4:
            return []
        header = lines[1].split(';')
        periods = []
        for h in header[1:]:  # 跳过 Make 列
            h = h.strip()
            if not h:
                continue
            # 季度(匈牙利语): '2022. I. negyedév' / 年度: '2022' / 英文 '2022 Q1'
            m = re.match(r'^(\d{4})', h)
            if not m:
                continue
            year = int(m.group(1))
            qm = re.search(r'\b([IVX]{1,3})\.?', h)
            if qm and qm.group(1) in ('I', 'II', 'III', 'IV'):
                qn = {'I': 1, 'II': 2, 'III': 3, 'IV': 4}[qm.group(1)]
                periods.append(f'{year} Q{qn}')
                continue
            if re.match(r'^\d{4}$', h) or re.match(r'^\d{4} Q[1-4]$', h):
                periods.append(h)
        records = []
        for ln in lines[4:]:
            cells = ln.split(';')
            if len(cells) < 2:
                continue
            brand = cells[0].strip()
            if not brand or brand.upper() in ('TOTAL', 'ÖSSZESEN', 'OF WICH:', 'OF WHICH:', 'EBBŐL:'):
                continue
            for i, p in enumerate(periods):
                if i + 1 >= len(cells):
                    break
                val = cells[i + 1].strip().replace(' ', '')
                if not val or not val.isdigit():
                    continue
                qty = int(val)
                if qty > 0:
                    records.append((p, brand, qty))
        return records

    def _period_to_date(self, period):
        """'2022 Q1' -> date(2022,1,1); '2022' -> date(2022,1,1)"""
        m = re.match(r'^(\d{4})(?: Q([1-4]))?$', period)
        if not m:
            return None
        y = int(m.group(1))
        q = m.group(2)
        month = QUARTERS.get(q, 1) if q else 1
        return date(y, month, 1)

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

    def crawl_source(self, url, period_type):
        """解析一个品牌表 CSV 并入库全部记录。返回 {period: count}"""
        content = self._fetch_csv(url)
        if not content:
            return {}
        records = self._parse_brand_csv(content)
        result = {}
        for period, brand, qty in records:
            sm = self._period_to_date(period)
            if not sm:
                continue
            rec = {
                'country_code': 'HU',
                'source_month': sm,
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
                'data_source': 'ksh_stadat_sza',
                'notes': f'KSH sza {period_type} {period} (first registrations incl used imports)',
            }
            self.save_sales(rec)
            result[period] = result.get(period, 0) + 1
        return result

    def crawl_quarterly(self):
        return self.crawl_source(SZA0070, 'quarterly')

    def crawl_annual(self):
        return self.crawl_source(SZA0024, 'annual')

    def crawl_incremental(self):
        # 简单：全量入库(save_sales幂等, 已有记录自动UPDATE)
        q = self.crawl_quarterly()
        a = self.crawl_annual()
        nq = sum(q.values())
        na = sum(a.values())
        return nq + na


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--incremental', action='store_true')
    ap.add_argument('--test', action='store_true')
    args = ap.parse_args()
    c = HuCrawler()
    if args.test:
        q = c.crawl_source(SZA0070, 'quarterly')
        a = c.crawl_source(SZA0024, 'annual')
        print('quarterly:', q)
        print('annual:', a)
    elif args.incremental:
        n = c.crawl_incremental()
        print(f'HU incremental saved: {n}')
    else:
        q = c.crawl_quarterly()
        a = c.crawl_annual()
        print('quarterly:', sum(q.values()), 'annual:', sum(a.values()))


if __name__ == '__main__':
    main()
