# -*- coding: utf-8 -*-
"""
DK 丹麦汽车月度销量爬虫
数据源: https://mobility.dk/nyregistreringer/ (Mobility Denmark, 原 De Danske Bilimportører)
数据类型: 品牌级乘用车新注册 (Nyregistreringer, Personbiler)
数据来源: Motorstyrelsen / Mobility Denmark

站点结构:
- 入口: https://mobility.dk/nyregistreringer/ (服务端渲染品牌表 + selectPeriod/selectType/selectView)
- AJAX: https://mobility.dk/wp-admin/admin-ajax.php
  - period_fetch: action=period_fetch&period=X&type=car -> <span>01/07 - 31/07/2026</span> (明确单月区间)
  - test_fetch: action=test_fetch&period=X&type=car&view=brands -> 品牌表HTML
- selectPeriod: now(YTD)/last_month(单月)/prev_month(单月)/last_year(全年)/prev_year(全年)
- selectType: car/van/truck/bus; selectView: brands/models

品牌表HTML结构 (period=last_month, view=brands):
- 表头行1: [标题"Nyregistrerede personbiler pr. mærke", 期间(如 1. July 2026 til 31. July 2026), 去年同期]
- 表头行2: [Mærke, Antal, Andel, Antal, Andel]
- 数据行: [品牌, 销量, 份额%, 去年销量, 去年份额%] (85行=1标题+1表头+83品牌)

增量策略:
- latest_available_month(): 从 selectPeriod 的 last_month 选项文本或 period_fetch 提取最新单月 (year, month)
- crawl_incremental(): 探测最新月 > 库中MAX 则抓取 last_month 品牌表入库
"""
import sys
sys.path.insert(0, '.')
import re
import logging
import requests
from datetime import datetime, date
from bs4 import BeautifulSoup
from base_crawler import BaseCrawler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)

DK_BASE_URL = 'https://mobility.dk'
DK_LIST_URL = f'{DK_BASE_URL}/nyregistreringer/'
DK_AJAX_URL = f'{DK_BASE_URL}/wp-admin/admin-ajax.php'

# 丹麦语月份名 -> 月份
DK_MONTH_MAP = {
    'januar': 1, 'februar': 2, 'marts': 3, 'april': 4, 'maj': 5,
    'juni': 6, 'juli': 7, 'august': 8, 'september': 9, 'oktober': 10,
    'november': 11, 'december': 12,
}
# 英文月份名(HTML标题用) -> 月份
EN_MONTH_MAP = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5,
    'june': 6, 'july': 7, 'august': 8, 'september': 9, 'october': 10,
    'november': 11, 'december': 12,
}

# 聚合/总量行 (品牌级数据行不会出现，保守跳过)
SKIP_BRANDS = ('TOTAL', 'I ALT', 'ALLE', 'ØVRIGE', 'OVRIGE')


def _to_int(value):
    """安全整数转换: 处理点号千分位(机器可读)/逗号/空格/百分比"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # 纯数字: 去掉点号(丹麦千分位)与逗号
    s = s.replace(',', '').replace(' ', '').replace('%', '')
    if not re.fullmatch(r'[\d.\-]+', s):
        return None
    try:
        return int(float(s.replace('.', '')))
    except (ValueError, TypeError):
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return None


class DenmarkCrawler(BaseCrawler):
    """Mobility Denmark 丹麦汽车销量爬虫"""

    def __init__(self):
        super().__init__(source_name='mobilitydenmark', country_code='DK')
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'da-DK,da;q=0.9,en;q=0.8',
        }
        self.session = requests.Session()

    # ---------- 最新月份探测 ----------
    def latest_available_month(self):
        """探测最新单月数据月份, 返回 (year, month) 或 None

        从首页 selectPeriod 的 last_month 选项文本 (如 '1. juli - 31. juli 2026')
        或 period_fetch AJAX (01/07 - 31/07/2026) 提取。
        """
        # 方式1: 首页 selectPeriod 选项
        try:
            resp = self.session.get(DK_LIST_URL, headers=self.headers, timeout=30)
            if resp.status_code == 200:
                resp.encoding = resp.apparent_encoding
                soup = BeautifulSoup(resp.text, 'html.parser')
                sel = soup.find('select', {'id': 'selectPeriod'})
                if sel:
                    for opt in sel.find_all('option'):
                        if opt.get('value') == 'last_month':
                            txt = opt.get_text(strip=True)
                            m = re.search(r'(\d{1,2})\.\s*([a-zæøå]+)\s*-\s*\d{1,2}\.\s*[a-zæøå]+\s*(\d{4})', txt, re.I)
                            if m:
                                month = DK_MONTH_MAP.get(m.group(2).lower())
                                year = int(m.group(3))
                                if month:
                                    self.logger.info(f'DK 最新单月(首页): {year}-{month:02d}')
                                    return (year, month)
        except Exception as e:
            self.logger.error(f'DK 首页探测失败: {e}')

        # 方式2: period_fetch AJAX (返回 01/07 - 31/07/2026)
        try:
            resp = self.session.post(DK_AJAX_URL, data={
                'action': 'period_fetch', 'period': 'last_month', 'type': 'car'
            }, headers=self.headers, timeout=30)
            if resp.status_code == 200:
                m = re.search(r'(\d{2})/(\d{2})\s*-\s*\d{2}/(\d{2})/(\d{4})', resp.text)
                if m:
                    d1, m1, d2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    self.logger.info(f'DK 最新单月(ajax): {y2}-{m2:02d}')
                    return (y2, m2)
        except Exception as e:
            self.logger.error(f'DK period_fetch 失败: {e}')

        return None

    # ---------- 品牌表抓取 ----------
    def fetch_brand_table(self, period='last_month', type_code='car'):
        """抓取品牌表, 返回 [(brand, qty, share, qty_ly, share_ly)]"""
        rows = []
        resp = self.session.post(DK_AJAX_URL, data={
            'action': 'test_fetch', 'period': period, 'type': type_code, 'view': 'brands'
        }, headers=self.headers, timeout=60)
        if resp.status_code != 200:
            self.logger.error(f'DK test_fetch 失败: HTTP {resp.status_code}')
            return rows
        soup = BeautifulSoup(resp.text, 'html.parser')
        tables = soup.find_all('table')
        if not tables:
            self.logger.warning('DK 品牌表未找到 table')
            return rows
        for tr in tables[0].find_all('tr'):
            cells = []
            for td in tr.find_all(['td', 'th']):
                dv = td.get('data-value')
                cells.append(dv if dv is not None else td.get_text(strip=True))
            if len(cells) < 2:
                continue
            brand = str(cells[0]).strip()
            # 跳过表头与聚合行
            if not brand or brand.upper() in SKIP_BRANDS:
                continue
            if brand in ('Mærke',) or brand.lower().startswith('nyregistrerede'):
                continue
            qty = _to_int(cells[1])
            if qty is None:
                continue
            share = _to_int(cells[2])
            qty_ly = _to_int(cells[3]) if len(cells) > 3 else None
            rows.append((brand, qty, share, qty_ly))
        return rows

    # ---------- 品牌匹配 ----------
    def get_brand_id(self, brand_name):
        """UPPER匹配 canonical_name/brand_name_cn, variant回退"""
        lookup = str(brand_name).strip().upper()
        try:
            conn, cur = self.get_connection()
            cur.execute("""
                SELECT id FROM brand_name_mapping
                WHERE UPPER(canonical_name) = %s OR UPPER(brand_name_cn) = %s
                LIMIT 1
            """, (lookup, lookup))
            row = cur.fetchone()
            if row:
                return row['id']
            cur.execute("""
                SELECT brand_id FROM brand_name_variant
                WHERE UPPER(variant_name) = %s
                LIMIT 1
            """, (lookup,))
            row = cur.fetchone()
            if row:
                return row['brand_id']
        except Exception as e:
            self.logger.error(f'品牌ID查询失败: {e}')
        return None

    def save_sales(self, record):
        record['brand_id'] = self.get_brand_id(record['brand_name_raw'])
        return super().save_sales(record)

    # ---------- 主流程 ----------
    def crawl_month(self, year, month):
        """抓取指定单月数据 (mobility.dk 只保留最近几个月, 历史月份可能不可得)"""
        # 先确认站点当前数据是否为 (year, month)
        latest = self.latest_available_month()
        if latest is None:
            return {'records': 0, 'msg': 'latest month probe failed'}
        ly, lm = latest
        if (ly, lm) != (year, month):
            self.logger.info(f'DK 站点最新单月为 {ly}-{lm:02d}, 目标 {year}-{month:02d} 跳过')
            return {'records': 0, 'msg': f'latest is {ly}-{lm:02d}'}

        rows = self.fetch_brand_table(period='last_month', type_code='car')
        saved = 0
        for brand, qty, share, qty_ly in rows:
            record = {
                'country_code': 'DK',
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
                'data_source': 'mobilitydenmark',
                'notes': 'Mobility Denmark nyregistreringer personbiler (mærke)',
            }
            if self.save_sales(record):
                saved += 1
        self.logger.info(f'DK {year}-{month:02d} 保存 {saved} 条')
        return {'records': saved}

    def crawl_incremental(self):
        """增量爬取: 探测最新月 > 库中MAX 则抓取"""
        max_month = self._get_db_max_month()
        latest = self.latest_available_month()
        if latest is None:
            return 0
        ly, lm = latest
        latest_date = date(ly, lm, 1)
        if max_month is not None and latest_date <= max_month:
            self.logger.info(f'DK 最新 {latest_date} <= 库中 {max_month}, 无新数据')
            return 0
        res = self.crawl_month(ly, lm)
        return res.get('records', 0)

    def _get_db_max_month(self):
        try:
            conn, cur = self.get_connection()
            cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='DK' AND data_source='mobilitydenmark'")
            row = cur.fetchone()
            return row['m'] if row else None
        except Exception as e:
            self.logger.error(f'库中DK MAX查询失败: {e}')
            return None


def main():
    """主函数: 爬取丹麦KAMA数据"""
    crawler = DenmarkCrawler()
    saved = crawler.crawl_incremental()
    print(f'DK 增量爬取完成, 新增 {saved} 条')


if __name__ == '__main__':
    main()
