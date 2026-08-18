# -*- coding: utf-8 -*-
"""欧洲 ACEA 月度新车注册爬虫: 国家 × 动力类型
数据: acea.auto 月度 press release PDF (NEW CAR REGISTRATIONS BY MARKET AND POWER SOURCE)
粒度: 30市场(EU27+IS/NO/CH+UK) × 7动力(BEV/PHEV/HEV/Others/Petrol/Diesel/Total) × 月度
注意: Cloudflare 按 UA 指纹区分, 必须用非浏览器 UA(curl/8.4.0), 浏览器 UA 反而 403
口径: 新车注册(registrations), 各国协会+ACEA成员+S&P Global Mobility 汇总
"""
import re
import io
import time
import requests
from datetime import date, datetime
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

ACEA_BASE = 'https://www.acea.auto'
ACEA_AJAX = 'https://www.acea.auto/wp-admin/admin-ajax.php'
CURL_UA = 'curl/8.4.0'

# 动力类型列标签 (表头顺序)
POWER_COLS = ['BATTERY ELECTRIC', 'PLUG-IN HYBRID', 'HYBRID ELECTRIC', 'OTHERS', 'PETROL', 'DIESEL', 'TOTAL']
POWER_ENERGY = {
    'BATTERY ELECTRIC': 'BEV', 'PLUG-IN HYBRID': 'PHEV', 'HYBRID ELECTRIC': 'HEV',
    'OTHERS': 'OTHER', 'PETROL': 'GASOLINE', 'DIESEL': 'DIESEL', 'TOTAL': None,
}
# 汇总行 (保留入库, 通过country_code特殊标记)
AGGREGATE_ROWS = {'EUROPEAN UNION', 'EU14', 'EU12', 'EFTA', 'UNITED KINGDOM', 'EU + EFTA + UK'}

# ACEA 国家全名 → ISO alpha2 (EU27 + IS/NO/CH + GB)
ACEA_COUNTRY_MAP = {
    'AUSTRIA': 'AT', 'BELGIUM': 'BE', 'BULGARIA': 'BG', 'CROATIA': 'HR',
    'CYPRUS': 'CY', 'CZECHIA': 'CZ', 'DENMARK': 'DK', 'ESTONIA': 'EE',
    'FINLAND': 'FI', 'FRANCE': 'FR', 'GERMANY': 'DE', 'GREECE': 'GR',
    'HUNGARY': 'HU', 'ICELAND': 'IS', 'IRELAND': 'IE', 'ITALY': 'IT',
    'LATVIA': 'LV', 'LITHUANIA': 'LT', 'LUXEMBOURG': 'LU', 'MALTA': 'MT',
    'NETHERLANDS': 'NL', 'NORWAY': 'NO', 'POLAND': 'PL', 'PORTUGAL': 'PT',
    'ROMANIA': 'RO', 'SLOVAKIA': 'SK', 'SLOVENIA': 'SI', 'SPAIN': 'ES',
    'SWEDEN': 'SE', 'SWITZERLAND': 'CH', 'UNITED KINGDOM': 'GB',
}


class AceaCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('acea', None)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': CURL_UA,
            'Accept': '*/*',
        })
        self._brand_cache = {}

    def _fetch(self, url, timeout=60, post=None):
        for attempt in range(3):
            try:
                if post:
                    r = self.session.post(url, data=post, timeout=timeout)
                else:
                    r = self.session.get(url, timeout=timeout)
                if r.status_code == 200:
                    return r
            except Exception as e:
                print(f'_fetch {url} err: {e}')
            time.sleep(2)
        return None

    def discover_release_articles(self, search='registrations', max_pages=5):
        """ACEA AJAX 接口枚举月度 release 文章。返回 [(permalink, title, date_str), ...]"""
        articles = []
        for page in range(1, max_pages + 1):
            post = {
                'action': 'load_results',
                'filters[content][]': 'news',
                'filters[search]': search,
                'filters[pageNumber]': str(page),
                'filters[orderby]': 'date',
            }
            r = self._fetch(ACEA_AJAX, timeout=60, post=post)
            if not r:
                break
            try:
                data = r.json()
            except Exception:
                break
            posts = data.get('posts', [])
            if not posts:
                break
            for p in posts:
                articles.append((p.get('permalink', ''), p.get('title', ''), p.get('date', '')))
            if page >= data.get('numPages', 1):
                break
            time.sleep(0.5)
        return articles

    def find_pdf_url(self, article_html):
        """从 release 页面找 PDF 数据文件链接。"""
        pat = re.compile(r'href="([^"]+\.pdf[^"]*)"', re.I)
        for href in pat.findall(article_html):
            if 'acea' in href.lower() or 'press' in href.lower() or '/files/' in href:
                if href.startswith('http'):
                    return href
                return ACEA_BASE + href
        # fallback 任意 pdf
        for href in pat.findall(article_html):
            if href.startswith('http'):
                return href
            return ACEA_BASE + href
        return None

    def parse_power_table(self, pdf_bytes):
        """坐标方案解析 'NEW CAR REGISTRATIONS BY MARKET AND POWER SOURCE' 表。
        返回 (records, period_type) records=[(country, power, qty_2026), ...]
        period_type='MONTHLY'/'YTD'
        """
        import pdfplumber
        records = []
        period_type = None
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                words = page.extract_words()
                # 识别 period_type: 页面文本含 YEAR TO DATE -> YTD, 否则 MONTHLY
                page_text = ' '.join(w['text'] for w in words).upper()
                if 'YEAR TO DATE' in page_text:
                    pt = 'YTD'
                else:
                    pt = 'MONTHLY'
                # 找 BATTERY ELECTRIC 表头(标题行下方的表头)
                be_words = [w for w in words if w['text'].upper() in ('BATTERY', 'BATTERYELECTRIC')]
                if not be_words:
                    continue
                be_top = be_words[0]['top']
                # 找 2026 子表头行 (top 在 be_top 下方)
                # 动态年份: 当年PDF子表头是当前年份(2026/2025/2024...), 每组(当年/去年/%change)取第一个年份
                y2026 = [w for w in words if re.match(r'^20\d\d$', w['text']) and w['top'] > be_top - 5]
                if len(y2026) < 14:
                    continue
                # 年份word成对出现[当年,去年]×7动力, 取每对第一个(当年)为列中心
                y2026.sort(key=lambda w: w['x0'])
                col_centers = [y2026[i]['x0'] for i in range(0, 14, 2)][:7]
                # 数据行: top > y2026[0].top
                data_top = min(w['top'] for w in y2026)
                data_words = [w for w in words if w['top'] > data_top + 1]
                # 按 top 聚类行
                rows = []
                cur = []
                cur_top = None
                for w in sorted(data_words, key=lambda w: (w['top'], w['x0'])):
                    if cur_top is None:
                        cur = [w]
                        cur_top = w['top']
                    elif abs(w['top'] - cur_top) < 3:
                        cur.append(w)
                        cur_top = max(cur_top, w['top'])
                    else:
                        rows.append(cur)
                        cur = [w]
                        cur_top = w['top']
                if cur:
                    rows.append(cur)
                # 每行: 国家名 + 7列各取距列中心最近的数字
                for row in rows:
                    row_sorted = sorted(row, key=lambda w: w['x0'])
                    # 国家名 = 最左字母 word
                    name_parts = []
                    num_words = []
                    for w in row_sorted:
                        if re.match(r'^[A-Za-z]$', w['text']):
                            # 单字母可能属于国家名或表头
                            name_parts.append(w['text'])
                        elif re.match(r'^[A-Za-z]', w['text']):
                            name_parts.append(w['text'])
                        else:
                            num_words.append(w)
                    country = ' '.join(name_parts).strip()
                    if not country or len(country) < 3:
                        continue
                    if country in ('BATTERY', 'PLUG', 'HYBRID', 'OTHERS', 'PETROL', 'DIESEL', 'TOTAL'):
                        continue
                    # 每列取距 col_center 最近的数字 word
                    vals = {}
                    for ci, cc in enumerate(col_centers):
                        best = None
                        best_d = 999
                        for w in num_words:
                            d = abs(w['x0'] - cc)
                            if d < best_d:
                                best_d = d
                                best = w
                        if best and best_d < 60:
                            txt = best['text'].replace(',', '').replace('.', '').replace('ꟷ', '').replace('−', '-')
                            try:
                                vals[ci] = int(txt)
                            except ValueError:
                                vals[ci] = None
                            num_words.remove(best)
                    if country.upper() in AGGREGATE_ROWS or country in ('EU + EFTA + UK',):
                        # 汇总行, 保留但标记
                        pass
                    for ci, label in enumerate(POWER_COLS):
                        if ci in vals and vals[ci] is not None:
                            records.append((country, label, vals[ci], pt))
        return records, period_type

    def save_record(self, country, power_label, qty, y, m, period_type):
        """写 market_sales_monthly (ACEA 汇总维度, brand=NULL)。"""
        if country.upper() in ('EUROPEAN UNION', 'EU14', 'EU12', 'EFTA'):
            cc_code = 'EU'
        elif country.upper() == 'UNITED KINGDOM':
            cc_code = 'GB'
        elif country.upper() == 'EU + EFTA + UK':
            cc_code = 'EU'
        else:
            cc_code = ACEA_COUNTRY_MAP.get(country.upper(), 'EU')  # 国家全名→ISO
        # 汇总行用 data_source 区分, country_code 用原 ISO (EUROPEAN UNION 无法映射)
        energy = POWER_ENERGY.get(power_label)
        rec = {
            'country_code': cc_code,
            'source_month': date(y, m, 1),
            'brand_name_raw': country.upper(),
            'brand_id': None,
            'model_name': None,
            'vehicle_type': 'passenger',
            'energy_type': energy,
            'segment': None,
            'raw_unit': 'units',
            'sales_volume_raw': qty,
            'sales_volume_normalized': qty,
            'revision_no': 1,
            'is_latest': True,
            'pub_date': None,
            'crawl_time': datetime.now(),
            'data_source': 'acea',
            'notes': f'ACEA {period_type} {y}-{m} registrations by power source ({country})',
        }
        super().save_sales(rec)

    def crawl_article(self, url, y, m):
        """爬单篇月度 release (含当月 MONTHLY 表)。返回记录数。"""
        r = self._fetch(url)
        if not r:
            return 0
        pdf_url = self.find_pdf_url(r.text)
        if not pdf_url:
            return 0
        rp = self._fetch(pdf_url, timeout=90)
        if not rp or len(rp.content) < 10000:
            return 0
        records, period_type = self.parse_power_table(rp.content)
        if not records:
            return 0
        n = 0
        for country, power, qty, pt in records:
            # 只存 MONTHLY 单月值 (YTD 是衍生累计, 避免污染单月口径)
            if pt != 'MONTHLY':
                continue
            # 只存非汇总国家行
            if country.upper() in AGGREGATE_ROWS or country == 'EU + EFTA + UK' or 'EU EFTA' in country:
                continue
            if 'acea.auto' in country.lower() or 'PAGE' in country.upper():
                continue
            self.save_record(country, power, qty, y, m, pt)
            n += 1
        return n

    def parse_month_from(self, text):
        """从 slug/title 解析数据年月 (如 'in-may-2026'→(2026,5))"""
        for i, mon in enumerate(['january', 'february', 'march', 'april', 'may', 'june',
                                 'july', 'august', 'september', 'october', 'november', 'december'], 1):
            pat = rf'\b{mon}\b[\s\-/]*(\d{{4}})'
            m = re.search(pat, text, re.I)
            if m:
                return int(m.group(1)), i
        return None

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE data_source='acea'")
        row = cur.fetchone()
        m = row['m'] if isinstance(row, dict) else row[0]
        return m.date() if hasattr(m, 'date') else m

    def crawl_incremental(self, max_pages=40):
        """从最新月度 release 往回爬, 只处理比库中 MAX month 新的文章。返回记录数。"""
        from datetime import date as _date
        max_m = self._get_db_max_month()
        articles = self.discover_release_articles(search='registrations', max_pages=max_pages)
        saved = 0
        seen = set()
        for permalink, title, _date in articles:
            if 'pc-registrations' not in permalink:
                continue
            if permalink in seen:
                continue
            seen.add(permalink)
            ym = self.parse_month_from(permalink)
            if not ym:
                continue
            y, m = ym
            if max_m is not None and _date(y, m, 1) <= max_m:
                break  # 文章按日期倒序, 遇到不新的即可停
            try:
                n = self.crawl_article(permalink, y, m)
                saved += n
                print(f'ACEA {y}-{m:02d}: saved {n}')
            except Exception as e:
                print(f'ACEA {y}-{m:02d}: ERROR {e}')
            time.sleep(1)
        return saved


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--incremental', action='store_true')
    ap.add_argument('--test', action='store_true')
    args = ap.parse_args()

    c = AceaCrawler()
    if args.test:
        articles = c.discover_release_articles(max_pages=1)
        print('articles:', len(articles))
        for a in articles[:5]:
            print(a)
    elif args.incremental:
        # 探测最新月度 release, 解析入库
        articles = c.discover_release_articles(max_pages=2)
        print('total articles:', len(articles))
        # 找最新的 PC release (含月份)
        for url, title, d in articles[:20]:
            print(url, '|', title[:60], '|', d)


if __name__ == '__main__':
    main()
