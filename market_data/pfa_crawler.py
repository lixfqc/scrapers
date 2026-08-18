# -*- coding: utf-8 -*-
"""
PFA 法国汽车销量爬虫

数据源: CCFA/PFA 月度数据 PDF
URL格式（新版，稳定）:
  - 乘用车(VP): https://ccfa.fr/wp-content/uploads/{发布年}/{发布月}/Immatriculations-VPN_{法月份缩写}{年份}.pdf
  - 商用车(VUL): https://ccfa.fr/wp-content/uploads/{发布年}/{发布月}/Immatriculations-VULN_{法月份缩写}{年份}.pdf
数据类型: VP(乘用车)、VUL(轻型商用车)
特点: 品牌级数据 + 集团级汇总，AUTRES品牌无细分（约39%市场份额）
"""
import os
import sys
import re
import io
import time
import random
import requests
import pdfplumber
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kba_crawler import BaseCrawler

# 法语月份映射（全名 -> 数字）
FRENCH_MONTH_MAP = {
    'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4,
    'mai': 5, 'juin': 6, 'juillet': 7, 'août': 8,
    'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12
}

# 法语月份缩写映射（数字 -> URL缩写）
# 注意：二月使用Fev（不带'r'），这是CCFA网站的特殊格式
FRENCH_MONTH_ABBR = {
    1: 'Janv', 2: 'Fev', 3: 'Mars', 4: 'Avril',
    5: 'Mai', 6: 'Juin', 7: 'Juillet', 8: 'Aout',
    9: 'Sept', 10: 'Oct', 11: 'Nov', 12: 'Dec'
}

# 法语月份全名映射（数字 -> 全名）
FRENCH_MONTH_FULL = {
    1: 'Janvier', 2: 'Fevrier', 3: 'Mars', 4: 'Avril',
    5: 'Mai', 6: 'Juin', 7: 'Juillet', 8: 'Aout',
    9: 'Septembre', 10: 'Octobre', 11: 'Novembre', 12: 'Decembre'
}

# PFA品牌映射表（处理GROUPE等层级）
PFA_BRAND_MAP = {
    # 集团级映射（合并子品牌）
    'STELLANTIS': 'STELLANTIS',
    'GROUPE RENAULT': 'RENAULT_GROUP',
    'GROUPE TOYOTA': 'TOYOTA_GROUP',
    # 子品牌（归属于集团）
    'ABARTH': 'STELLANTIS',
    'ALFA ROMEO': 'STELLANTIS',
    'CITROEN': 'STELLANTIS',
    'DS': 'STELLANTIS',
    'FIAT': 'STELLANTIS',
    'JEEP': 'STELLANTIS',
    'MASERATI': 'STELLANTIS',
    'OPEL': 'STELLANTIS',
    'PEUGEOT': 'STELLANTIS',
    'VAUXHALL': 'STELLANTIS',
    # RENAULT集团子品牌
    'ALPINE': 'RENAULT_GROUP',
    'DACIA': 'RENAULT_GROUP',
    'RENAULT': 'RENAULT_GROUP',
    'MOBILIZE': 'RENAULT_GROUP',
    # TOYOTA集团子品牌
    'LEXUS': 'TOYOTA_GROUP',
    'TOYOTA': 'TOYOTA_GROUP',
    # 其他品牌（直接存储）
    'AUTRES': 'AUTRES',
    'TOTAL': 'TOTAL',
}

# 需要跳过的行
SKIP_ROWS = {'TOTAL', 'AUTRES', 'Source : PFA/AAA DATA', 'Pénétration'}


def _french_number_to_int(num_str):
    """法语数字格式转整数：'30 317' -> 30317"""
    if not num_str or num_str.strip() == '':
        return None
    cleaned = num_str.replace(' ', '').replace('\xa0', '')
    try:
        return int(cleaned)
    except ValueError:
        return None


def _french_pct_to_float(pct_str):
    """法语百分比转浮点：'+1,7' -> 1.7, '++' -> None"""
    if not pct_str or pct_str.strip() == '':
        return None
    cleaned = pct_str.strip()
    if cleaned == '++' or cleaned == '--':
        return None
    cleaned = cleaned.replace(',', '.').replace('+', '')
    try:
        return float(cleaned)
    except ValueError:
        return None


def _french_month_to_int(month_str):
    """法语月份转数字：'août' -> 8"""
    if not month_str:
        return None
    month_lower = month_str.lower().strip()
    return FRENCH_MONTH_MAP.get(month_lower)


def _normalize_pfa_brand(raw_brand):
    """PFA品牌名标准化"""
    brand_upper = raw_brand.strip().upper()
    # 先检查PFA特定映射
    if brand_upper in PFA_BRAND_MAP:
        return PFA_BRAND_MAP[brand_upper]
    # 检查是否包含"GROUPE"
    if 'GROUPE' in brand_upper:
        return brand_upper.replace('GROUPE ', '').replace('GROUPE', '').strip()
    return brand_upper


def _get_pdf_urls(data_year, data_month, vehicle_type='VP'):
    """生成CCFA月度数据PDF URL列表（支持多种格式）
    data_year: 数据年份
    data_month: 数据月份 (1-12)
    vehicle_type: 'VP' (乘用车) 或 'VUL' (商用车)
    
    返回: [(url, 发布年, 发布月), ...] 元组列表（按优先级排序）
    """
    # 发布年月 = 数据月+1，12月发布在次年1月
    pub_month = data_month + 1
    pub_year = data_year
    if pub_month > 12:
        pub_month = 1
        pub_year += 1
    
    # 法语月份缩写和全名
    month_abbr = FRENCH_MONTH_ABBR.get(data_month, '')
    month_full = FRENCH_MONTH_FULL.get(data_month, '')
    
    # 根据车辆类型选择URL前缀
    if vehicle_type == 'VP':
        prefix = 'Immatriculations-VPN'
    else:  # VUL
        prefix = 'Immatriculations-VULN'
    
    # 生成多种可能的URL格式（按优先级排序）
    urls = [
        # 格式1: 旧格式（2024-2025年）- 缩写
        f'https://ccfa.fr/wp-content/uploads/{pub_year}/{pub_month:02d}/{prefix}_{month_abbr}{data_year}.pdf',
        # 格式2: 新格式（2026年）- 全名连字符
        f'https://ccfa.fr/wp-content/uploads/{pub_year}/{pub_month:02d}/{prefix}-{month_full}-{data_year}.pdf',
        # 格式3: 全名下划线
        f'https://ccfa.fr/wp-content/uploads/{pub_year}/{pub_month:02d}/{prefix}_{month_full}{data_year}.pdf',
    ]
    
    return [(url, pub_year, pub_month) for url in urls]


def _get_pdf_url(data_year, data_month, vehicle_type='VP'):
    """生成CCFA月度数据PDF URL（兼容旧接口，返回第一个URL）"""
    urls = _get_pdf_urls(data_year, data_month, vehicle_type)
    return urls[0]


class PfaCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(source_name='pfa', country_code='FR')
        self.vehicle_types = ['VL', 'VP', 'VUL']
        self._brand_id_cache = {}  # 品牌ID缓存

    def save_sales(self, record):
        """重写保存方法，在去重条件中包含vehicle_type"""
        # 自动匹配品牌ID（如果未设置）
        if record['brand_id'] is None and record['brand_name_raw'] is not None:
            brand_id, should_skip = self._match_brand(record['brand_name_raw'])
            record['brand_id'] = brand_id
            if brand_id:
                self.logger.debug(f'品牌匹配成功: {record["brand_name_raw"]} -> {brand_id}')
        
        conn, cur = self.get_connection()
        try:
            cur.execute("""
                SELECT id FROM market_sales_monthly
                WHERE country_code = %(country_code)s
                  AND source_month = %(source_month)s
                  AND brand_name_raw = %(brand_name_raw)s
                  AND vehicle_type = %(vehicle_type)s
                  AND revision_no = %(revision_no)s
                  AND model_name IS NOT DISTINCT FROM %(model_name)s
                  AND energy_type IS NOT DISTINCT FROM %(energy_type)s
                LIMIT 1
            """, record)
            row = cur.fetchone()
            if row:
                cur.execute("""
                    UPDATE market_sales_monthly SET
                        brand_id = %(brand_id)s,
                        sales_volume_raw = %(sales_volume_raw)s,
                        sales_volume_normalized = %(sales_volume_normalized)s,
                        is_latest = %(is_latest)s,
                        crawl_time = %(crawl_time)s,
                        pub_date = %(pub_date)s,
                        notes = %(notes)s
                    WHERE id = %(id)s
                """, {**record, 'id': row['id']})
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
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            self.logger.error(f'保存失败: {e}')
            return False

    def _match_brand(self, brand_raw):
        """品牌匹配：查brand_name_mapping表获取brand_id
        返回 (brand_id, should_skip) 元组
        should_skip=True 表示该品牌是集团汇总或AUTRES，应跳过
        
        匹配优先级:
        1. 精确匹配 canonical_name (不区分大小写)
        2. 精确匹配 brand_name_cn
        3. 去标点后精确匹配（处理 M.G. -> MG，Lynk & Co -> Lynk Co）
        4. 全面标准化匹配（去掉所有特殊字符）
        5. 标准化后模糊匹配（处理 Lynk Co -> Lynk & Co）
        """
        # 集团级汇总品牌（跳过，因为子品牌已单独存储）
        GROUP_BRANDS = {'STELLANTIS', 'GROUPE RENAULT', 'GROUPE TOYOTA'}
        if brand_raw.upper() in GROUP_BRANDS:
            return None, True

        # AUTRES（其他品牌，无具体品牌名）
        if brand_raw.upper() == 'AUTRES':
            return None, True

        # 先查缓存
        if brand_raw in self._brand_id_cache:
            return self._brand_id_cache[brand_raw], False

        conn, cur = self.get_connection()
        brand_upper = brand_raw.upper().strip()
        
        # 多层级规范化
        brand_clean = brand_upper.replace('.', '').replace(' ', '')
        brand_normalized = brand_upper.replace('.', '').replace(' ', '').replace('&', '').replace('-', '').replace(',', '')

        # 1. 精确匹配 canonical_name (不区分大小写)
        cur.execute("""
            SELECT id FROM brand_name_mapping
            WHERE LOWER(canonical_name) = LOWER(%s)
            LIMIT 1
        """, (brand_raw.strip(),))
        row = cur.fetchone()
        if row:
            brand_id = row['id']
            self._brand_id_cache[brand_raw] = brand_id
            return brand_id, False

        # 2. 精确匹配 brand_name_cn
        cur.execute("""
            SELECT id FROM brand_name_mapping
            WHERE LOWER(brand_name_cn) = LOWER(%s)
            LIMIT 1
        """, (brand_raw.strip(),))
        row = cur.fetchone()
        if row:
            brand_id = row['id']
            self._brand_id_cache[brand_raw] = brand_id
            return brand_id, False

        # 3. 去标点后精确匹配（处理 M.G. -> MG）
        if brand_clean != brand_upper.replace(' ', ''):
            cur.execute("""
                SELECT id FROM brand_name_mapping
                WHERE REPLACE(REPLACE(LOWER(canonical_name), '.', ''), ' ', '') = %s
                LIMIT 1
            """, (brand_clean.lower(),))
            row = cur.fetchone()
            if row:
                brand_id = row['id']
                self._brand_id_cache[brand_raw] = brand_id
                return brand_id, False

        # 4. 全面标准化匹配（去掉所有特殊字符，处理 Lynk Co -> Lynk & Co）
        if brand_normalized != brand_clean:
            cur.execute("""
                SELECT id FROM brand_name_mapping
                WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER(canonical_name), '.', ''), ' ', ''), '&', ''), '-', ''), ',', '') = %s
                LIMIT 1
            """, (brand_normalized.lower(),))
            row = cur.fetchone()
            if row:
                brand_id = row['id']
                self._brand_id_cache[brand_raw] = brand_id
                return brand_id, False

        # 5. 按标准化品牌名匹配
        normalized = _normalize_pfa_brand(brand_raw)
        if normalized != brand_raw:
            cur.execute("""
                SELECT id FROM brand_name_mapping
                WHERE LOWER(canonical_name) = LOWER(%s)
                LIMIT 1
            """, (normalized,))
            row = cur.fetchone()
            if row:
                brand_id = row['id']
                self._brand_id_cache[brand_raw] = brand_id
                return brand_id, False

        # 6. 模糊匹配（兜底）
        cur.execute("""
            SELECT id FROM brand_name_mapping
            WHERE canonical_name ILIKE %s OR brand_name_cn ILIKE %s
            LIMIT 1
        """, (f'%{brand_raw}%', f'%{brand_raw}%'))
        row = cur.fetchone()
        if row:
            brand_id = row['id']
            self._brand_id_cache[brand_raw] = brand_id
            return brand_id, False

        # 7. 去标点后模糊匹配
        cur.execute("""
            SELECT id FROM brand_name_mapping
            WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER(canonical_name), '.', ''), ' ', ''), '&', ''), '-', ''), ',', '') LIKE %s
            LIMIT 1
        """, (f'%{brand_normalized.lower()}%',))
        row = cur.fetchone()
        if row:
            brand_id = row['id']
            self._brand_id_cache[brand_raw] = brand_id
            return brand_id, False

        # 未找到
        self.logger.warning(f'品牌未匹配: {brand_raw}')
        self._brand_id_cache[brand_raw] = None
        return None, False

    def download_pdf(self, data_year, data_month, vehicle_type='VP'):
        """下载CCFA月度数据PDF文件（支持多URL格式尝试）
        vehicle_type: 'VP' (乘用车) 或 'VUL' (商用车)
        """
        urls = _get_pdf_urls(data_year, data_month, vehicle_type)
        self.logger.info(f'尝试下载{vehicle_type} PDF，共 {len(urls)} 种URL格式')

        headers = self.get_headers()
        for url, pub_year, pub_month in urls:
            self.logger.debug(f'尝试URL: {url}')
            try:
                response = self.retry_request(requests.get, url, headers=headers, timeout=30)
                if response and response.status_code == 200 and len(response.content) > 1000:
                    self.logger.info(f'下载成功: {url} ({len(response.content)} bytes)')
                    return response.content
                else:
                    status = response.status_code if response else "None"
                    content_len = len(response.content) if response else 0
                    self.logger.debug(f'URL失败: status={status}, size={content_len}')
            except Exception as e:
                self.logger.debug(f'URL异常: {url}, {e}')
                continue
        
        self.logger.error(f'所有URL格式均尝试失败: {data_year}-{data_month:02d} {vehicle_type}')
        return None

    def parse_pdf_tables(self, pdf_content):
        """解析PDF中的所有表格"""
        tables = []
        try:
            with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    page_tables = page.extract_tables()
                    for table in page_tables:
                        if table and len(table) > 2:
                            tables.append({
                                'page': page_num + 1,
                                'rows': table
                            })
            self.logger.info(f'解析到 {len(tables)} 个表格')
        except Exception as e:
            self.logger.error(f'PDF解析失败: {e}')
        return tables

    def _identify_table_type(self, table_rows):
        """识别表格类型：VL/VP/VUL/MODEL
        只识别品牌级数据表格，跳过图表、汇总表等
        
        支持两种格式：
        1. 旧格式（2024-2025）：表头在第一行
        2. 新格式（2026）：表头在第四行（Marques, Juin 2026, ...）
        """
        if not table_rows or len(table_rows) < 5:
            return None

        # 检查所有行来构建表头文本
        all_header_text = ''
        for row in table_rows[:6]:  # 检查前6行
            row_text = ' '.join([str(cell).upper().replace('\n', ' ') if cell else '' for cell in row])
            all_header_text += ' ' + row_text

        all_header_text = all_header_text.strip()

        # 跳过空表头或图表表
        if not all_header_text:
            return None
        if 'RUNNING COUNT' in all_header_text:
            return None
        if '1 /' in all_header_text or '2 /' in all_header_text:  # 页码行
            return None

        # 识别品牌级表格
        # 检查是否包含"Marques"或"Marque"关键字（所有格式都有）
        if 'MARQUES' not in all_header_text and 'MARQUE' not in all_header_text:
            return None

        # 根据表头内容识别类型
        # VL: Véhicules Légers (VP + VUL)
        if 'VÉHICULES LÉGERS' in all_header_text and 'UTILITAIRES' not in all_header_text:
            return 'VL'
        # VP: Voitures Particulières / Immatriculations VP
        if 'VOITURES PARTICULIÈRES' in all_header_text or 'IMMATRICULATIONS VP' in all_header_text:
            return 'VP'
        # VUL: Véhicules Utilitaires Légers / Immatriculations VUL / VU -5t1
        if 'UTILITAIRES LÉGERS' in all_header_text or 'IMMATRICULATIONS VUL' in all_header_text:
            return 'VUL'
        # VUL新格式: "Immatriculations VU -5t1 en France"
        if 'IMMATRICULATIONS VU' in all_header_text and '5T1' in all_header_text:
            return 'VUL'

        return None

    def _parse_brand_row_v2(self, row, vehicle_type, data_year, data_month):
        """解析新格式PDF的品牌行数据（CCFA Immatriculations格式）
        列结构: ['', 'Marques', 'Août 2024', 'Var. 24/23 en %', '8 mois 2024']
        """
        cells = [str(c).strip() if c else '' for c in row]
        if len(cells) < 3:
            return None

        # 品牌在第2列（index 1）
        brand_raw = cells[1].strip()
        
        # 跳过非数据行
        if not brand_raw or brand_raw in SKIP_ROWS:
            return None
        if brand_raw.startswith('Source') or brand_raw.startswith('%'):
            return None
        # 跳过表头
        if brand_raw.upper() in ('MARQUES', 'MARQUE'):
            return None

        # 当月销量在第3列（index 2）
        sales = _french_number_to_int(cells[2])
        if sales is None or sales <= 0:
            return None

        # 同比变化在第4列（index 3）
        variation = _french_pct_to_float(cells[3]) if len(cells) > 3 else None

        brand_id, should_skip = self._match_brand(brand_raw)
        if should_skip:
            return None
        if brand_id is None:
            self.logger.debug(f'跳过未匹配品牌: {brand_raw}')
            return None

        record = {
            'country_code': 'FR',
            'source_month': f'{data_year}-{data_month:02d}-01',
            'brand_name_raw': brand_raw,
            'brand_id': brand_id,
            'model_name': None,
            'vehicle_type': vehicle_type,
            'energy_type': None,
            'segment': None,
            'raw_unit': 'unit',
            'sales_volume_raw': sales,
            'sales_volume_normalized': sales,
            'revision_no': 1,
            'is_latest': True,
            'pub_date': f'{data_year}-{data_month:02d}-01',
            'crawl_time': datetime.now(),
            'data_source': f'CCFA_{vehicle_type}_Immatriculations',
            'notes': f'CCFA_{vehicle_type}_{data_year}-{data_month:02d} | variation={variation}% | new_format',
        }
        return record

    def _is_cumulative_table(self, table_rows):
        """判断是否为累计数据表格（8 mois 2025 格式）"""
        if not table_rows:
            return False
        first_row = [str(cell).lower().replace('\n', ' ') if cell else '' for cell in table_rows[0]]
        header_text = ' '.join(first_row)
        return 'mois' in header_text

    def extract_records_from_tables(self, tables, data_year, data_month):
        """从所有表格提取销售记录（仅提取月度数据，累计数据通过其他方式处理）
        存储策略：存储VP（乘用车）和VUL（商用车），跳过VL（VL=VP+VUL，可计算得出）
        
        支持两种格式：
        1. 旧格式：表头在第一行，数据从第二行开始
        2. 新格式（2026）：表头在"Marques"行，数据从下一行开始
        """
        records = []

        for table_info in tables:
            table_type = self._identify_table_type(table_info['rows'])
            if not table_type:
                continue

            # 跳过累计表（只取月度数据）
            if self._is_cumulative_table(table_info['rows']):
                self.logger.info(f'跳过累计表: {table_type} (page {table_info["page"]})')
                continue

            # 跳过VL表（VL = VP + VUL，存储VP和VUL即可）
            if table_type == 'VL':
                self.logger.info(f'跳过VL表（VL=VP+VUL）: page {table_info["page"]}')
                continue

            self.logger.info(f'识别表格类型: {table_type} (page {table_info["page"]})')

            # 找到表头行（包含"Marques"或"Marque"的行）
            header_row_idx = 0
            for idx, row in enumerate(table_info['rows']):
                row_text = ' '.join([str(c).upper() for c in row if c])
                if 'MARQUES' in row_text or 'MARQUE' in row_text:
                    header_row_idx = idx
                    break

            # 从表头下一行开始解析数据
            for row in table_info['rows'][header_row_idx + 1:]:
                record = self._parse_brand_row_v2(row, table_type, data_year, data_month)
                if record:
                    records.append(record)

        return records

    def crawl_month(self, data_year, data_month):
        """爬取指定月份数据（新格式：分别下载VP和VUL PDF）"""
        self.logger.info(f'=== 开始爬取 {data_year}-{data_month:02d} ===')
        total_saved = 0
        
        # 分别下载VP和VUL
        for vtype in ['VP', 'VUL']:
            pdf_content = self.download_pdf(data_year, data_month, vtype)
            if not pdf_content:
                self.logger.warning(f'{data_year}-{data_month:02d} {vtype} 下载失败，跳过')
                continue

            tables = self.parse_pdf_tables(pdf_content)
            if not tables:
                self.logger.warning(f'{data_year}-{data_month:02d} {vtype} 无表格数据')
                continue

            # 使用新解析器提取记录
            records = []
            for table_info in tables:
                for row in table_info['rows']:
                    record = self._parse_brand_row_v2(row, vtype, data_year, data_month)
                    if record:
                        records.append(record)
            
            self.logger.info(f'{vtype}: 解析出 {len(records)} 条记录')

            saved_count = 0
            for record in records:
                if self.save_sales(record):
                    saved_count += 1
            
            self.logger.info(f'{vtype}: 保存 {saved_count} 条记录')
            total_saved += saved_count
        
        self.logger.info(f'{data_year}-{data_month:02d} 总共保存 {total_saved} 条记录')
        return total_saved

    def crawl_range(self, start_year, start_month, end_year, end_month):
        """爬取时间范围"""
        self.logger.info(f'=== PFA法国销量爬虫启动 ===')
        self.logger.info(f'时间范围: {start_year}-{start_month:02d} ~ {end_year}-{end_month:02d}')

        total_saved = 0
        current_year, current_month = start_year, start_month

        while (current_year, current_month) <= (end_year, end_month):
            saved = self.crawl_month(current_year, current_month)
            total_saved += saved

            self.page_count += 1
            self.random_delay()
            self.batch_restart()

            # 下一个月
            current_month += 1
            if current_month > 12:
                current_month = 1
                current_year += 1

        self.log_crawl_run('completed', total_saved)
        self.logger.info(f'=== 爬取完成，共保存 {total_saved} 条 ===')
        return total_saved

    def run(self):
        """主入口：爬取最近24个月数据"""
        today = date.today()
        end_year = today.year
        end_month = today.month - 1  # 上一月

        if end_month == 0:
            end_month = 12
            end_year -= 1

        start_year = end_year - 2
        start_month = end_month + 1

        if start_month > 12:
            start_month -= 12
            start_year += 1

        self.logger.info(f'默认范围: {start_year}-{start_month:02d} ~ {end_year}-{end_month:02d}')
        self.logger.info('如需自定义范围，请修改 run() 方法')

        return self.crawl_range(start_year, start_month, end_year, end_month)


# 支持直接运行
if __name__ == '__main__':
    import io
    crawler = PfaCrawler()

    # 快速测试：爬取最近3个月
    today = date.today()
    test_year = today.year
    test_month = today.month - 2
    if test_month <= 0:
        test_month += 12
        test_year -= 1

    print(f'测试爬取: {test_year}-{test_month:02d}')
    count = crawler.crawl_month(test_year, test_month)
    print(f'完成，保存 {count} 条')

    crawler.close()


# ========== 能源类型数据解析 ==========

# 能源类型映射（法语 -> 英文代码）
ENERGY_TYPE_MAP = {
    'ELECTRIQUE': 'BEV',           # 纯电动
    'HYDROGÈNE': 'FCEV',           # 氢燃料电池
    'HYDROGENE': 'FCEV',
    'HYBRIDE RECHARGEABLE': 'PHEV',  # 插电混动
    'HYBRIDE NON RECHARGEABLE': 'HEV',  # 非插电混动
    'HYBRIDE': 'HEV',             # 混动（通用）
    'ESSENCE': 'GASOLINE',        # 汽油
    'DIESEL': 'DIESEL',          # 柴油
    'GPL': 'LPG',                 # 液化石油气
    'GNV': 'CNG',                 # 压缩天然气
    'B100': 'BIODIESEL',          # 生物柴油
    'E85': 'ETHANOL',             # 乙醇
    'BIO-ETHANOL': 'ETHANOL',
    'BIOETHANOL': 'ETHANOL',
}


def _get_energy_pdf_urls(data_year, data_month):
    """生成能源类型PDF的URL列表
    
    URL格式（按优先级）:
    格式1: Immatriculations-mensuelles-par-energie_{法月份缩写}{年份}.pdf
    格式2: Immatriculations-mensuelles-par-energie_{法月份缩写}{年份}-1.pdf
    格式3: Immatriculations-mensuelles-par-energie-{法月份全名}-{年份}.pdf
    """
    pub_month = data_month + 1
    pub_year = data_year
    if pub_month > 12:
        pub_month = 1
        pub_year += 1
    
    month_abbr = FRENCH_MONTH_ABBR.get(data_month, '')
    month_full = FRENCH_MONTH_FULL.get(data_month, '')
    
    prefix = 'Immatriculations-mensuelles-par-energie'
    
    urls = [
        f'https://ccfa.fr/wp-content/uploads/{pub_year}/{pub_month:02d}/{prefix}_{month_abbr}{data_year}.pdf',
        f'https://ccfa.fr/wp-content/uploads/{pub_year}/{pub_month:02d}/{prefix}_{month_abbr}{data_year}-1.pdf',
        f'https://ccfa.fr/wp-content/uploads/{pub_year}/{pub_month:02d}/{prefix}-{month_full}-{data_year}.pdf',
    ]
    
    return [(url, pub_year, pub_month) for url in urls]


def _map_energy_type(energy_raw):
    """映射能源类型名称"""
    energy_upper = energy_raw.upper().strip()
    return ENERGY_TYPE_MAP.get(energy_upper, None)


class PfaEnergyCrawler(PfaCrawler):
    """PFA能源类型数据爬虫"""
    
    def download_energy_pdf(self, data_year, data_month):
        """下载能源类型PDF"""
        urls = _get_energy_pdf_urls(data_year, data_month)
        self.logger.info(f'尝试下载能源类型PDF，共 {len(urls)} 种URL格式')

        headers = self.get_headers()
        for url, pub_year, pub_month in urls:
            self.logger.debug(f'尝试URL: {url}')
            try:
                response = self.retry_request(requests.get, url, headers=headers, timeout=30)
                if response and response.status_code == 200 and len(response.content) > 1000:
                    self.logger.info(f'下载成功: {url} ({len(response.content)} bytes)')
                    return response.content
            except Exception as e:
                self.logger.debug(f'URL异常: {url}, {e}')
                continue
        
        self.logger.error(f'所有能源类型URL均尝试失败: {data_year}-{data_month:02d}')
        return None

    def _parse_energy_table(self, table_rows, data_year, data_month, vehicle_type):
        """解析能源类型表格
        
        注意：PDF解析可能会产生重复字符（如"GGeennrree"），
        需要先进行去重处理
        """
        records = []
        
        def _dedup_text(text):
            """去除重复字符（PDF解析常见问题）"""
            if not text:
                return text
            # 只保留每个字符一次（连续重复）
            result = []
            for char in text:
                if not result or char != result[-1]:
                    result.append(char)
            return ''.join(result)
        
        # 查找表头行（使用去重和宽松匹配）
        header_idx = -1
        for idx, row in enumerate(table_rows):
            row_text = ' '.join([_dedup_text(str(c)).upper() for c in row if c])
            # 宽松匹配：检查是否包含"NERGIE"或"ype d"等特征
            if 'NERGIE' in row_text or ('YPE' in row_text and 'Mois' in row_text):
                header_idx = idx
                break
        
        if header_idx < 0:
            return records
        
        # 解析数据行
        for row in table_rows[header_idx + 1:]:
            cells = [str(c).strip() if c else '' for c in row]
            
            if len(cells) < 4:
                continue
            
            # 能源类型在第3列（index 2），需要去重
            energy_raw = _dedup_text(cells[2].strip())
            
            if not energy_raw or energy_raw in ('TOTAL', 'Total', 'Source'):
                continue
            
            energy_type = _map_energy_type(energy_raw)
            if not energy_type:
                self.logger.debug(f'未识别的能源类型: {energy_raw}')
                continue
            
            # 当月销量在第4列（index 3），需要去重
            sales_text = _dedup_text(cells[3].strip())
            sales = _french_number_to_int(sales_text)
            if sales is None:
                continue
            
            # 同比变化在第5列（index 4）
            variation = _french_pct_to_float(_dedup_text(cells[4])) if len(cells) > 4 else None
            
            record = {
                'country_code': 'FR',
                'source_month': f'{data_year}-{data_month:02d}-01',
                'brand_name_raw': None,
                'brand_id': None,
                'model_name': None,
                'vehicle_type': vehicle_type,
                'energy_type': energy_type,
                'segment': None,
                'raw_unit': 'unit',
                'sales_volume_raw': sales,
                'sales_volume_normalized': sales,
                'revision_no': 1,
                'is_latest': True,
                'pub_date': f'{data_year}-{data_month:02d}-01',
                'crawl_time': datetime.now(),
                'data_source': f'CCFA_ENERGY_{vehicle_type}_Immatriculations',
                'notes': f'CCFA_Energy_{data_year}-{data_month:02d}_{energy_type} | variation={variation}%',
            }
            records.append(record)
        
        return records

    def extract_energy_records(self, tables, data_year, data_month):
        """从所有表格提取能源类型记录"""
        records = []
        
        for table_info in tables:
            rows = table_info['rows']
            if len(rows) < 5:
                continue
            
            # 识别车辆类型
            vehicle_type = None
            for row in rows[:6]:
                row_text = ' '.join([str(c).upper().replace('\n', ' ') if c else '' for c in row])
                
                if 'VOITURES PARTICULIÈRES' in row_text or 'VOITURES PARTICULIERES' in row_text:
                    vehicle_type = 'VP'
                    break
                elif 'VÉHICULES UTILITAIRES LÉGERS' in row_text or 'VEHICULES UTILITAIRES LEGERS' in row_text:
                    vehicle_type = 'VUL'
                    break
                elif 'VÉHICULES INDUSTRIELS' in row_text or 'VEHICULES INDUSTRIELS' in row_text:
                    vehicle_type = 'VI'
                    break
                elif 'CARS ET BUS' in row_text:
                    vehicle_type = 'BUS'
                    break
            
            if not vehicle_type:
                continue
            
            self.logger.info(f'识别能源表格: {vehicle_type} (page {table_info["page"]})')
            
            table_records = self._parse_energy_table(rows, data_year, data_month, vehicle_type)
            records.extend(table_records)
        
        return records

    def crawl_energy_month(self, data_year, data_month):
        """爬取指定月份的能源类型数据"""
        self.logger.info(f'=== 开始爬取能源类型数据 {data_year}-{data_month:02d} ===')
        
        pdf_content = self.download_energy_pdf(data_year, data_month)
        if not pdf_content:
            self.logger.warning(f'{data_year}-{data_month:02d} 能源类型PDF下载失败')
            return 0
        
        tables = self.parse_pdf_tables(pdf_content)
        if not tables:
            self.logger.warning(f'{data_year}-{data_month:02d} 能源类型无表格数据')
            return 0
        
        records = self.extract_energy_records(tables, data_year, data_month)
        self.logger.info(f'提取到 {len(records)} 条能源类型记录')
        
        saved_count = 0
        for record in records:
            if self.save_sales(record):
                saved_count += 1
        
        self.logger.info(f'能源类型: 保存 {saved_count} 条记录')
        return saved_count
