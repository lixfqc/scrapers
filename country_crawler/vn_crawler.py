# -*- coding: utf-8 -*-
"""越南 VN 爬虫: VAMA (vama.org.vn) 月度 Summary PDF 品牌级销量
口径: 零售销量(doanh số bán hàng), VAMA 成员(不含 VinFast/Hyundai)。
注意: 必须用 HTTP(HTTPS 被重置)。Summary PDF 第2节=成员公司月度表。
"""
import re
import io
import time
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

VN_BASE = 'http://vama.org.vn'
VN_INDEX = 'http://vama.org.vn/vn/bao-cao-ban-hang.html'

VN_MONTH_MAP = {'1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6,
                '7': 7, '8': 8, '9': 9, '10': 10, '11': 11, '12': 12}
VN_EN_MONTH = {1: 'January', 2: 'February', 3: 'March', 4: 'April', 5: 'May', 6: 'June',
               7: 'July', 8: 'August', 9: 'September', 10: 'October', 11: 'November', 12: 'December'}

# Thaco 系品牌名拆分
THACO_MAP = {
    'THACO KIA': 'KIA', 'THACO MAZDA': 'MAZDA', 'PEUGEOT': 'PEUGEOT',
    'THACO TRUCK': 'THACO', 'BUS THACO': 'THACO BUS',
    'THACO PREMIUM BMW+MINI': 'BMW', 'BMW-MINI': 'BMW',
}
SKIP_COMPANIES = ('TOTAL', 'TOTAL THACO', 'MEKONG', 'VAMA', 'TONG')

# VN 品牌名 -> 需映射 (依赖 get_brand_id UPPER 查 mapping)
# Toyota/Lexus/Mercedes/Ford/Honda/Peugeot/Mitsubishi/Isuzu/Suzuki/Hino/BMW/Kia/Mazda


class VnCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('vama_monthly_sales', 'VN')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        self._brand_cache = {}

    def _fetch(self, url, timeout=60):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r
            except Exception as e:
                print(f'_fetch {url} err: {e}')
            time.sleep(2)
        return None

    VN_EN_MONTHS = {'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
                    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12}

    def discover_month_urls(self):
        """遍历索引分页, 收集全部 Summary PDF 链接。
        返回 {(year, month): pdf_url}。文件名如 'VAMA sales report July 2026 -  Summary.pdf'。
        """
        found = {}
        pat_pdf = re.compile(r'href="([^"]+\.pdf[^"]*)"', re.I)
        pat_month = re.compile(r'([A-Za-z]+)\s+(\d{4})')
        for page in range(1, 40):
            url = VN_INDEX if page == 1 else f'{VN_INDEX}?Page={page}'
            r = self._fetch(url)
            if not r:
                break
            hits = pat_pdf.findall(r.text)
            new_count = 0
            for href in hits:
                hl = href.lower()
                if 'summary' not in hl:
                    continue
                if 'lexus' in hl or 'bmw' in hl:
                    continue
                # 从文件名提取月份 (July 2026)
                fname = href.split('/')[-1].replace('%20', ' ')
                fname = requests.utils.unquote(fname)
                m = pat_month.search(fname)
                if not m:
                    continue
                mname = m.group(1).lower()
                if mname not in self.VN_EN_MONTHS:
                    continue
                mon = self.VN_EN_MONTHS[mname]
                yr = int(m.group(2))
                if not (2000 <= yr <= 2030):
                    continue
                full = href if href.startswith('http') else VN_BASE + href
                key = (yr, mon)
                if key not in found:
                    found[key] = full
                    new_count += 1
            if new_count == 0 and page > 1:
                break
            time.sleep(0.8)
        return found

    def find_summary_pdf(self, article_html):
        """索引页直接含 Summary PDF 链接。"""
        pat = re.compile(r'href="([^"]+\.pdf[^"]*)"', re.I)
        for href in pat.findall(article_html):
            if 'summary' in href.lower() and 'lexus' not in href.lower() and 'bmw' not in href.lower():
                if href.startswith('http'):
                    return href
                return VN_BASE + href
        return None

    def parse_summary_pdf(self, pdf_bytes, year, month):
        """解析 Summary PDF 第2节成员公司月度表。
        返回 [(brand_raw, qty), ...] 和 total。
        第2节表头含 'TOTAL' 合计行; Thaco 拆分行为子品牌。
        """
        import pdfplumber
        brands = []
        total = None
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = ''
            for page in pdf.pages:
                t = page.extract_text() or ''
                text += t + '\n'
        # 找第2节(成员公司月度)起点: 含 'TOTAL' 的公司表, 或 'Total*' 标记后
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        # 定位第2节(VAMA Complete Vehicles 成员公司月度表)起点:
        # 先找第2节标题行, 其后第1个公司行即数据起点 (横版/竖版通用, 不依赖月份表头)
        start = None
        for i, ln in enumerate(lines):
            if 'VAMA COMPLETE VEHICLES' in ln.upper():
                for j in range(i + 1, min(i + 12, len(lines))):
                    lu = lines[j].upper()
                    if lu.startswith('MEKONG') or lu.startswith('MITSUBISHI') or lu.startswith('TOTAL'):
                        start = j
                        break
                if start is not None:
                    break
        if start is None:
            # fallback: 找含任意 '{MON}-2x' 表头行 (如 Jan-26/Jul-26)
            for i, ln in enumerate(lines):
                u = ln.upper()
                if re.match(r'^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)-2[0-9]', u) and ('YTM' in u or 'DIFFERENCE' in u):
                    start = i + 2
                    break
        if start is None:
            for i, ln in enumerate(lines):
                if ln.upper() == 'TOTAL' or (ln.upper().startswith('TOTAL') and len(re.findall(r'\d', ln)) > 5):
                    start = i - 2
                    break
        if start is None:
            start = 0
        # 从 start 后逐行: 公司名 + 数字序列
        seen = set()
        in_section2 = True
        for ln in lines[start:]:
            u = ln.upper()
            # 遇到第3节表头(YTM 2026)或页脚则停止
            if u.startswith('YTM 2026') or 'YTM 2026' in u or 'PRINTED ON' in u or 'SENDTOMEDIA' in u:
                in_section2 = False
                break
            # 跳过表头/分段 (含任意月份缩写表头如 JAN-26/JUL-26)
            if re.match(r'^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC|THANG|STT|TT|NO|MAKER|COMPANY|ĐVT|DVT)', u) or 'VAMA' == u:
                continue
            # 公司名 + 首个数字token = 当月销量
            m = re.match(r'^([A-Z][A-Za-z0-9\s\+\-\.\(\)\*]{1,40}?)\s+([\d][\d\s\,\.]*)', ln)
            if not m:
                continue
            comp = m.group(1).strip().rstrip('*').strip()
            # 只取第一个数字token (千分位逗号)
            nums = re.findall(r'\d[\d\,]*', m.group(2))
            if not nums:
                continue
            qty_s = nums[0].replace(',', '')
            if not qty_s:
                continue
            try:
                qty = int(qty_s)
            except ValueError:
                continue
            cu = comp.upper()
            if any(s in cu for s in SKIP_COMPANIES):
                if cu == 'TOTAL' or cu.startswith('TOTAL'):
                    total = qty
                continue
            if comp in seen:
                continue
            seen.add(comp)
            # Thaco 拆分
            brand = comp
            for k, v in THACO_MAP.items():
                if cu == k:
                    brand = v
                    break
            if qty > 0:
                brands.append((brand, qty))
        return brands, total

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
        """爬指定月份, 返回 {'records': n, 'total': t}"""
        urls = self.discover_month_urls()
        pdf_url = urls.get((year, month))
        if not pdf_url:
            return {'records': 0, 'total': None}
        rp = self._fetch(pdf_url)
        if not rp or len(rp.content) < 5000:
            return {'records': 0, 'total': None}
        brands, total = self.parse_summary_pdf(rp.content, year, month)
        n = 0
        for brand, qty in brands:
            rec = {
                'country_code': 'VN',
                'source_month': date(year, month, 1),
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
                'data_source': 'vama_monthly_sales',
                'notes': 'VAMA monthly member sales (retail, excl VinFast/Hyundai)',
            }
            self.save_sales(rec)
            n += 1
        return {'records': n, 'total': total}

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='VN'")
        row = cur.fetchone()
        m = row['m'] if isinstance(row, dict) else row[0]
        return m.date() if hasattr(m, 'date') else m

    def crawl_incremental(self):
        max_m = self._get_db_max_month()
        urls = self.discover_month_urls()
        saved = 0
        for (y, m) in sorted(urls.keys()):
            sm = date(y, m, 1)
            if max_m is None or sm > max_m:
                res = self.crawl_month(y, m)
                saved += res['records']
        return saved

    def crawl_range(self, y1, m1, y2, m2):
        urls = self.discover_month_urls()
        results = {}
        for (y, m) in sorted(urls.keys()):
            if (y, m) < (y1, m1) or (y, m) > (y2, m2):
                continue
            res = self.crawl_month(y, m)
            results[f'{y}-{m:02d}'] = res
            print(f'{y}-{m:02d}: {res}')
            time.sleep(1)
        return results


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--incremental', action='store_true')
    ap.add_argument('--y1', type=int, default=2019)
    ap.add_argument('--m1', type=int, default=1)
    ap.add_argument('--y2', type=int, default=2026)
    ap.add_argument('--m2', type=int, default=7)
    ap.add_argument('--ym', type=str, default='', help='单月 2026-07')
    args = ap.parse_args()

    c = VnCrawler()
    if args.ym:
        y, m = map(int, args.ym.split('-'))
        print(c.crawl_month(y, m))
    elif args.incremental:
        n = c.crawl_incremental()
        print(f'VN incremental saved: {n}')
    else:
        urls = c.discover_month_urls()
        print('months found:', len(urls))
        res = c.crawl_range(args.y1, args.m1, args.y2, args.m2)
        print('VN range done')


if __name__ == '__main__':
    main()
