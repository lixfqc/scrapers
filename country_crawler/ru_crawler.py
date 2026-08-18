# -*- coding: utf-8 -*-
"""RU Russia crawler - AEB (aebrus.ru) PDF brand sales 2007-2023, market total 2024+
Class: RuCrawler(BaseCrawler), source_name='aeb', country_code='RU'
"""
import sys, io, os, re, random, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST
import requests
import pdfplumber
from datetime import datetime, date

RU_LIST_URL = 'https://aebrus.ru/en/media/press-releases/sales-of-cars-and-light-commercial-vehicles.php'
RU_BASE = 'https://aebrus.ru'
RU_MONTHS = ['january', 'february', 'march', 'april', 'may', 'june',
              'july', 'august', 'september', 'october', 'november', 'december']
# 俄语月份(全称), 用于 RUS 版 PDF 表头识别
RU_MONTHS_RU = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
                'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
RU_MONTH_RE = r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*'
RU_MONTH_RE_RU = r'(январь|февраль|март|апрель|май|июнь|июль|август|сентябрь|октябрь|ноябрь|декабрь)'
RU_BRAND_SKIP = {'TOTAL', 'BRAND', 'BRANDS', 'GROUPS'}
RU_TABLE_END = ('BY GROUPS', 'BEST SOLD', '25 BEST', '10 BEST')
# footer address lines in AEB PDFs (must not be parsed as brands)
RU_ADDR_WORDS = ('ASSOCIATION OF EUROPEAN', 'KRASNOPROLETARSKAYA', 'KASNOPROLETARSKAYA',
                 'BUSINESSES', 'UL. KRASNOPROLETARSKAYA', 'MOSCOW', 'RUSSIAN FEDERATION',
                 'PRESS RELEASE', 'TEL.', 'FAX', 'E-MAIL', 'WWW.AEBRUS.RU')


def _to_int(s):
    if s is None:
        return None
    s = str(s).strip().replace(' ', '').replace('\u00a0', '').replace(',', '')
    try:
        return int(float(s))
    except Exception:
        return None


class RuCrawler(BaseCrawler):
    def __init__(self, source_name='aeb', country_code='RU'):
        super().__init__(source_name, country_code)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': random.choice(UA_LIST),
            'Accept-Language': 'en-US,en;q=0.9',
        })
        self._brand_id_cache = {}

    # ---------- index ----------
    def _fetch(self, url, timeout=60):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    r.encoding = r.apparent_encoding
                    return r.text
            except Exception:
                pass
            time.sleep(random.uniform(2, 4))
        return None

    def _build_file_index(self):
        """Parse list pages ?PAGEN_1=1..12 -> {(year,month): (url, title)}"""
        index = {}
        for page in range(1, 13):
            url = RU_LIST_URL if page == 1 else f'{RU_LIST_URL}?PAGEN_1={page}'
            html = self._fetch(url)
            if not html:
                continue
            # anchors: href=...pdf, text title
            for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>([^<]*)</a>', html):
                href, title = m.group(1).strip(), m.group(2).strip()
                if not href.lower().endswith('.pdf'):
                    continue
                title_l = title.lower()
                # month name + 4-digit year in title
                mm = re.search(r'\b([a-z]+)\s+(20\d{2})\b', title_l)
                if not mm:
                    continue
                mname, year = mm.group(1), int(mm.group(2))
                try:
                    month = RU_MONTHS.index(mname) + 1
                except ValueError:
                    continue
                # prefer English (non 'rus') version
                full = href if href.startswith('http') else RU_BASE + href
                prev = index.get((year, month))
                if prev is None or (title_l.startswith('en') or title_l.startswith('eng')):
                    index[(year, month)] = (full, title)
            time.sleep(random.uniform(1.0, 1.8))
        return index

    def latest_available_month(self):
        idx = self._build_file_index()
        if not idx:
            return None
        return max(idx.keys())

    # ---------- download / parse ----------
    def download_pdf(self, url):
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=120)
                if r.status_code == 200 and len(r.content) > 5000:
                    return r.content
            except Exception:
                pass
            time.sleep(random.uniform(2, 4))
        return None

    def _parse_brand_table(self, pdf_bytes):
        """Extract monthly brand sales from 'BY BRANDS' table (2007-2023) via
        x-coordinate column clustering (verified against 2023-01 & 2011 samples).
        Returns list of (brand, month_qty)."""
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = pdf.pages
            page_words = [p.extract_words() for p in pages]
            page_texts = [(p.extract_text() or '') for p in pages]

        # 只解析第一张"单月品牌表"页: 页文本含 BY BRANDS 且非 YTD/集团/车型表
        # 后续页的 YTD 表(JANUARY-DECEMBER)/集团表(BRAND/GROUP)/车型表(# MODEL) 全部跳过
        # 只解析第一张"单月品牌表"页。
        # 封面新闻稿页也有 "1. NEW CAR/LCV SALES ... BY BRANDS ..." 摘要标题(带编号"1.")，
        # 真实品牌表页标题为 "NEW CAR AND LCV SALES IN RUSSIA BY BRANDS FOR <月份>"(无编号)。
        # 后续页的 YTD 表(JANUARY-DECEMBER)/集团表(BRAND/GROUP)/车型表(# MODEL) 全部跳过。
        target_pi = None
        for pi, txt in enumerate(page_texts):
            lines = [l.strip() for l in txt.split('\n') if l.strip()]
            hit_line = None
            # 品牌表标题模式 (2008-2023 多种格式):
            #   "NEW CAR AND LCV SALES IN RUSSIA BY BRANDS FOR <月份>"
            #   "SALES OF FOREIGN BRANDS IN RUSSIA IN <月份>"
            #   "CAR AND LCV* SALES IN RUSSIA IN <月份> / <N> MONTHS <年份>"
            #   "SALES OF CARS AND LIGHT COMMERCIAL VEHICLES IN RUSSIA IN <月份>"
            # 封面正文散文(小写)也会含这些词(如 "sales of foreign brands* increase by 53%"),
            # 必须要求标题行全大写(标题是大写,正文散文是小写)。
            for ln in lines:
                u = ln.upper()
                if ('BY BRANDS' in u or 'SALES OF FOREIGN BRANDS' in u
                        or 'CAR AND LCV' in u or 'SALES OF CARS AND LIGHT' in u
                        or 'ПО МАРКАМ' in u):
                    # 标题行应基本全大写(封面正文散文是小写, 如 'january 2008 saw sales...')。
                    # 不能用 ln==u 严格判断: 标题可能含小写字符(如俄语 '2009г.' 的 г)。
                    n_upper = sum(1 for ch in ln if ch.isupper())
                    n_lower = sum(1 for ch in ln if ch.islower())
                    if n_upper > 0 and n_upper >= n_lower:
                        hit_line = ln
                        break
            if hit_line is None:
                continue
            # 封面摘要标题带编号如 "1. NEW CAR/LCV ..."；品牌表标题无编号
            if re.match(r'^\d+\s*[.)．]', hit_line.strip()):
                continue
            # 集团表 / 车型表 (BY GROUPS / BRAND/GROUP / # MODEL / MODEL BRAND)
            if ('BY GROUPS' in txt.upper() or 'BRAND/GROUP' in txt.upper()
                    or '# MODEL' in txt.upper() or 'MODEL BRAND' in txt.upper()):
                continue
            # 品牌表页必须有 BRAND/BRANDS 表头word(封面叙述页没有表格)
            has_header = any(w['text'] in ('BRANDS', 'BRAND', 'Brands', 'Brand', 'МАРКИ')
                             for w in page_words[pi])
            if not has_header:
                continue
            target_pi = pi
            break
        if target_pi is None:
            return []

        records = []
        for pi, words in enumerate(page_words):
            if pi != target_pi:
                continue
            header_words = [w for w in words if w['text'] in ('BRANDS', 'BRAND', 'Brands', 'Brand', 'МАРКИ')]
            if not header_words:
                continue
            hw = min(header_words, key=lambda w: w['x0'])
            top = hw['top']
            # 表头行: 年份标签可能在 BRAND 的下一行(top差可达12)
            hr = [w for w in words if abs(w['top'] - top) < 12]
            brand_center = hw['x0']
            # 年份标签列: 2010 / '10(撇号两位) / Nov'10组合词 (跨行收集); 排除括号说明文字
            def _is_year_label(w):
                txt = w['text']
                if txt.startswith('('):
                    return False
                return bool(re.search(r'(?:20\d\d|[\'\u2019]\d\d)', txt))
            num_cols = sorted(w['x0'] for w in hr
                              if w['x0'] > brand_center + 20 and _is_year_label(w))
            # 去重: 同年标签x0可能重复
            _dedup = []
            for x in num_cols:
                if not _dedup or abs(x - _dedup[-1]) > 10:
                    _dedup.append(x)
            num_cols = _dedup
            if len(num_cols) < 2:
                num_cols = sorted(w['x0'] for w in hr
                                  if w['x0'] > brand_center + 20
                                  and not re.match(RU_MONTH_RE, w['text'], re.I)
                                  and not re.match(RU_MONTH_RE_RU, w['text'], re.I)
                                  and w['text'].upper() not in ('%', 'PERCENT')
                                  and not w['text'].startswith('('))
            if len(num_cols) < 2:
                continue
            # 判定当月列位置:
            #   len==2 (现代 2015/2016/2019/2023 / 2008): 当月=idx0
            #   len==4 (双期 2011/2014/2009): 检查第1列上方是否累计月份词(带连字符)
            #     2009: January-@223(累计在前) -> 当月=idx2 (February 2009)
            #     2011: Jan.-May在前(累计)     -> 当月=idx2 (May2011)
            #     2014: May在前(当月)          -> 当月=idx0 (May2014, January-May@423在列后)
            early = len(num_cols) >= 4
            qty_idx = 0
            if early:
                # 累计月份词(带 - 或 .): January- / Jan.-May / Jan-May / январь-май -> 第1列是累计区间
                # 2010-11 表头 'Jan – Nov'10' 中破折号是独立word -> 也视为累计
                dash_x = [w['x0'] for w in hr if w['text'] in ('-', '–', '—')]
                hyphen_months = []
                for w in hr:
                    wt = w['text']
                    if w['x0'] > brand_center + 20 and re.match(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*', wt, re.I):
                        if re.search(r'[.\-]', wt):
                            hyphen_months.append(w['x0'])
                        elif any(dx > w['x0'] and dx < num_cols[1] for dx in dash_x):
                            hyphen_months.append(w['x0'])
                    elif w['x0'] > brand_center + 20 and re.match(RU_MONTH_RE_RU + r'[.\-]', wt, re.I):
                        hyphen_months.append(w['x0'])
                if hyphen_months and min(hyphen_months) < num_cols[1]:
                    qty_idx = 2  # 累计列在前 -> 当月列在后 (2009-02/2011/2010-11)
                else:
                    qty_idx = 0  # 当月列在前 (2014-05: May在前)
            else:
                qty_idx = 0

            data_top = top + 6
            cands = sorted([w for w in words if w['top'] >= data_top],
                           key=lambda w: (w['top'], w['x0']))
            rows = []
            cur = []
            cur_top = None
            for w in cands:
                if cur_top is None:
                    cur = [w]
                    cur_top = w['top']
                elif abs(w['top'] - cur_top) < 5:
                    cur.append(w)
                    cur_top = max(cur_top, w['top'])
                else:
                    rows.append(cur)
                    cur = [w]
                    cur_top = w['top']
            if cur:
                rows.append(cur)

            for row in rows:
                brand_parts = []
                col_vals = {i: [] for i in range(len(num_cols))}
                for w in sorted(row, key=lambda x: x['x0']):
                    if w['x0'] <= brand_center + 35:
                        txt = w['text'].rstrip('*')
                        if txt and txt.upper() not in ('BRAND', 'BRANDS', 'МАРКИ'):
                            brand_parts.append(txt)
                        continue
                    best = min(range(len(num_cols)), key=lambda i: abs(w['x0'] - num_cols[i]))
                    col_vals[best].append(w['text'])
                if not brand_parts:
                    continue
                brand = ' '.join(brand_parts).upper()
                # strip trailing digits glued to brand name (cross-page continuation)
                brand = re.sub(r'\d+$', '', brand).strip()
                if brand in ('TOTAL', 'BRAND', 'BRANDS', 'ИТОГО', 'ВСЕГО') or brand.startswith('TOTAL') or brand.startswith('ИТОГО') or brand.startswith('ВСЕГО'):
                    return records  # table complete
                # skip header continuation / non-brand rows
                if re.search(r'\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b|20\d\d', brand):
                    continue
                if re.match(r'^\d', brand):
                    continue  # ranked model rows like '1 GAZELLE GAZ LCV'
                if any(k in brand for k in RU_TABLE_END):
                    return records
                # footer address lines (ASSOCIATION OF EUROPEAN BUSINESSES ... KRASNOPROLETARSKAYA STR)
                if any(w in brand for w in RU_ADDR_WORDS):
                    continue
                vals = []
                for i in range(len(num_cols)):
                    # 只保留纯数字 token(丢弃百分比/负号 token 如 '-37%'/'46%')
                    num_tokens = [t for t in col_vals[i] if re.fullmatch(r'[\d\.,\s]+', t)]
                    num = ''.join(num_tokens)
                    v = _to_int(num)
                    vals.append(v)
                if len(vals) > qty_idx:
                    qty = vals[qty_idx]
                    if qty and qty > 0:
                        records.append((brand, qty))
            # continue to next page for cross-page table continuation
        return records

    # ---------- save ----------
    def get_brand_id(self, brand_raw):
        if brand_raw in self._brand_id_cache:
            return self._brand_id_cache[brand_raw]
        b = brand_raw.upper()
        try:
            conn, cur = self.get_connection()
            cur.execute("""
                SELECT id FROM brand_name_mapping
                WHERE UPPER(canonical_name)=%s OR UPPER(brand_name_cn)=%s
                ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, id LIMIT 1
            """, (b, b))
            row = cur.fetchone()
            if row:
                bid = row['id'] if isinstance(row, dict) else row[0]
                self._brand_id_cache[brand_raw] = bid
                return bid
            cur.execute("""
                SELECT brand_id FROM brand_name_variant WHERE UPPER(variant_name)=%s LIMIT 1
            """, (b,))
            row = cur.fetchone()
            if row:
                bid = row['brand_id'] if isinstance(row, dict) else row[0]
                self._brand_id_cache[brand_raw] = bid
                return bid
        except Exception:
            pass
        self._brand_id_cache[brand_raw] = None
        return None

    def save_sales(self, record):
        record['brand_id'] = self.get_brand_id(record['brand_name_raw'])
        return super().save_sales(record)

    # ---------- crawl ----------
    def crawl_month(self, year, month, idx=None):
        if idx is None:
            idx = self._build_file_index()
        item = idx.get((year, month))
        if not item:
            return {'records': 0, 'note': 'no file in index'}
        url, title = item
        content = self.download_pdf(url)
        if not content:
            return {'records': 0, 'note': 'download failed'}
        brands = self._parse_brand_table(content)
        n = 0
        for brand, qty in brands:
            rec = {
                'country_code': 'RU',
                'source_month': date(year, month, 1),
                'brand_name_raw': brand,
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
                'data_source': 'aeb',
                'notes': 'AEB brand sales (2007-2023)',
            }
            try:
                self.save_sales(rec)
                n += 1
            except Exception:
                pass
        return {'records': n}

    def crawl_incremental(self):
        """Crawl latest available month if newer than DB max."""
        idx = self._build_file_index()
        if not idx:
            return 0
        latest = max(idx.keys())
        try:
            conn, cur = self.get_connection()
            cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='RU' AND data_source='aeb'")
            row = cur.fetchone()
            max_m = row['m'] if isinstance(row, dict) else row[0]
        except Exception:
            max_m = None
        if max_m is not None:
            latest_d = date(latest[0], latest[1], 1)
            if latest_d <= max_m:
                return 0
        r = self.crawl_month(latest[0], latest[1])
        return r.get('records', 0)

    def crawl_range(self, start_year, start_month, end_year, end_month):
        idx = self._build_file_index()
        results = {}
        y, m = start_year, start_month
        while (y, m) <= (end_year, end_month):
            results[f'{y}-{m:02d}'] = self.crawl_month(y, m)
            m += 1
            if m > 12:
                m = 1
                y += 1
        return results


def main():
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == '--incremental':
        c = RuCrawler()
        n = c.crawl_incremental()
        print(f'RU incremental saved: {n}')
    else:
        c = RuCrawler()
        res = c.crawl_range(2007, 1, 2023, 12)
        ok = sum(1 for v in res.values() if v.get('records', 0) > 0)
        tot = sum(v.get('records', 0) for v in res.values())
        print(f'RU crawl_range done: {ok}/{len(res)} months, {tot} records')


if __name__ == '__main__':
    main()
