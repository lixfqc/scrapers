# -*- coding: utf-8 -*-
"""
UNRAE 意大利汽车销量爬虫
整合三类PDF解析：能源类型(Comunicato)、品牌级(Marca)、车型级(Top 50)
支持历史数据批量回爬
"""
import os
import sys
import re
import time
import json
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
]

# 意大利月份名
MONTH_NAMES = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
               'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']

# UNRAE品牌名映射
BRAND_MAP = {
    'FIAT': 'FIAT', 'DACIA': 'Dacia', 'TOYOTA': 'Toyota',
    'VOLKSWAGEN': 'Volkswagen', 'PEUGEOT': 'Peugeot', 'AUDI': 'Audi',
    'BMW': 'BMW', 'RENAULT': 'Renault', 'JEEP': 'Jeep',
    'CITROEN': 'Citroen', 'FORD': 'Ford', 'MERCEDES': 'Mercedes-Benz',
    'MG': 'MG', 'KIA': 'Kia', 'HYUNDAI': 'Hyundai',
    'OPEL': 'Opel', 'NISSAN': 'Nissan', 'SKODA': 'Skoda',
    'SUZUKI': 'Suzuki', 'ALFA ROMEO': 'Alfa Romeo', 'DR MOTOR': 'DR',
    'CUPRA': 'Cupra', 'VOLVO': 'Volvo', 'MAZDA': 'Mazda',
    'MINI': 'Mini', 'LANCIA': 'Lancia', 'BYD': 'BYD',
    'SEAT': 'Seat', 'HONDA': 'Honda', 'EVO': 'Evo',
    'LAND ROVER': 'Land Rover', 'PORSCHE': 'Porsche',
    'OMODA&JAECOO': 'Omoda+Jaecoo', 'LEXUS': 'Lexus', 'TESLA': 'Tesla',
    'DS': 'DS', 'MITSUBISHI': 'Mitsubishi', 'EMC': 'EMC',
    'MASERATI': 'Maserati', 'SUBARU': 'Subaru', 'SPORTEQUIPE': 'Sportequipe',
    'SMART': 'Smart', 'FERRARI': 'Ferrari', 'LYNK & CO': 'Lynk & Co',
    'LAMBORGHINI': 'Lamborghini', 'JAGUAR': 'Jaguar',
    'SSANGYONG': 'SsangYong', 'LOTUS': 'Lotus', 'MAHINDRA': 'Mahindra',
    'POLESTAR': 'Polestar', 'ASTON MARTIN': 'Aston Martin', 'ALTRE': 'Others',
}

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'unrae_data')
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

    def _download_file(self, url, filepath):
        """下载文件"""
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code != 200:
                logger.error(f'  下载失败: HTTP {resp.status_code}')
                return False
            with open(filepath, 'wb') as f:
                f.write(resp.content)
            logger.info(f'  下载成功: {os.path.basename(filepath)} ({len(resp.content):,}字节)')
            return True
        except Exception as e:
            logger.error(f'  下载异常: {e}')
            return False

    def _fetch_page(self, url):
        """获取页面内容"""
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, 'html.parser')
        except Exception as e:
            logger.error(f'请求失败 {url}: {e}')
        return None

    def discover_pdfs_for_month(self, year, month):
        """
        从UNRAE统计数据页面发现指定月份的三类PDF链接
        
        返回: {'brand': url, 'model': url, 'energy': url}
        """
        month_name = MONTH_NAMES[month - 1]
        pdfs = {}

        # 方式1: 从统计数据tag页面获取品牌和车型PDF（遍历多页）
        max_pages = 10  # 最多遍历10页
        for page in range(1, max_pages + 1):
            if page == 1:
                tag_url = f"https://unrae.it/dati-statistici/immatricolazioni/tag/{month_name}"
            else:
                tag_url = f"https://unrae.it/dati-statistici/immatricolazioni/tag/{month_name}?page={page}"
            
            soup = self._fetch_page(tag_url)
            if not soup:
                break

            # 查找品牌PDF链接
            if 'brand' not in pdfs:
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    title = a.get_text(strip=True)
                    # 匹配: immatricolazioni-di-autovetture-per-marca-{month}-{year}
                    if ('per-marca' in href.lower() and str(year) in title and month_name.capitalize() in title):
                        detail_url = href if href.startswith('http') else f'https://unrae.it{href}'
                        pdf_url = self._extract_pdf_from_page(detail_url, ['marca'])
                        if pdf_url:
                            pdfs['brand'] = pdf_url
                            logger.info(f'  品牌PDF (page{page}): {pdf_url[:80]}...')
                            break

            # 查找车型PDF链接
            if 'model' not in pdfs:
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    title = a.get_text(strip=True)
                    # 匹配: top-50-modelli-{month}-{year}
                    if ('top-50-modelli' in href.lower() and str(year) in title and month_name.capitalize() in title):
                        detail_url = href if href.startswith('http') else f'https://unrae.it{href}'
                        pdf_url = self._extract_pdf_from_page(detail_url, ['top', 'modelli'])
                        if pdf_url:
                            pdfs['model'] = pdf_url
                            logger.info(f'  车型PDF (page{page}): {pdf_url[:80]}...')
                            break

            # 已找到所有类型，停止遍历
            if 'brand' in pdfs and 'model' in pdfs:
                break
            
            time.sleep(0.5)  # 礼貌延迟

        # 方式2: 从新闻页面获取能源类型PDF（遍历多页）
        if 'energy' not in pdfs:
            for page in range(1, 5):
                if page == 1:
                    news_tag_url = f"https://unrae.it/sala-stampa/autovetture/tag/{month_name}"
                else:
                    news_tag_url = f"https://unrae.it/sala-stampa/autovetture/tag/{month_name}?page={page}"
                
                soup2 = self._fetch_page(news_tag_url)
                if not soup2:
                    break

                for a in soup2.find_all('a', href=True):
                    href = a['href']
                    title = a.get_text(strip=True)
                    # 匹配: mercato-auto-italia-{month}-{year}
                    if ('mercato-auto-italia' in href.lower() and str(year) in title and month_name.capitalize() in title):
                        detail_url = href if href.startswith('http') else f'https://unrae.it{href}'
                        pdf_url = self._extract_pdf_from_page(detail_url, ['comunicato', 'stampa'])
                        if pdf_url:
                            pdfs['energy'] = pdf_url
                            logger.info(f'  能源PDF (page{page}): {pdf_url[:80]}...')
                            break

                if 'energy' in pdfs:
                    break
                time.sleep(0.5)

        return pdfs

    def _extract_pdf_from_page(self, page_url, keywords):
        """从详情页面提取PDF链接"""
        soup = self._fetch_page(page_url)
        if not soup:
            return None

        for a in soup.find_all('a', href=True):
            href = a['href']
            if '.pdf' in href.lower():
                href_lower = href.lower()
                if any(kw.lower() in href_lower for kw in keywords):
                    if not href.startswith('http'):
                        href = f'https://unrae.it{href}'
                    return href

        # 备选: 从页面文本中找PDF
        text = soup.get_text()
        pdfs = re.findall(r'https?://[^"<>\']+?\.pdf[^"<>\']*', text, re.IGNORECASE)
        for p in pdfs:
            if any(kw.lower() in p.lower() for kw in keywords):
                return p

        return None

    # ==================== 解析器 ====================

    def parse_energy_pdf(self, filepath):
        """
        解析能源类型PDF（Comunicato Stampa）
        
        格式:
        VOLUMI 23.781 8.038 13.301 0 59.420 13.103 7.368 0
        列: Benzina Diesel GPL Metano Ibride PHEV BEV Idrogeno
        """
        records = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ''
                if 'ALIMENTAZIONI' in page_text and 'VOLUMI' in page_text:
                    volumi_match = re.search(r'VOLUMI\s+([\d\.\s]+)', page_text)
                    if not volumi_match:
                        continue

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
                                'parse_type': 'energy',
                                'energy_type': energy_type,
                                'volume': volume,
                            })
        return records

    def parse_brand_pdf(self, filepath):
        """
        解析品牌级PDF（Marca）
        
        格式:
        FIAT 15.901 15.919 -0,11 11,89 11,21 ...
        DACIA 11.465 10.318 +11,12 8,58 7,27 ...
        """
        records = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ''
                lines = page_text.split('\n')

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # 跳过汇总行
                    if 'TOTALE' in line.upper():
                        continue

                    # 匹配品牌行: 品牌名 + 本月销量 + 上月销量 + 变化率%
                    match = re.match(
                        r'^([A-Z][A-Z\s&]+?)\s+([\d.]+)\s+([\d.]+)\s+([+-]?[\d,]+)',
                        line.upper()
                    )
                    if match:
                        brand_name_raw = match.group(1).strip()
                        volume_str = match.group(2).replace('.', '')

                        if len(brand_name_raw) < 2:
                            continue

                        try:
                            volume = int(volume_str)
                        except ValueError:
                            continue

                        if volume > 0:
                            mapped_brand = BRAND_MAP.get(brand_name_raw, brand_name_raw.title())
                            brand_id = self._get_brand_id(mapped_brand)

                            records.append({
                                'parse_type': 'brand',
                                'brand_name_raw': brand_name_raw,
                                'brand_name': mapped_brand,
                                'brand_id': brand_id,
                                'volume': volume,
                            })
        return records

    # 已知多词品牌（按长度降序排列，确保长品牌优先匹配）
    _MULTI_WORD_BRANDS = sorted(
        [b for b in BRAND_MAP.keys() if ' ' in b or '&' in b],
        key=len, reverse=True
    )
    # 已知单词品牌
    _SINGLE_WORD_BRANDS = sorted(
        [b for b in BRAND_MAP.keys() if ' ' not in b and '&' not in b],
        key=len, reverse=True
    )

    def _match_brand_from_line(self, line_upper):
        """
        从车型行文本中匹配品牌名（支持多词品牌）
        
        策略：已知品牌优先匹配 > 通用正则回退
        """
        # 先尝试匹配多词品牌（如 ALFA ROMEO, LAND ROVER 等）
        for brand in self._MULTI_WORD_BRANDS:
            brand_upper = brand.upper()
            # 品牌名必须在行首序号之后
            pattern = rf'^\d+\s+{re.escape(brand_upper)}\s+(.+?)\s+([\d.]+)$'
            match = re.match(pattern, line_upper)
            if match:
                return brand, match.group(1).strip(), match.group(2)

        # 再尝试匹配单词品牌（如 FIAT, BMW 等）
        for brand in self._SINGLE_WORD_BRANDS:
            brand_upper = brand.upper()
            pattern = rf'^\d+\s+{re.escape(brand_upper)}\s+(.+?)\s+([\d.]+)$'
            match = re.match(pattern, line_upper)
            if match:
                return brand, match.group(1).strip(), match.group(2)

        # 回退：通用正则匹配（处理未知品牌）
        match = re.match(
            r'^\d+\s+([A-Z][A-Z\s&]+?)\s+(.+?)\s+([\d.]+)$',
            line_upper
        )
        if match:
            return match.group(1).strip(), match.group(2).strip(), match.group(3)

        return None, None, None

    def parse_model_pdf(self, filepath):
        """
        解析车型级PDF（Top 50 modelli）
        
        格式:
        1 FIAT PANDA 13.333
        2 DACIA SANDERO 5.577
        23 ALFA ROMEO JUNIOR 1.234
        """
        records = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ''
                lines = page_text.split('\n')

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    brand_name_raw, model_name, volume_str = self._match_brand_from_line(line.upper())
                    
                    if brand_name_raw and model_name and volume_str:
                        try:
                            volume = int(volume_str.replace('.', ''))
                        except ValueError:
                            continue

                        if volume > 0 and len(model_name) > 2:
                            mapped_brand = BRAND_MAP.get(brand_name_raw, brand_name_raw.title())
                            brand_id = self._get_brand_id(mapped_brand)

                            records.append({
                                'parse_type': 'model',
                                'brand_name_raw': brand_name_raw,
                                'brand_name': mapped_brand,
                                'brand_id': brand_id,
                                'model_name': model_name,
                                'volume': volume,
                            })
        return records

    # ==================== 数据库操作 ====================

    def _get_brand_id(self, brand_name):
        """获取品牌ID（大小写不敏感，支持 variant 别名回退）"""
        if not hasattr(self, '_brand_id_cache'):
            self._brand_id_cache = {}
        if brand_name in self._brand_id_cache:
            return self._brand_id_cache[brand_name]

        conn, cur = self.get_connection()
        cur.execute(
            "SELECT id FROM brand_name_mapping WHERE canonical_name ILIKE %s LIMIT 1",
            (brand_name,)
        )
        row = cur.fetchone()
        brand_id = row['id'] if row else None
        if not brand_id:
            cur.execute(
                "SELECT brand_id FROM brand_name_variant WHERE variant_name ILIKE %s LIMIT 1",
                (brand_name,)
            )
            row = cur.fetchone()
            brand_id = row['brand_id'] if row else None
        self._brand_id_cache[brand_name] = brand_id
        return brand_id

    def save_records(self, records, source_month, parse_type='energy'):
        """将解析的数据入库"""
        if not records:
            return 0, 0

        conn, cur = self.get_connection()
        inserted = 0
        updated = 0

        for rec in records:
            try:
                if parse_type == 'energy':
                    record = {
                        'country_code': self.country_code,
                        'source_month': source_month,
                        'brand_name_raw': 'UNRAE_TOTAL',
                        'brand_id': None,
                        'model_name': None,
                        'vehicle_type': 'passenger',
                        'energy_type': rec['energy_type'],
                        'segment': None,
                        'raw_unit': 'unit',
                        'sales_volume_raw': rec['volume'],
                        'sales_volume_normalized': rec['volume'],
                        'revision_no': 1,
                        'is_latest': True,
                        'pub_date': source_month,
                        'crawl_time': datetime.now(),
                        'data_source': self.source_name,
                        'notes': f'UNRAE Energy PDF {source_month.strftime("%Y-%m")} {rec["energy_type"]}'
                    }
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

                elif parse_type == 'brand':
                    record = {
                        'country_code': self.country_code,
                        'source_month': source_month,
                        'brand_name_raw': rec['brand_name_raw'],
                        'brand_id': rec.get('brand_id'),
                        'model_name': None,
                        'vehicle_type': 'passenger',
                        'energy_type': 'unknown',
                        'segment': None,
                        'raw_unit': 'unit',
                        'sales_volume_raw': rec['volume'],
                        'sales_volume_normalized': rec['volume'],
                        'revision_no': 1,
                        'is_latest': True,
                        'pub_date': source_month,
                        'crawl_time': datetime.now(),
                        'data_source': self.source_name,
                        'notes': f'UNRAE Brand PDF {source_month.strftime("%Y-%m")} {rec["brand_name"]}'
                    }
                    cur.execute("""
                        SELECT id FROM market_sales_monthly
                        WHERE country_code = %(country_code)s
                          AND source_month = %(source_month)s
                          AND brand_name_raw = %(brand_name_raw)s
                          AND model_name IS NULL
                          AND energy_type = %(energy_type)s
                          AND revision_no = %(revision_no)s
                        LIMIT 1
                    """, record)

                elif parse_type == 'model':
                    record = {
                        'country_code': self.country_code,
                        'source_month': source_month,
                        'brand_name_raw': rec['brand_name_raw'],
                        'brand_id': rec.get('brand_id'),
                        'model_name': rec['model_name'],
                        'vehicle_type': 'passenger',
                        'energy_type': 'unknown',
                        'segment': None,
                        'raw_unit': 'unit',
                        'sales_volume_raw': rec['volume'],
                        'sales_volume_normalized': rec['volume'],
                        'revision_no': 1,
                        'is_latest': True,
                        'pub_date': source_month,
                        'crawl_time': datetime.now(),
                        'data_source': self.source_name,
                        'notes': f'UNRAE Model PDF {source_month.strftime("%Y-%m")} {rec["brand_name"]} {rec["model_name"]}'
                    }
                    cur.execute("""
                        SELECT id FROM market_sales_monthly
                        WHERE country_code = %(country_code)s
                          AND source_month = %(source_month)s
                          AND brand_name_raw = %(brand_name_raw)s
                          AND model_name = %(model_name)s
                          AND energy_type = %(energy_type)s
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
                logger.error(f'入库失败 {source_month} {parse_type}: {e}')
                conn.rollback()

        conn.commit()
        return inserted, updated

    # ==================== 主流程 ====================

    def crawl_range(self, start_year, start_month, end_year, end_month,
                    parse_types=None, force=False):
        """
        批量回爬指定时间范围的数据
        
        Args:
            start_year/start_month: 起始年月
            end_year/end_month: 结束年月
            parse_types: 要解析的类型列表 ['energy', 'brand', 'model']，默认全部
            force: 是否强制重新爬取
        """
        if parse_types is None:
            parse_types = ['energy', 'brand', 'model']

        logger.info('=' * 60)
        logger.info(f'UNRAE 历史数据回爬: {start_year}-{start_month:02d} 至 {end_year}-{end_month:02d}')
        logger.info(f'解析类型: {parse_types}')
        logger.info('=' * 60)

        # 生成月份列表
        months = []
        y, m = start_year, start_month
        while (y, m) <= (end_year, end_month):
            months.append((y, m))
            m += 1
            if m > 12:
                m = 1
                y += 1

        logger.info(f'共 {len(months)} 个月待处理\n')

        total_stats = {'energy': [0, 0], 'brand': [0, 0], 'model': [0, 0]}

        for idx, (year, month) in enumerate(months):
            source_month = date(year, month, 1)
            logger.info(f'--- [{idx+1}/{len(months)}] {year}-{month:02d} ---')

            pdfs = self.discover_pdfs_for_month(year, month)

            if not pdfs:
                logger.warning(f'  未发现任何PDF链接，跳过')
                time.sleep(1)
                continue

            for ptype in parse_types:
                if ptype not in pdfs:
                    continue

                url = pdfs[ptype]
                type_dir = os.path.join(OUTPUT_DIR, ptype)
                os.makedirs(type_dir, exist_ok=True)
                filepath = os.path.join(type_dir, f'unrae_{ptype}_{year}{month:02d}.pdf')

                # 检查是否已存在
                if not force and os.path.exists(filepath):
                    logger.info(f'  {ptype}: 文件已存在，跳过下载')
                else:
                    if not self._download_file(url, filepath):
                        continue

                # 检查数据库是否已有此类型数据
                conn, cur = self.get_connection()
                cur.execute("""
                    SELECT COUNT(*) as cnt FROM market_sales_monthly
                    WHERE country_code = 'IT' AND source_month = %s AND data_source = 'UNRAE'
                      AND notes LIKE %s
                """, (source_month, f'%UNRAE {ptype.capitalize()} PDF%'))
                existing = cur.fetchone()['cnt']
                # 使用独立游标检查，不关闭主连接

                if not force and existing > 0:
                    logger.info(f'  {ptype}: 已有 {existing} 条数据，跳过入库')
                    continue

                # 解析
                parser = {
                    'energy': self.parse_energy_pdf,
                    'brand': self.parse_brand_pdf,
                    'model': self.parse_model_pdf,
                }[ptype]

                records = parser(filepath)
                if not records:
                    logger.warning(f'  {ptype}: 未解析到数据')
                    continue

                # 入库
                inserted, updated = self.save_records(records, source_month, ptype)
                total_stats[ptype][0] += inserted
                total_stats[ptype][1] += updated

                logger.info(f'  {ptype}: {len(records)} 条, 新增 {inserted}, 更新 {updated}')

            time.sleep(random.uniform(1, 2))

        # 汇总
        logger.info(f'\n{"="*60}')
        logger.info(f'回爬完成汇总')
        logger.info(f'{"="*60}')
        for ptype, (ins, upd) in total_stats.items():
            if ins or upd:
                logger.info(f'  {ptype}: 新增 {ins}, 更新 {upd}')

        self._verify_range(start_year, start_month, end_year, end_month)

    def run(self):
        """运行模式：爬取最新一个月"""
        logger.info('=' * 60)
        logger.info('UNRAE 意大利汽车销量爬虫（最新月模式）')
        logger.info('=' * 60)

        now = datetime.now()
        # 默认爬取上个月
        if now.month == 1:
            year, month = now.year - 1, 12
        else:
            year, month = now.year, now.month - 1

        self.crawl_range(year, month, year, month)

    def _verify_range(self, start_year, start_month, end_year, end_month):
        """验证数据完整性"""
        conn, cur = self.get_connection()

        cur.execute("""
            SELECT 
                source_month,
                COUNT(*) as cnt,
                SUM(sales_volume_normalized) as total,
                COUNT(DISTINCT energy_type) as energy_types,
                COUNT(DISTINCT brand_name_raw) FILTER (WHERE model_name IS NULL AND energy_type = 'unknown') as brands,
                COUNT(DISTINCT model_name) FILTER (WHERE model_name IS NOT NULL) as models
            FROM market_sales_monthly
            WHERE country_code = 'IT' AND data_source = 'UNRAE'
              AND source_month >= %s AND source_month <= %s
            GROUP BY source_month
            ORDER BY source_month
        """, (date(start_year, start_month, 1), date(end_year, end_month, 1)))

        logger.info(f'\n=== 数据验证 ({start_year}-{start_month:02d} 至 {end_year}-{end_month:02d}) ===')
        logger.info(f'{"月份":<12} {"记录":<6} {"能源":<5} {"品牌":<5} {"车型":<5} {"总销量":>12}')
        logger.info('-' * 55)
        for r in cur.fetchall():
            logger.info(f"{r['source_month'].strftime('%Y-%m'):<12} {r['cnt']:<6} "
                       f"{r['energy_types'] or 0:<5} {r['brands'] or 0:<5} "
                       f"{r['models'] or 0:<5} {r['total']:>12,}")

        cur.close()


if __name__ == '__main__':
    crawler = UNRAECrawler()
    try:
        crawler.run()
    finally:
        crawler.close()
