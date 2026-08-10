# -*- coding: utf-8 -*-
"""UNRAE历史PDF回爬脚本 - 直接构造已知URL模式"""
import requests
import re
import time
import json
import os
from datetime import datetime, date
from bs4 import BeautifulSoup
import pdfplumber
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

# 配置
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
]

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'unrae_pdf')
os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('crawler_unrae_history.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('unrae_history')

# 月份映射
MONTHS_IT = {
    1: 'Gennaio', 2: 'Febbraio', 3: 'Marzo', 4: 'Aprile',
    5: 'Maggio', 6: 'Giugno', 7: 'Luglio', 8: 'Agosto',
    9: 'Settembre', 10: 'Ottobre', 11: 'Novembre', 12: 'Dicembre'
}

# 已知有效的PDF URL（通过探测验证的链接格式）
# 格式: https://www.unrae.it/files/[序号]%20Comunicato%20Stampa%20UNRAE%20e%20Infografica%20Mercato%20Auto%20{月份}%20{年份}_{hash}.pdf

class UNRAEHistoryCrawler:
    def __init__(self):
        self.conn = None
        self.cur = None
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.pdf_urls = []

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

    def fetch_pdf_urls_from_sitemap(self):
        """从sitemap获取所有autovetture新闻页面，然后提取PDF链接"""
        logger.info('=== 从sitemap获取历史PDF链接 ===')
        
        # 获取sitemap
        resp = self.session.get('https://www.unrae.it/sitemap.xml', timeout=15)
        if resp.status_code != 200:
            logger.error(f'sitemap请求失败: {resp.status_code}')
            return
        
        urls = re.findall(r'<loc>(.*?)</loc>', resp.text)
        auto_urls = [u for u in urls if 'sala-stampa/autovetture' in u]
        logger.info(f'autovetture相关URL: {len(auto_urls)}')
        
        # 提取ID并筛选2024年以后的URL（ID > 某个阈值）
        # 根据已知数据：2026年7月ID=7748，2026年1月ID约=7600
        # 预估2024年1月ID约=7000左右
        auto_urls.sort(key=lambda x: int(re.search(r'/(\d+)/', x).group(1)) if re.search(r'/(\d+)/', x) else 0, reverse=True)
        
        # 只处理前50个URL（覆盖约4年）
        urls_to_check = auto_urls[:50]
        logger.info(f'将检查 {len(urls_to_check)} 个页面')
        
        for i, url in enumerate(urls_to_check):
            if i % 5 == 0:
                logger.info(f'进度: {i}/{len(urls_to_check)}')
            
            try:
                resp = self.session.get(url, timeout=10)
                if resp.status_code == 200:
                    # 找PDF链接
                    pdf_url = self._extract_pdf_from_page(resp.text)
                    if pdf_url:
                        # 提取年月
                        date_info = self._extract_date_from_url(pdf_url)
                        if date_info:
                            self.pdf_urls.append({
                                'url': pdf_url,
                                'year': date_info[0],
                                'month': date_info[1],
                            })
                            logger.info(f'  找到: {date_info[0]}-{date_info[1]:02d}: {pdf_url[:80]}')
            except Exception as e:
                logger.warning(f'  错误 {url}: {e}')
                continue
        
        # 按年月排序
        self.pdf_urls.sort(key=lambda x: (x['year'], x['month']))
        logger.info(f'共找到 {len(self.pdf_urls)} 个PDF链接')
        
        # 保存中间结果
        with open('unrae_pdf_links.json', 'w', encoding='utf-8') as f:
            json.dump(self.pdf_urls, f, ensure_ascii=False, indent=2)
        
        return self.pdf_urls

    def _extract_pdf_from_page(self, html):
        """从页面提取PDF链接"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # 优先查找comunicato相关PDF
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '.pdf' in href.lower() and ('comunicato' in href.lower() or 'mercato' in href.lower()):
                if href.startswith('http'):
                    return href
                else:
                    return f'https://www.unrae.it{href}'
        
        # 备选：搜索页面文本中的PDF URL
        pdfs = re.findall(r'https?://[^"<>\']+?\.pdf[^"<>\']*', html, re.IGNORECASE)
        for p in pdfs:
            if 'comunicato' in p.lower() or 'mercato' in p.lower() or 'auto' in p.lower():
                return p
        
        return None

    def _extract_date_from_url(self, url):
        """从PDF URL提取年月"""
        # 格式: ...{月份} {年份}_{hash}.pdf
        month_match = re.search(
            r'(Gennaio|Febbraio|Marzo|Aprile|Maggio|Giugno|Luglio|Agosto|Settembre|Ottobre|Novembre|Dicembre)\s+(\d{4})',
            url, re.IGNORECASE
        )
        if month_match:
            month_it = month_match.group(1)
            year = int(month_match.group(2))
            month_map = {
                'Gennaio': 1, 'Febbraio': 2, 'Marzo': 3, 'Aprile': 4,
                'Maggio': 5, 'Giugno': 6, 'Luglio': 7, 'Agosto': 8,
                'Settembre': 9, 'Ottobre': 10, 'Novembre': 11, 'Dicembre': 12
            }
            month = month_map.get(month_it)
            if month:
                return (year, month)
        return None

    def download_pdf(self, pdf_url, year, month):
        """下载PDF文件"""
        try:
            resp = self.session.get(pdf_url, timeout=30)
            if resp.status_code != 200:
                logger.error(f'下载失败: HTTP {resp.status_code}')
                return None
            
            filename = f'unrae_{year}{month:02d}.pdf'
            filepath = os.path.join(OUTPUT_DIR, filename)
            with open(filepath, 'wb') as f:
                f.write(resp.content)
            
            logger.info(f'  下载成功: {filename}')
            return filepath
        except Exception as e:
            logger.error(f'下载异常: {e}')
            return None

    def parse_pdf(self, filepath):
        """解析PDF文件，提取能源类型数据"""
        records = []
        
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ''
                
                # 只提取能源类型数据页
                if 'ALIMENTAZIONI' in page_text and 'VOLUMI' in page_text:
                    volumi_match = re.search(r'VOLUMI\s+([\d\.\s]+)', page_text)
                    if volumi_match:
                        volumi_str = volumi_match.group(1).strip()
                        volumes = []
                        for v in volumi_str.split():
                            try:
                                volumes.append(int(v.replace('.', '')))
                            except ValueError:
                                volumes.append(0)

                        energy_types = ['ice_petrol', 'ice_diesel', 'ice_lpg', 'ice_methane', 
                                       'hev', 'phev', 'bev', 'fcev']
                        
                        for energy_type, volume in zip(energy_types, volumes):
                            if volume > 0:
                                records.append({
                                    'energy_type': energy_type,
                                    'volume': volume,
                                })
        
        return records

    def save_records(self, records, source_month):
        """将数据入库"""
        if not records:
            return 0, 0
        
        conn, cur = self.get_connection()
        inserted = 0
        updated = 0

        for record_data in records:
            energy_type = record_data['energy_type']
            volume = record_data['volume']
            
            record = {
                'country_code': 'IT',
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
                'data_source': 'UNRAE',
                'notes': f'UNRAE history import {source_month.strftime("%Y-%m")} {energy_type}'
            }

            try:
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
        return inserted, updated

    def run(self):
        """运行历史回爬"""
        logger.info('=' * 60)
        logger.info('UNRAE 历史数据回爬启动')
        logger.info('=' * 60)
        
        # 1. 获取PDF链接
        self.fetch_pdf_urls_from_sitemap()
        
        if not self.pdf_urls:
            logger.error('未找到任何PDF链接')
            return
        
        # 2. 筛选2024年1月以后的数据
        filtered = [p for p in self.pdf_urls 
                   if (p['year'] > 2024) or (p['year'] == 2024 and p['month'] >= 1)]
        logger.info(f'2024年至今PDF: {len(filtered)} 个')
        
        # 3. 逐个下载和解析
        total_inserted = 0
        total_updated = 0
        total_months = 0
        
        for i, pdf_info in enumerate(filtered):
            year = pdf_info['year']
            month = pdf_info['month']
            source_month = date(year, month, 1)
            
            logger.info(f'\n--- [{i+1}/{len(filtered)}] 处理 {year}-{month:02d} ---')
            
            # 检查是否已存在（2026年7月已导入）
            conn, cur = self.get_connection()
            cur.execute("""
                SELECT COUNT(*) as cnt FROM market_sales_monthly
                WHERE country_code = 'IT' AND source_month = %s AND data_source = 'UNRAE'
            """, (source_month,))
            existing_count = cur.fetchone()['cnt']
            
            if existing_count > 0:
                logger.info(f'  已有 {existing_count} 条数据，跳过')
                continue
            
            # 下载PDF
            filepath = self.download_pdf(pdf_info['url'], year, month)
            if not filepath:
                continue
            
            # 解析PDF
            records = self.parse_pdf(filepath)
            if not records:
                logger.warning(f'  未解析到数据')
                continue
            
            # 入库
            inserted, updated = self.save_records(records, source_month)
            total_inserted += inserted
            total_updated += updated
            
            logger.info(f'  {year}-{month:02d}: 新增 {inserted}, 更新 {updated}, 总销量: {sum(r["volume"] for r in records):,}')
            total_months += 1
            
            # 休息一下，避免请求过快
            time.sleep(1)
        
        logger.info(f'\n=== 回爬完成 ===')
        logger.info(f'处理月份: {total_months}')
        logger.info(f'总新增: {total_inserted}')
        logger.info(f'总更新: {total_updated}')
        
        # 4. 验证数据
        self.verify()

    def verify(self):
        """验证入库数据"""
        conn, cur = self.get_connection()
        
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                MIN(source_month) as min_month,
                MAX(source_month) as max_month,
                SUM(sales_volume_normalized) as total_volume
            FROM market_sales_monthly
            WHERE country_code = 'IT' AND data_source = 'UNRAE'
              AND source_month >= '2024-01-01'
        """)
        row = cur.fetchone()
        logger.info(f'\n=== 2024年至今数据统计 ===')
        logger.info(f'  记录数: {row["total"]}')
        logger.info(f'  月份范围: {row["min_month"]} 至 {row["max_month"]}')
        logger.info(f'  总销量: {row["total_volume"]:,}')
        
        cur.execute("""
            SELECT energy_type, COUNT(*) as cnt, SUM(sales_volume_normalized) as total
            FROM market_sales_monthly
            WHERE country_code = 'IT' AND data_source = 'UNRAE'
              AND source_month >= '2024-01-01'
            GROUP BY energy_type
            ORDER BY total DESC
        """)
        logger.info(f'\n=== 按能源类型分布 ===')
        for r in cur.fetchall():
            logger.info(f'  {r["energy_type"]:25s}: {r["cnt"]:3d}条, {r["total"]:>12,}辆')
        
        cur.execute("""
            SELECT source_month, SUM(sales_volume_normalized) as total
            FROM market_sales_monthly
            WHERE country_code = 'IT' AND data_source = 'UNRAE'
              AND source_month >= '2024-01-01'
            GROUP BY source_month
            ORDER BY source_month DESC
        """)
        logger.info(f'\n=== 月度销量 ===')
        for r in cur.fetchall():
            logger.info(f'  {r["source_month"].strftime("%Y-%m")}: {r["total"]:>12,}辆')


if __name__ == '__main__':
    crawler = UNRAEHistoryCrawler()
    try:
        crawler.run()
    finally:
        crawler.close()
