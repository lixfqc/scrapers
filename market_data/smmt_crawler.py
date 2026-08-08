# -*- coding: utf-8 -*-
"""
SMMT 英国汽车销量爬虫（含车型级解析）
- 复用 kba_crawler.py 中的 BaseCrawler 基类
- 解析品牌级数据（By Brand表）
- 解析车型级数据（Top 10 + BEV Top 10）

用法:
  python smmt_crawler.py                  # 爬取最新月份（品牌级+车型级）
  python smmt_crawler.py --brand-only     # 仅爬取品牌级
"""
import os
import sys
import re
from datetime import datetime, date
from bs4 import BeautifulSoup
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kba_crawler import BaseCrawler

# 英文月份 3 字母 → 数字
MONTH_MAP = {m: i for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
     'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}

# 非真实品牌的聚合行
SKIP_BRANDS = {
    'MARQUE', 'TOTAL', 'GRAND TOTAL', 'TOTAL UK',
    'OTHERS', 'OTHER', 'OTHER BRITISH', 'OTHER IMPORTS',
}


class SMMTCrawler(BaseCrawler):
    def __init__(self):
        super().__init__('SMMT', 'GB')
        self.page_url = 'https://www.smmt.co.uk/vehicle-data/car-registrations/'
        self.session = requests.Session()
        headers = self.get_headers()
        headers['Accept-Encoding'] = 'gzip, deflate'
        self.session.headers.update(headers)

    def crawl_latest(self, include_model=True):
        """爬取最新月份数据，支持品牌级+车型级"""
        self.logger.info('开始爬取 SMMT 最新月度数据')
        self.random_delay()

        resp = self.retry_request(self.session.get, self.page_url, timeout=30)
        if not resp:
            return False, 0

        try:
            soup = BeautifulSoup(resp.text, 'html.parser')
            source_month = self._extract_source_month(soup)
            if source_month is None:
                source_month = datetime.now().replace(day=1).date()
                self.logger.warning('未解析到数据月份，回退当前月')
            self.logger.info(f'数据月份: {source_month}')

            # 1. 品牌级
            brand_records = self._parse_brand_table(soup, source_month)
            brand_saved = sum(1 for r in brand_records if self.save_sales(r))
            self.logger.info(f'品牌级: 解析 {len(brand_records)} 条，入库 {brand_saved} 条')

            # 2. 车型级
            model_saved = 0
            if include_model:
                model_records = self._parse_model_tables(soup, source_month)
                model_saved = sum(1 for r in model_records if self.save_sales(r))
                self.logger.info(f'车型级: 解析 {len(model_records)} 条，入库 {model_saved} 条')

            self.page_count += 1
            self.batch_restart()

            # 标记最新数据
            self._mark_latest(source_month, include_model)
            return brand_saved > 0 or model_saved > 0, model_saved

        except Exception as e:
            self.logger.error(f'页面解析失败: {e}')
            return False, 0

    def _extract_source_month(self, soup):
        """从页面提取数据月份（品牌表表头）"""
        month_re = re.compile(
            r'\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|'
            r'jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|'
            r'nov(?:ember)?|dec(?:ember)?)\b', re.I)

        tables = soup.find_all('table')
        for table in tables:
            text = table.get_text(' ', strip=True).upper()
            if 'MARQUE' not in text or 'YEAR-TO-DATE' in text:
                continue

            year = None
            month_num = None
            for tr in table.find_all('tr')[:4]:
                cells = [td.get_text(' ', strip=True) for td in tr.find_all(['td', 'th'])]
                if not cells:
                    continue
                if cells[0].upper() == 'MARQUE':
                    for cell in cells[1:]:
                        m = re.match(r'^(20\d{2})$', cell)
                        if m:
                            year = int(m.group(1))
                            break
                    continue
                for cell in cells:
                    m = month_re.search(cell)
                    if m:
                        month_num = MONTH_MAP.get(m.group(0).lower()[:3])

            if month_num and year:
                return date(year, month_num, 1)
        return None

    def _parse_brand_table(self, soup, source_month):
        """解析品牌级数据"""
        records = []
        tables = soup.find_all('table')
        brand_table = None
        for table in tables:
            text = table.get_text(' ', strip=True).upper()
            if 'MARQUE' in text and 'YEAR-TO-DATE' not in text:
                brand_table = table
                break

        if brand_table is None:
            self.logger.warning('未找到 By Brand 表')
            return records

        for tr in brand_table.find_all('tr'):
            cells = [td.get_text(' ', strip=True) for td in tr.find_all(['td', 'th'])]
            if not cells:
                continue

            brand_raw = cells[0]
            if not brand_raw or brand_raw.upper() in SKIP_BRANDS:
                continue
            if len(cells) < 2:
                continue

            try:
                volume = int(re.sub(r'[^\d]', '', cells[1]))
            except Exception:
                continue
            if volume <= 0:
                continue

            brand_id = self._match_brand(brand_raw)
            record = {
                'country_code': 'GB',
                'source_month': source_month,
                'brand_name_raw': brand_raw,
                'brand_id': brand_id,
                'model_name': None,
                'vehicle_type': 'passenger',
                'energy_type': 'unknown',
                'segment': None,
                'raw_unit': 'unit',
                'sales_volume_raw': volume,
                'sales_volume_normalized': volume,
                'revision_no': 1,
                'is_latest': True,
                'pub_date': datetime.now().date(),
                'crawl_time': datetime.now(),
                'data_source': 'SMMT',
                'notes': f'SMMT brand {source_month.strftime("%Y-%m")}',
            }
            records.append(record)

        return records

    def _parse_model_tables(self, soup, source_month):
        """
        解析车型级数据（Top 10综合 + Top 10 BEV）
        表7: Top 10综合 [排名, 车型名, 销量]
        表9: Top 10 BEV [车型名, 销量]
        """
        records = []
        tables = soup.find_all('table')

        # 找车型级表格（不含"MARQUE"的小表格）
        model_tables = []
        for table in tables:
            text = table.get_text(' ', strip=True).upper()
            if 'MARQUE' in text:
                continue
            rows = table.find_all('tr')
            if len(rows) >= 10 and len(rows) <= 15:
                model_tables.append(table)

        self.logger.info(f'发现 {len(model_tables)} 个车型级表格')

        for idx, table in enumerate(model_tables):
            is_bev = 'BEV' in table.get_text(' ', strip=True).upper()
            energy_type = 'bev' if is_bev else 'unknown'

            for tr in table.find_all('tr'):
                cells = [td.get_text(' ', strip=True) for td in tr.find_all(['td', 'th'])]
                if not cells:
                    continue

                # 判断列数格式
                if len(cells) >= 3:
                    # 3列格式: [排名, 车型名, 销量]
                    model_cell_idx = 1
                    volume_cell_idx = 2
                elif len(cells) == 2:
                    # 2列格式: [车型名, 销量]
                    model_cell_idx = 0
                    volume_cell_idx = 1
                else:
                    continue

                model_raw = cells[model_cell_idx]
                volume_str = cells[volume_cell_idx]

                # 跳过表头
                if any(kw in model_raw.upper() for kw in ['JULY', 'YEAR', 'TOP', 'FUEL', 'TYPE']):
                    continue

                try:
                    volume = int(re.sub(r'[^\d]', '', volume_str))
                except Exception:
                    continue
                if volume <= 0:
                    continue

                # 车型名格式: "BRAND model" (品牌+空格+车型名)
                # 品牌为首字母大写的第一个词
                parts = model_raw.split(' ', 1)
                if len(parts) < 2:
                    continue

                brand_raw = parts[0]
                model_name = parts[1]

                brand_id = self._match_brand(brand_raw)
                record = {
                    'country_code': 'GB',
                    'source_month': source_month,
                    'brand_name_raw': brand_raw,
                    'brand_id': brand_id,
                    'model_name': model_name,
                    'vehicle_type': 'passenger',
                    'energy_type': energy_type,
                    'segment': None,
                    'raw_unit': 'unit',
                    'sales_volume_raw': volume,
                    'sales_volume_normalized': volume,
                    'revision_no': 1,
                    'is_latest': True,
                    'pub_date': datetime.now().date(),
                    'crawl_time': datetime.now(),
                    'data_source': 'SMMT',
                    'notes': f'SMMT model {source_month.strftime("%Y-%m")} {"BEV" if is_bev else "Top10"}',
                }
                records.append(record)

        return records

    def _mark_latest(self, source_month, include_model):
        """标记最新月份"""
        conn, cur = self.get_connection()
        try:
            # 品牌级
            cur.execute("""
                UPDATE market_sales_monthly SET is_latest = FALSE
                WHERE country_code = 'GB' AND data_source = 'SMMT' AND model_name IS NULL
            """)
            cur.execute("""
                UPDATE market_sales_monthly SET is_latest = TRUE
                WHERE country_code = 'GB' AND data_source = 'SMMT'
                  AND source_month = %s AND model_name IS NULL
            """, (source_month,))

            # 车型级
            if include_model:
                cur.execute("""
                    UPDATE market_sales_monthly SET is_latest = FALSE
                    WHERE country_code = 'GB' AND data_source = 'SMMT' AND model_name IS NOT NULL
                """)
                cur.execute("""
                    UPDATE market_sales_monthly SET is_latest = TRUE
                    WHERE country_code = 'GB' AND data_source = 'SMMT'
                      AND source_month = %s AND model_name IS NOT NULL
                """, (source_month,))

            conn.commit()
        except Exception as e:
            conn.rollback()
            self.logger.error(f'标记最新失败: {e}')

    def run(self, months=1, brand_only=False):
        self.logger.info(f'SMMT 爬虫启动')
        include_model = not brand_only
        for i in range(months):
            self.logger.info(f'爬取第 {i+1}/{months} 次')
            self.crawl_latest(include_model=include_model)
        self.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='SMMT 英国销量爬虫')
    parser.add_argument('--brand-only', action='store_true', help='仅爬取品牌级数据')
    args = parser.parse_args()

    crawler = SMMTCrawler()
    crawler.run(months=1, brand_only=args.brand_only)