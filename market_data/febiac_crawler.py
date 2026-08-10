# -*- coding: utf-8 -*-
"""
Febiac 比利时汽车销量爬虫

数据源: Febiac 月度数据 PDF
URL格式（多种格式fallback）:
  - 2026年: https://febiac.be/sites/default/files/media/file/{上传年-上传月}/{MMYY}%20-%20Cars%20by%20make.pdf
  - 2025年: https://febiac.be/sites/default/files/media/file/{上传年-上传月}/{MMYY}_Cars_by_make.pdf
  - 2024年: 混合格式，需要多种尝试
数据类型: Cars by make (乘用车品牌级)
特点: PDF含双表（当月+累计），存在合并行（如 DACIA/RENAULT 合并）
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


# 比利时品牌名标准化映射
FEBIAC_BRAND_MAP = {
    'KSIA': 'KIA',
    'MERCEDES': 'MERCEDES-BENZ',
    'MERCEDES BENZ': 'MERCEDES-BENZ',
    'LAND ROVER': 'LAND ROVER',
    'ROVER': 'LAND ROVER',
    'LYNK & CO': 'LYNK&CO',
    'LYNKCO': 'LYNK&CO',
    'B-STYLE&FLEX-I-TRANS': 'B-STYLE',
    'KG MOBILITY': 'KG_MOBILITY',
    'NIO': 'NIO',
    'XPENG': 'XPENG',
    'LEAPMOTOR': 'LEAPMOTOR',
    'MAXUS': 'MAXUS',
    'SSANGYONG': 'SSANGYONG',
    'BAIC': 'BAIC',
    'FISKER': 'FISKER',
    'AIWAYS': 'AIWAYS',
    'SWM': 'SWM',
    'OMODA': 'OMODA',
    'DFSK': 'DFSK',
    'FAW': 'FAW',
    'AMF': 'AMF',
    'TRIPOD': 'TRIPOD',
    'FORTHING': 'FORTHING',
    'ALLIED VEHICLES LTD': 'ALLIED_VEHICLES',
    'CATERHAM': 'CATERHAM',
}

# 需要跳过的汇总行/特殊行
SKIP_BRANDS = {'TOTAL', 'TOTAAL', 'AUTRES', 'ANDERE', '-'}

# 月份关键词（用于过滤PDF标题行）
MONTH_KEYWORDS = {
    'JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE',
    'JULY', 'AUGUST', 'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER',
    'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
    'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC',
    'JANUARI', 'FEBRUARI', 'MAART', 'APRIL', 'MEI', 'JUNI',
    'JULI', 'AUGUSTUS', 'SEPTEMBER', 'OKTOBER', 'NOVEMBER', 'DECEMBER',
}


def _belgian_number_to_int(num_str):
    """比利时数字格式转整数：'29 274' -> 29274, '1.003' -> 1003"""
    if not num_str or num_str.strip() == '':
        return None
    # 先尝试空格分隔
    cleaned = num_str.strip()
    if ' ' in cleaned:
        cleaned = cleaned.replace(' ', '')
    # 再尝试点号分隔（千分位）
    if '.' in cleaned and ',' not in cleaned:
        # 可能是 "1.003" -> 1003
        cleaned = cleaned.replace('.', '')
    # 逗号分隔（小数点）
    if ',' in cleaned and '.' not in cleaned:
        # 可能是 "1.003" -> 1003 (比利时用逗号做千分位)
        cleaned = cleaned.replace(',', '')
    try:
        return int(cleaned)
    except ValueError:
        # 最后尝试直接转换
        try:
            return int(float(num_str.strip().replace(' ', '').replace('.', '').replace(',', '')))
        except ValueError:
            return None


def _clean_brand_name(brand_raw):
    """清理品牌名"""
    if not brand_raw:
        return None
    cleaned = brand_raw.strip().upper()
    # 移除排名前缀（如 "1 BMW" -> "BMW"）
    # 模式：数字开头 + 空格 + 品牌名
    match = re.match(r'^\d+\s+(.+)', cleaned)
    if match:
        cleaned = match.group(1).strip()
    # 特殊映射
    if cleaned in FEBIAC_BRAND_MAP:
        return FEBIAC_BRAND_MAP[cleaned]
    # 清理多余空格
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned


def _get_febiac_pdf_urls(data_year, data_month):
    """生成Febiac月度PDF URL列表（多种格式fallback）
    
    URL格式规律（经实测验证）：
    - 2026年: {YYMM} - Cars by make.pdf （空格+连字符+空格，YYMM=年份后两位+月份）
    - 2025年: {YYMM}_Cars by make.pdf （下划线分隔，YYMM格式）
    - 2024年: {MMYY} - Cars by make_0.pdf 或 {MMYY}_Cars by make.pdf （MMYY格式，可能带_0后缀）
    
    关键规则：上传目录 = 数据月+1（如7月数据在8月目录）
    """
    # 上传年月 = 数据月+1
    upload_month = data_month + 1
    upload_year = data_year
    if upload_month > 12:
        upload_month = 1
        upload_year += 1
    
    # 两种日期格式
    yymm = f'{str(data_year)[2:]}{data_month:02d}'  # YYMM: 2026年7月 -> 2607
    mmyy = f'{data_month:02d}{str(data_year)[2:]}'  # MMYY: 2026年7月 -> 0726
    
    # 上传目录
    upload_dir = f'{upload_year}-{upload_month:02d}'
    
    base_url = 'https://febiac.be/sites/default/files/media/file'
    
    # 生成所有可能的URL格式（按匹配概率排序）
    urls = []
    
    # 2026年格式: YYMM + 全下划线 (实测有效，如 2601_Cars_by_make.pdf)
    urls.append(f'{base_url}/{upload_dir}/{yymm}_Cars_by_make.pdf')
    
    # 2026年格式: YYMM + 空格 + 连字符 + 空格
    urls.append(f'{base_url}/{upload_dir}/{yymm}%20-%20Cars%20by%20make.pdf')
    
    # 2025年格式: YYMM + 下划线 + 空格
    urls.append(f'{base_url}/{upload_dir}/{yymm}_Cars%20by%20make.pdf')
    
    # 2024年格式A: MMYY + 空格 + 连字符 + 空格 + _0后缀
    urls.append(f'{base_url}/{upload_dir}/{mmyy}%20-%20Cars%20by%20make_0.pdf')
    
    # 2024年格式B: MMYY + 下划线 + 空格
    urls.append(f'{base_url}/{upload_dir}/{mmyy}_Cars%20by%20make.pdf')
    
    # 备用格式: 全下划线
    urls.append(f'{base_url}/{upload_dir}/{mmyy}_Cars_by_make.pdf')
    urls.append(f'{base_url}/{upload_dir}/{yymm}_Cars_by_make_0.pdf')
    
    # 备用格式: 空格连字符
    urls.append(f'{base_url}/{upload_dir}/{yymm}%20-%20Cars%20by%20make_0.pdf')
    urls.append(f'{base_url}/{upload_dir}/{mmyy}%20-%20Cars%20by%20make.pdf')
    
    # 尝试当月目录（有些数据可能当月发布）
    current_dir = f'{data_year}-{data_month:02d}'
    urls.append(f'{base_url}/{current_dir}/{yymm}_Cars_by_make.pdf')
    urls.append(f'{base_url}/{current_dir}/{yymm}%20-%20Cars%20by%20make.pdf')
    urls.append(f'{base_url}/{current_dir}/{yymm}_Cars%20by%20make.pdf')
    
    return urls


class FebiacCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(source_name='febiac', country_code='BE')
        self._brand_id_cache = {}
        
    def save_sales(self, record):
        """重写保存方法，自动匹配品牌ID"""
        # 自动匹配品牌ID
        if record['brand_id'] is None and record['brand_name_raw'] is not None:
            brand_id = self._match_brand(record['brand_name_raw'])
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
        
        匹配优先级:
        1. 精确匹配 canonical_name (不区分大小写)
        2. 精确匹配 brand_name_cn
        3. 去标点后精确匹配
        4. 全面标准化匹配
        5. 模糊匹配（兜底）
        """
        # 先查缓存
        if brand_raw in self._brand_id_cache:
            return self._brand_id_cache[brand_raw]
        
        conn, cur = self.get_connection()
        brand_upper = brand_raw.upper().strip()
        
        # 多层级规范化
        brand_clean = brand_upper.replace('.', '').replace(' ', '')
        brand_normalized = brand_upper.replace('.', '').replace(' ', '').replace('&', '').replace('-', '').replace(',', '')
        
        # 1. 精确匹配 canonical_name
        cur.execute("""
            SELECT id FROM brand_name_mapping
            WHERE LOWER(canonical_name) = LOWER(%s)
            LIMIT 1
        """, (brand_raw.strip(),))
        row = cur.fetchone()
        if row:
            brand_id = row['id']
            self._brand_id_cache[brand_raw] = brand_id
            return brand_id
        
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
            return brand_id
        
        # 3. 去标点后精确匹配
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
                return brand_id
        
        # 4. 全面标准化匹配
        cur.execute("""
            SELECT id FROM brand_name_mapping
            WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER(canonical_name), '.', ''), ' ', ''), '&', ''), '-', ''), ',', '') = %s
            LIMIT 1
        """, (brand_normalized.lower(),))
        row = cur.fetchone()
        if row:
            brand_id = row['id']
            self._brand_id_cache[brand_raw] = brand_id
            return brand_id
        
        # 5. 模糊匹配（兜底）
        cur.execute("""
            SELECT id FROM brand_name_mapping
            WHERE canonical_name ILIKE %s OR brand_name_cn ILIKE %s
            LIMIT 1
        """, (f'%{brand_raw}%', f'%{brand_raw}%'))
        row = cur.fetchone()
        if row:
            brand_id = row['id']
            self._brand_id_cache[brand_raw] = brand_id
            return brand_id
        
        # 6. 去标点后模糊匹配
        cur.execute("""
            SELECT id FROM brand_name_mapping
            WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER(canonical_name), '.', ''), ' ', ''), '&', ''), '-', ''), ',', '') LIKE %s
            LIMIT 1
        """, (f'%{brand_normalized.lower()}%',))
        row = cur.fetchone()
        if row:
            brand_id = row['id']
            self._brand_id_cache[brand_raw] = brand_id
            return brand_id
        
        # 未找到
        self.logger.warning(f'品牌未匹配: {brand_raw}')
        self._brand_id_cache[brand_raw] = None
        return None
    
    def download_pdf(self, data_year, data_month):
        """下载Febiac月度PDF文件（支持多URL格式尝试）"""
        urls = _get_febiac_pdf_urls(data_year, data_month)
        self.logger.info(f'尝试下载PDF，共 {len(urls)} 种URL格式')
        
        headers = self.get_headers()
        for url in urls:
            self.logger.debug(f'尝试URL: {url}')
            try:
                response = requests.get(url, headers=headers, timeout=30, verify=False)
                if response.status_code == 200 and len(response.content) > 1000:
                    self.logger.info(f'下载成功: {url} ({len(response.content)} bytes)')
                    return response.content
                else:
                    self.logger.debug(f'URL失败: status={response.status_code}, size={len(response.content)}')
            except Exception as e:
                self.logger.debug(f'URL异常: {url}, {e}')
                continue
        
        self.logger.error(f'所有URL格式均尝试失败: {data_year}-{data_month:02d}')
        return None
    
    def parse_pdf_tables(self, pdf_content):
        """解析PDF中的所有表格"""
        tables = []
        try:
            with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    page_tables = page.extract_tables()
                    for table in page_tables:
                        if table and len(table) > 3:
                            tables.append({
                                'page': page_num + 1,
                                'rows': table
                            })
            self.logger.info(f'解析到 {len(tables)} 个表格')
        except Exception as e:
            self.logger.error(f'PDF解析失败: {e}')
        return tables
    
    def _identify_brand_table(self, table_rows):
        """识别品牌销量表格
        
        特征：
        - 表头包含 "Brandname" 或 "Merk" 或 "Marque"
        - 包含数字列（销量数据）
        - 不是累计表（Cumul）
        """
        if not table_rows or len(table_rows) < 5:
            return False
        
        # 检查前几行是否包含品牌表头关键字
        header_text = ''
        for row in table_rows[:5]:
            row_text = ' '.join([str(c).upper() if c else '' for c in row])
            header_text += ' ' + row_text
        
        header_text = header_text.strip()
        
        # 必须包含品牌列关键字
        brand_keywords = ['BRANDNAME', 'MERK', 'MARQUE', 'BRAND']
        has_brand_col = any(kw in header_text for kw in brand_keywords)
        
        # 跳过累计表（Cumul/Cumulative）
        is_cumul = 'CUMUL' in header_text.upper() or 'CUMULATIVE' in header_text.upper()
        
        return has_brand_col and not is_cumul
    
    def _split_merged_row(self, row):
        """处理合并行问题
        
        PDF中可能出现两个品牌挤在一行的情况：
        如: ['7 8', 'DACIA RENAULT', '1 331 1 283', ...]
        
        处理后拆分为两行：
        ['7', 'DACIA', '1 331', ...]
        ['8', 'RENAULT', '1 283', ...]
        """
        cells = [str(c).strip() if c else '' for c in row]
        
        # 检查品牌列（index 1）是否包含多个品牌
        if len(cells) > 1:
            brand_cell = cells[1]
            # 常见合并模式：两个品牌名用空格分隔
            # 如 "DACIA RENAULT" 或 "JAGUAR LAND ROVER"
            if brand_cell and len(brand_cell.split()) >= 2:
                parts = brand_cell.split()
                # 检查数字列是否也有合并
                if len(cells) > 2:
                    sales_cell = cells[2]
                    sales_parts = sales_cell.split()
                    # 如果销量列也有多个数字，尝试拆分
                    if len(sales_parts) >= 2:
                        return None  # 交给标准解析处理
        
        return None  # 无需拆分
    
    def _parse_brand_row(self, row, data_year, data_month):
        """解析品牌行数据
        
        列结构（2026年格式）:
        [排名, 品牌名, 当月销量, 占比%, 去年同期, 去年占比%, 同比变化, 同比%]
        
        列结构（2025年格式）:
        [排名, 品牌名, 当月销量, 占比%, 去年同期, 去年占比%, 同比变化, 同比%]
        """
        cells = [str(c).strip() if c else '' for c in row]
        
        # 最少需要3列（排名+品牌+销量）
        if len(cells) < 3:
            return None
        
        # 提取品牌名（第2列，index 1）
        brand_raw = cells[1].strip()
        
        # 跳过非数据行
        if not brand_raw:
            return None
        if brand_raw.upper() in SKIP_BRANDS:
            return None
        # 跳过表头行
        if brand_raw.upper() in ('BRANDNAME', 'MERK', 'MARQUE', 'BRAND', 'NAAM'):
            return None
        # 跳过包含"Total"的行
        if 'TOTAL' in brand_raw.upper() or 'TOTAAL' in brand_raw.upper():
            return None
        # 跳过空数据行（用'-'表示）
        if brand_raw == '-':
            return None
        # 跳过月份标题行（如 "July", "January" 等）
        brand_upper = brand_raw.upper().strip()
        if brand_upper in MONTH_KEYWORDS:
            return None
        # 跳过年份数字（如 "2026", "2025" 单独出现）
        if brand_raw.isdigit() and len(brand_raw) == 4:
            return None
        
        # 清理品牌名（移除排名前缀）
        brand_clean = _clean_brand_name(brand_raw)
        if not brand_clean:
            return None
        
        # 提取当月销量（第3列，index 2）
        sales_raw = cells[2] if len(cells) > 2 else ''
        sales_volume = _belgian_number_to_int(sales_raw)
        
        if sales_volume is None or sales_volume <= 0:
            return None
        
        # 构建记录（source_month 必须是完整日期格式 YYYY-MM-01）
        source_month = f'{data_year}-{data_month:02d}-01'
        
        record = {
            'country_code': 'BE',
            'source_month': source_month,
            'brand_name_raw': brand_clean,
            'brand_id': None,  # 将在 save_sales 中自动匹配
            'model_name': None,
            'vehicle_type': 'PC',  # 乘用车
            'energy_type': 'UNKNOWN',  # Cars by make不含能源类型
            'segment': None,
            'raw_unit': 'units',
            'sales_volume_raw': sales_volume,
            'sales_volume_normalized': sales_volume,
            'revision_no': 1,
            'is_latest': True,
            'pub_date': date(data_year, data_month, 15),  # 假设月中发布
            'crawl_time': datetime.now(),
            'data_source': 'febiac.be',
            'notes': 'Cars by make PDF',
        }
        
        return record
    
    def crawl_month(self, data_year, data_month):
        """爬取单个月份数据"""
        self.logger.info(f'开始爬取 {data_year}-{data_month:02d}')
        
        # 先检查是否已存在
        source_month = f'{data_year}-{data_month:02d}-01'
        conn, cur = self.get_connection()
        cur.execute("""
            SELECT COUNT(*) as cnt FROM market_sales_monthly
            WHERE country_code = 'BE' AND source_month = %s AND is_latest = TRUE
        """, (source_month,))
        existing = cur.fetchone()['cnt']
        
        if existing > 0:
            self.logger.info(f'{source_month} 已有 {existing} 条数据，跳过')
            return existing
        
        # 下载PDF
        pdf_content = self.download_pdf(data_year, data_month)
        if not pdf_content:
            self.logger.warning(f'{source_month} PDF下载失败')
            return 0
        
        # 解析表格
        tables = self.parse_pdf_tables(pdf_content)
        if not tables:
            self.logger.warning(f'{source_month} 无解析到表格')
            return 0
        
        # 处理每个表格
        saved_count = 0
        for table_info in tables:
            rows = table_info['rows']
            
            # 识别是否为品牌销量表
            if not self._identify_brand_table(rows):
                continue
            
            # 解析每一行
            for row in rows:
                record = self._parse_brand_row(row, data_year, data_month)
                if record:
                    success = self.save_sales(record)
                    if success:
                        saved_count += 1
        
        self.logger.info(f'{source_month} 保存 {saved_count} 条记录')
        return saved_count
    
    def crawl_range(self, start_year, start_month, end_year, end_month):
        """爬取指定时间范围的数据"""
        self.logger.info(f'开始爬取 {start_year}-{start_month:02d} 至 {end_year}-{end_month:02d}')
        
        total_saved = 0
        current_year, current_month = start_year, start_month
        
        while (current_year, current_month) <= (end_year, end_month):
            # 随机延迟
            self.random_delay()
            
            # 爬取当月
            saved = self.crawl_month(current_year, current_month)
            total_saved += saved
            
            # 批次长休
            self.page_count += 1
            self.batch_restart()
            
            # 移动到下一月
            current_month += 1
            if current_month > 12:
                current_month = 1
                current_year += 1
        
        self.logger.info(f'爬取完成，共保存 {total_saved} 条记录')
        return total_saved


if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    crawler = FebiacCrawler()
    
    try:
        # 爬取 2024-01 至 2026-07
        total = crawler.crawl_range(2024, 1, 2026, 7)
        print(f'\n爬取完成！共保存 {total} 条记录')
    except Exception as e:
        print(f'爬取异常: {e}')
        import traceback
        traceback.print_exc()
    finally:
        crawler.close()