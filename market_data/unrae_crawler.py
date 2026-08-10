# -*- coding: utf-8 -*-
"""
UNRAE 意大利汽车销量爬虫
从UNRAE官网下载最新PDF并解析入库
"""
import os
import sys
import re
import time
import random
import logging
import requests
from datetime import datetime, date
from bs4 import BeautifulSoup
import pdfplumber
import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_CONFIG = {
    'host': 'pgm-bp1sf8zujdx18698io.pg.rds.aliyuncs.com',
    'port': 5432,
    'user': 'Levin001',
    'password': 'Li800124',
    'dbname': 'guobiezhinan'
}

UA_LIST = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
]

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'unrae_pdf')
os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('crawler_unrae.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('unrae')


class UNRAECrawler:
    def __init__(self):
        self.source_name = 'UNRAE'
        self.country_code = 'IT'
        self.conn = None
        self.cur = None
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': random.choice(UA_LIST),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8',
        })

    def get_connection(self):
        if not self.conn:
            self.conn = psycopg2.connect(**DB_CONFIG)
            self.conn.autocommit = False
            self.cur = self.conn.cursor(cursor_factory=RealDictCursor)
        return self.conn, self.cur

    def close(self):
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()
        self.conn = None
        self.cur = None

    def find_latest_pdf(self):
        """
        从UNRAE sitemap获取最新的汽车市场数据PDF链接
        """
        logger.info('=== 搜索最新UNRAE PDF ===')
        
        try:
            resp = self.session.get('https://www.unrae.it/sitemap.xml', timeout=15)
            if resp.status_code != 200:
                logger.error(f'sitemap请求失败: {resp.status_code}')
                return None, None
        except Exception as e:
            logger.error(f'sitemap请求异常: {e}')
            return None, None

        urls = re.findall(r'<loc>(.*?)</loc>', resp.text)
        
        # 找汽车市场相关URL（按时间倒序）
        auto_urls = [u for u in urls if 'sala-stampa/autovetture' in u]
        if not auto_urls:
            logger.error('未找到autovetture相关URL')
            return None, None

        # 按URL中的ID数字排序（越大越新）
        auto_urls.sort(key=lambda x: int(re.search(r'/(\d+)/', x).group(1)) if re.search(r'/(\d+)/', x) else 0, reverse=True)
        
        latest_url = auto_urls[0]
        logger.info(f'最新新闻URL: {latest_url}')

        # 访问新闻页面获取PDF链接
        try:
            resp = self.session.get(latest_url, timeout=15)
            if resp.status_code != 200:
                logger.error(f'新闻页面请求失败: {resp.status_code}')
                return None, None
        except Exception as e:
            logger.error(f'新闻页面请求异常: {e}')
            return None, None

        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 找PDF下载链接
        pdf_url = None
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '.pdf' in href.lower() and 'comunicato' in href.lower():
                if href.startswith('http'):
                    pdf_url = href
                else:
                    pdf_url = f'https://www.unrae.it{href}'
                break

        if not pdf_url:
            # 备选：搜索页面文本中的PDF URL
            pdfs = re.findall(r'https?://[^"<>\']+?\.pdf[^"<>\']*', resp.text, re.IGNORECASE)
            if pdfs:
                pdf_url = pdfs[0]

        if not pdf_url:
            logger.error('未找到PDF下载链接')
            return None, None

        logger.info(f'找到PDF: {pdf_url}')
        
        # 从文件名提取月份和年份
        match = re.search(r'(Gennaio|Febbraio|Marzo|Aprile|Maggio|Giugno|Luglio|Agosto|Settembre|Ottobre|Novembre|Dicembre)\s+(\d{4})', pdf_url)
        if match:
            month_it = match.group(1)
            year = int(match.group(2))
            month_map = {
                'Gennaio': 1, 'Febbraio': 2, 'Marzo': 3, 'Aprile': 4,
                'Maggio': 5, 'Giugno': 6, 'Luglio': 7, 'Agosto': 8,
                'Settembre': 9, 'Ottobre': 10, 'Novembre': 11, 'Dicembre': 12
            }
            month = month_map.get(month_it)
            source_month = date(year, month, 1)
            logger.info(f'数据月份: {source_month}')
        else:
            # 从URL ID或当前时间推断
            now = datetime.now()
            # 默认上个月
            if now.month == 1:
                source_month = date(now.year - 1, 12, 1)
            else:
                source_month = date(now.year, now.month - 1, 1)
            logger.warning(f'无法从URL提取月份，使用默认: {source_month}')

        return pdf_url, source_month

    def download_pdf(self, pdf_url, source_month):
        """下载PDF文件"""
        logger.info(f'=== 下载PDF ===')
        logger.info(f'URL: {pdf_url}')
        
        try:
            resp = self.session.get(pdf_url, timeout=30)
            if resp.status_code != 200:
                logger.error(f'下载失败: HTTP {resp.status_code}')
                return None
        except Exception as e:
            logger.error(f'下载异常: {e}')
            return None

        filename = f'unrae_{source_month.strftime("%Y%m")}.pdf'
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, 'wb') as f:
            f.write(resp.content)
        
        logger.info(f'下载成功: {filepath} ({len(resp.content):,}字节)')
        return filepath

    def parse_pdf(self, filepath):
        """
        解析UNRAE PDF文件，提取能源类型数据（主数据）
        
        注意：只提取能源类型数据，用途数据为同一维度的不同分类，不重复存储
        
        PDF结构:
        - 第6页: 能源类型数据（ALIMENTAZIONI）
        """
        logger.info(f'=== 解析PDF: {filepath} ===')
        
        records = []
        
        with pdfplumber.open(filepath) as pdf:
            logger.info(f'总页数: {len(pdf.pages)}')
            
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ''
                
                # 只提取能源类型数据页（主数据）
                if 'ALIMENTAZIONI' in page_text and 'VOLUMI' in page_text:
                    logger.info(f'  第{i+1}页: 发现能源类型数据')
                    energy_records = self._parse_energy_page(page_text)
                    records.extend(energy_records)

        logger.info(f'解析完成，共 {len(records)} 条记录')
        return records

    def _parse_energy_page(self, page_text):
        """
        解析能源类型页面
        
        格式示例:
        ALIMENTAZIONI
        LUGLIO 2026
        VOLUMI 23.781 8.038 13.301 0 59.420 13.103 7.368 0
        QUOTE 19,0% 6,4% 10,6% 0,0% 47,5% 10,5% 5,9% 0,0%
        
        列顺序: Benzina Diesel GPL Metano Ibride PHEV BEV Idrogeno
        """
        records = []
        
        # 提取VOLUMI行
        volumi_match = re.search(r'VOLUMI\s+([\d\.\s]+)', page_text)
        
        if not volumi_match:
            return records

        # 解析VOLUMI数值（千分位分隔符.需要移除）
        volumi_str = volumi_match.group(1).strip()
        volumes = []
        for v in volumi_str.split():
            try:
                volumes.append(int(v.replace('.', '')))
            except ValueError:
                volumes.append(0)

        # 能源类型列映射（按位置）
        energy_types = ['ice_petrol', 'ice_diesel', 'ice_lpg', 'ice_methane', 
                       'hev', 'phev', 'bev', 'fcev']
        
        for energy_type, volume in zip(energy_types, volumes):
            if volume > 0:
                records.append({
                    'energy_type': energy_type,
                    'volume': volume,
                })

        logger.info(f'  能源类型数据: {len(records)} 种能源类型, 总销量: {sum(r["volume"] for r in records):,}')
        return records

    def save_records(self, records, source_month):
        """将解析的数据入库"""
        logger.info(f'=== 入库 {len(records)} 条记录 ===')
        
        conn, cur = self.get_connection()
        inserted = 0
        updated = 0

        for record_data in records:
            energy_type = record_data['energy_type']
            volume = record_data['volume']
            
            record = {
                'country_code': self.country_code,
                'source_month': source_month,
                'brand_name_raw': 'UNRAE_TOTAL',
                'brand_id': None,
                'model_name': None,
                'vehicle_type': 'passenger',
                'energy_type': energy_type,
                'segment': None,
                'raw_unit': 'unit',
                'sales_volume_raw': volume,
                'sales_volume_normalized': volume,
                'revision_no': 1,
                'is_latest': True,
                'pub_date': source_month,
                'crawl_time': datetime.now(),
                'data_source': self.source_name,
                'notes': f'UNRAE PDF {source_month.strftime("%Y-%m")} {energy_type}'
            }

            try:
                # 检查是否存在
                cur.execute("""
                    SELECT id FROM market_sales_monthly
                    WHERE country_code = %(country_code)s
                      AND source_month = %(source_month)s
                      AND brand_name_raw = %(brand_name_raw)s
                      AND model_name IS NOT DISTINCT FROM %(model_name)s
                      AND energy_type IS NOT DISTINCT FROM %(energy_type)s
                      AND revision_no = %(revision_no)s
                    LIMIT 1
                """, record)
                existing = cur.fetchone()

                if existing:
                    cur.execute("""
                        UPDATE market_sales_monthly SET
                            sales_volume_raw = %(sales_volume_raw)s,
                            sales_volume_normalized = %(sales_volume_normalized)s,
                            is_latest = %(is_latest)s,
                            crawl_time = %(crawl_time)s,
                            notes = %(notes)s
                        WHERE id = %(id)s
                    """, {**record, 'id': existing['id']})
                    updated += 1
                else:
                    cur.execute("""
                        INSERT INTO market_sales_monthly
                            (country_code, source_month, brand_name_raw, brand_id,
                             model_name, vehicle_type, energy_type, segment,
                             raw_unit, sales_volume_raw, sales_volume_normalized,
                             revision_no, is_latest, pub_date, crawl_time,
                             data_source, notes)
                        VALUES
                            (%(country_code)s, %(source_month)s, %(brand_name_raw)s, %(brand_id)s,
                             %(model_name)s, %(vehicle_type)s, %(energy_type)s, %(segment)s,
                             %(raw_unit)s, %(sales_volume_raw)s, %(sales_volume_normalized)s,
                             %(revision_no)s, %(is_latest)s, %(pub_date)s, %(crawl_time)s,
                             %(data_source)s, %(notes)s)
                    """, record)
                    inserted += 1

            except Exception as e:
                logger.error(f'入库失败 {source_month} {energy_type}: {e}')
                conn.rollback()

        conn.commit()
        logger.info(f'入库完成: 新增 {inserted}, 更新 {updated}')
        return inserted, updated

    def run(self):
        """主运行流程"""
        logger.info('=' * 60)
        logger.info('UNRAE 意大利汽车销量爬虫启动')
        logger.info('=' * 60)

        # 1. 找最新PDF
        pdf_url, source_month = self.find_latest_pdf()
        if not pdf_url:
            logger.error('未找到PDF链接，退出')
            return False

        # 2. 下载PDF
        pdf_path = self.download_pdf(pdf_url, source_month)
        if not pdf_path:
            logger.error('PDF下载失败，退出')
            return False

        # 3. 解析PDF
        records = self.parse_pdf(pdf_path)
        if not records:
            logger.warning('未解析到任何数据')
            return False

        # 4. 入库
        self.save_records(records, source_month)

        # 5. 验证
        self.verify(source_month)

        logger.info('爬虫运行完成')
        return True

    def verify(self, source_month):
        """验证入库数据"""
        conn, cur = self.get_connection()
        
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(sales_volume_normalized) as total_volume
            FROM market_sales_monthly
            WHERE country_code = 'IT' 
              AND data_source = 'UNRAE'
              AND source_month = %s
        """, (source_month,))
        row = cur.fetchone()
        logger.info(f'\n=== 数据验证 ({source_month}) ===')
        logger.info(f'  记录数: {row["total"]}')
        logger.info(f'  总销量: {row["total_volume"]:,}')

        cur.execute("""
            SELECT energy_type, sales_volume_normalized
            FROM market_sales_monthly
            WHERE country_code = 'IT' 
              AND data_source = 'UNRAE'
              AND source_month = %s
            ORDER BY sales_volume_normalized DESC
        """, (source_month,))
        logger.info('  明细:')
        for r in cur.fetchall():
            logger.info(f'    {r["energy_type"]:25s}: {r["sales_volume_normalized"]:>10,} 辆')


if __name__ == '__main__':
    crawler = UNRAECrawler()
    try:
        success = crawler.run()
        sys.exit(0 if success else 1)
    finally:
        crawler.close()