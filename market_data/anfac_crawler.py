# -*- coding: utf-8 -*-
"""
ANFAC 西班牙汽车销量爬虫

数据源: ANFAC 月度数据 PDF
URL格式: https://anfac.com/wp-content/uploads/{发布年}/{发布月}/NP-Matriculaciones-{西班牙语月份}-{年份}-COMPLETA.pdf
数据类型: 乘用车(Turismos)、商用车(Comerciales Ligeros)
特点: 品牌级数据 + 车型级数据，PDF结构相对稳定
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

# 西班牙语月份映射（数字 -> 全名）
SPANISH_MONTH_MAP = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
    5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
    9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
}

# 西班牙语月份缩写映射
SPANISH_MONTH_ABBR = {
    1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr',
    5: 'May', 6: 'Jun', 7: 'Jul', 8: 'Ago',
    9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic'
}

# 需要跳过的行
SKIP_ROWS = {'TOTAL', 'Total', 'Source', 'Fuente', 'Datos', 'Elaborados'}


def _spanish_number_to_int(num_str):
    """西班牙语数字格式转整数：'9.473' -> 9473, '1.116.725' -> 1116725"""
    if not num_str or num_str.strip() == '':
        return None
    # 移除空格
    cleaned = num_str.replace(' ', '').replace('\xa0', '')
    # 检查是否为百分比或特殊值
    if cleaned == '--' or cleaned == '---':
        return None
    # 移除千分位分隔符（西班牙语使用.作为千分位）
    cleaned = cleaned.replace('.', '')
    try:
        return int(cleaned)
    except ValueError:
        return None


def _spanish_pct_to_float(pct_str):
    """西班牙语百分比转浮点：'23,2%' -> 23.2, '--' -> None"""
    if not pct_str or pct_str.strip() == '':
        return None
    cleaned = pct_str.strip()
    if cleaned == '--' or cleaned == '---' or cleaned == '++':
        return None
    # 移除百分号和加号
    cleaned = cleaned.replace('%', '').replace('+', '')
    # 西班牙语使用逗号作为小数点
    cleaned = cleaned.replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return None


def _get_pdf_urls(data_year, data_month):
    """生成ANFAC月度数据PDF URL列表
    
    data_year: 数据年份
    data_month: 数据月份 (1-12)
    
    返回: [(url, 发布年, 发布月), ...] 元组列表（按优先级排序）
    """
    # 发布年月 = 数据月+1，12月发布在次年1月
    pub_month = data_month + 1
    pub_year = data_year
    if pub_month > 12:
        pub_month = 1
        pub_year += 1
    
    month_name = SPANISH_MONTH_MAP.get(data_month, '')
    month_abbr = SPANISH_MONTH_ABBR.get(data_month, '')
    
    # 生成多种可能的URL格式（按优先级排序）
    urls = [
        # 格式1: NP-Matriculaciones-{月份}-{年份}-COMPLETA.pdf（主格式）
        f'https://anfac.com/wp-content/uploads/{pub_year}/{pub_month:02d}/NP-Matriculaciones-{month_name}-{data_year}-COMPLETA.pdf',
        # 格式2: NP-Matriculaciones-{缩写}-{年份}-COMPLETA.pdf
        f'https://anfac.com/wp-content/uploads/{pub_year}/{pub_month:02d}/NP-Matriculaciones-{month_abbr}-{data_year}-COMPLETA.pdf',
        # 格式3: Nota-de-prensa-Matriculaciones-{月份}-{年份}.pdf
        f'https://anfac.com/wp-content/uploads/{pub_year}/{pub_month:02d}/Nota-de-prensa-Matriculaciones-{month_name}-{data_year}.pdf',
        # 格式4: Nota-de-Prensa-Completa-{月份}-{年份}.pdf（12月特殊格式）
        f'https://anfac.com/wp-content/uploads/{pub_year}/{pub_month:02d}/Nota-de-Prensa-Completa-{month_name}-{data_year}.pdf',
        # 格式5: Informe-Matriculaciones-CCAA-{月份}-{年份}.pdf
        f'https://anfac.com/wp-content/uploads/{pub_year}/{pub_month:02d}/Informe-Matriculaciones-CCAA-{month_name}-{data_year}.pdf',
    ]
    
    return [(url, pub_year, pub_month) for url in urls]


class AnfacCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(source_name='anfac', country_code='ES')
        self._brand_id_cache = {}  # 品牌ID缓存

    def save_sales(self, record):
        """重写保存方法，在去重条件中包含vehicle_type，支持能源类型数据（无品牌）"""
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
                  AND brand_name_raw IS NOT DISTINCT FROM %(brand_name_raw)s
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
        """品牌匹配：查brand_name_mapping表获取brand_id"""
        if not brand_raw or brand_raw.strip() == '':
            return None, False

        # 先查缓存
        if brand_raw in self._brand_id_cache:
            return self._brand_id_cache[brand_raw], False

        conn, cur = self.get_connection()
        brand_upper = brand_raw.upper().strip()

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

        # 3. 标准化匹配（处理特殊字符）
        # 移除所有特殊字符进行匹配
        brand_clean = brand_upper.replace('.', '').replace(' ', '')
        brand_normalized = brand_upper.replace('.', '').replace(' ', '').replace('&', '').replace('-', '').replace(',', '')

        # 3a. 移除点和空格匹配
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

        # 3b. 移除所有特殊字符匹配（处理 &、- 等）
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

        # 4. 模糊匹配（兜底）
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

        # 未找到
        self.logger.warning(f'品牌未匹配: {brand_raw}')
        self._brand_id_cache[brand_raw] = None
        return None, False

    def download_pdf(self, data_year, data_month):
        """下载ANFAC月度数据PDF文件"""
        urls = _get_pdf_urls(data_year, data_month)
        self.logger.info(f'尝试下载PDF，共 {len(urls)} 种URL格式')

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

        self.logger.error(f'所有URL格式均尝试失败: {data_year}-{data_month:02d}')
        return None

    def parse_pdf_tables(self, pdf_content):
        """解析PDF中的所有表格"""
        tables = []
        try:
            with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    # 获取页面文本（用于能源类型识别）
                    page_text = page.extract_text() or ''
                    page_tables = page.extract_tables()
                    for table in page_tables:
                        if table and len(table) > 2:
                            tables.append({
                                'page': page_num + 1,
                                'rows': table,
                                'page_text': page_text  # 保存页面文本
                            })
            self.logger.info(f'解析到 {len(tables)} 个表格')
        except Exception as e:
            self.logger.error(f'PDF解析失败: {e}')
        return tables

    def _identify_table_type(self, table_rows, page_text=''):
        """识别表格类型
        
        返回: 'BRAND' (品牌级), 'MODEL' (车型级), 'LCV_BRAND' (商用车品牌级), 
              'ENERGY' (能源类型), None
        """
        if not table_rows or len(table_rows) < 5:
            return None

        # 检查所有行来构建表头文本
        all_header_text = ''
        for row in table_rows[:6]:
            row_text = ' '.join([str(cell).upper().replace('\n', ' ') if cell else '' for cell in row])
            all_header_text += ' ' + row_text

        all_header_text = all_header_text.strip()

        if not all_header_text:
            return None

        # 能源类型表格检查（优先检查，因为能源表格可能包含类似结构）
        # 需要结合页面文本判断能源类型
        page_text_upper = page_text.upper() if page_text else ''
        
        # 能源类型特征：页面文本包含能源关键词 + 表格包含Volumen/Cuota列
        energy_keywords = ['GASOLINA', 'DIÉSEL', 'DIESEL', 'RESTO COMBUSTIBLES']
        has_energy_keyword = any(kw in page_text_upper for kw in energy_keywords)
        has_volume_column = 'VOLUMEN' in all_header_text or 'CUOTA' in all_header_text
        
        if has_energy_keyword and has_volume_column and 'SEGMENTOS' in page_text_upper:
            return 'ENERGY'

        # 品牌级表格：标题包含 "POR MARCA" 但不包含 "Y MODELO"
        if 'POR MARCA' in all_header_text and 'MODELO' not in all_header_text:
            return 'BRAND'

        # 车型级表格：标题包含 "POR MARCA Y MODELO"
        if 'POR MARCA Y MODELO' in all_header_text:
            return 'MODEL'

        # 商用车品牌级表格：包含特定商用车标题
        if ('DERIVADOS, FURGONETAS Y PICK-UP' in all_header_text or
            'FURGONES Y CAMIONES/CHASIS LIGEROS' in all_header_text) and 'MARCA' in all_header_text:
            return 'LCV_BRAND'

        return None

    def _parse_brand_row(self, row, data_year, data_month, vehicle_type='VP'):
        """解析品牌级表格的一行数据
        
        列结构: MARCA | Marzo 2025 | Marzo 2024 | % Cto. | Enero-Marzo 2025 | Enero-Marzo 2024 | % Cto.
        """
        cells = [str(c).strip() if c else '' for c in row]
        if len(cells) < 3:
            return None

        # 品牌在第1列（index 0）
        brand_raw = cells[0].strip()

        # 跳过非数据行
        if not brand_raw or brand_raw in SKIP_ROWS:
            return None
        if brand_raw.startswith('Source') or brand_raw.startswith('Fuente') or brand_raw.startswith('Datos'):
            return None
        # 跳过表头
        if brand_raw.upper() in ('MARCA', 'MARCA ', 'MARCAS'):
            return None
        # 跳过分组标题行
        if brand_raw.upper().startswith('MOTOR') or brand_raw.upper().startswith('DERIVADOS'):
            return None
        # 跳过汇总行（Total/Tot.开头）
        brand_upper = brand_raw.upper()
        if brand_upper.startswith('TOTAL') or brand_upper.startswith('TOT.') or brand_upper.startswith('TOTAL '):
            return None

        # 当月销量在第2列（index 1）
        sales = _spanish_number_to_int(cells[1])
        if sales is None or sales <= 0:
            return None

        # 同比变化在第4列（index 3）
        variation = _spanish_pct_to_float(cells[3]) if len(cells) > 3 else None

        brand_id, should_skip = self._match_brand(brand_raw)
        if brand_id is None:
            self.logger.debug(f'跳过未匹配品牌: {brand_raw}')
            return None

        record = {
            'country_code': 'ES',
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
            'data_source': f'ANFAC_{vehicle_type}_Matriculaciones',
            'notes': f'ANFAC_{vehicle_type}_{data_year}-{data_month:02d} | variation={variation}% | brand_level',
        }
        return record

    def _parse_lcv_brand_row(self, row, data_year, data_month):
        """解析商用车品牌级表格的一行数据"""
        cells = [str(c).strip() if c else '' for c in row]
        if len(cells) < 3:
            return None

        # 品牌在第1列（index 0）
        brand_raw = cells[0].strip()

        if not brand_raw or brand_raw in SKIP_ROWS:
            return None
        # 跳过表头和分组标题
        brand_upper = brand_raw.upper()
        if brand_upper in ('MARCA', 'MARCAS', 'DERIVADOS', 'FURGONETAS', 'PICK-UP'):
            return None
        # 跳过汇总行
        if brand_upper.startswith('TOTAL') or brand_upper.startswith('TOT.'):
            return None
        # 跳过分类标题行
        if brand_upper.startswith('COMERCIALES') or brand_upper.startswith('FURGON/') or brand_upper.startswith('CAMI'):
            return None

        # 当月销量在第2列（index 1）
        sales = _spanish_number_to_int(cells[1])
        if sales is None or sales <= 0:
            return None

        # 同比变化在第4列（index 3）
        variation = _spanish_pct_to_float(cells[3]) if len(cells) > 3 else None

        brand_id, should_skip = self._match_brand(brand_raw)
        if brand_id is None:
            self.logger.debug(f'跳过未匹配品牌(LCV): {brand_raw}')
            return None

        record = {
            'country_code': 'ES',
            'source_month': f'{data_year}-{data_month:02d}-01',
            'brand_name_raw': brand_raw,
            'brand_id': brand_id,
            'model_name': None,
            'vehicle_type': 'VUL',  # 轻型商用车
            'energy_type': None,
            'segment': None,
            'raw_unit': 'unit',
            'sales_volume_raw': sales,
            'sales_volume_normalized': sales,
            'revision_no': 1,
            'is_latest': True,
            'pub_date': f'{data_year}-{data_month:02d}-01',
            'crawl_time': datetime.now(),
            'data_source': 'ANFAC_LCV_Matriculaciones',
            'notes': f'ANFAC_VUL_{data_year}-{data_month:02d} | variation={variation}% | lcv_brand_level',
        }
        return record

    def _parse_energy_row(self, row, data_year, data_month, energy_type, page_text=''):
        """解析能源类型表格的一行数据（TOTAL行）
        
        能源类型表格结构:
        列0: 'TOTAL' 或细分市场名称
        列1: '38.466 100%' (当月销量 + 份额)
        列2: 空
        列3: '40.316 100%' (去年同期销量 + 份额)
        列4: 空
        列5: '-4,59%' (同比变化)
        列6: '87.772 100%' (累计销量 + 份额)
        列7: 空
        列8: '96.963 100%' (去年累计销量 + 份额)
        列9: 空
        列10: '-9,48%' (累计同比变化)
        """
        cells = [str(c).strip() if c else '' for c in row]
        if len(cells) < 6:
            return None

        # 只处理TOTAL行（能源类型汇总）
        first_cell = cells[0].strip().upper()
        if first_cell != 'TOTAL':
            return None

        # 解析当月销量（从'38.466 100%'格式中提取）
        volume_text = cells[1].strip()
        if not volume_text:
            return None
        
        # 分割销量和份额（格式: "38.466 100%"）
        parts = volume_text.split()
        if len(parts) >= 1:
            sales = _spanish_number_to_int(parts[0])
        else:
            sales = _spanish_number_to_int(volume_text)
        
        if sales is None or sales <= 0:
            return None

        # 解析当月份额
        share = None
        if len(parts) >= 2:
            share = _spanish_pct_to_float(parts[1])

        # 解析同比变化
        variation = _spanish_pct_to_float(cells[5]) if len(cells) > 5 else None

        # 解析累计销量
        cumulative_volume = None
        if len(cells) > 6 and cells[6]:
            cum_parts = cells[6].split()
            if len(cum_parts) >= 1:
                cumulative_volume = _spanish_number_to_int(cum_parts[0])

        # 规范化能源类型名称
        energy_type_normalized = self._normalize_energy_type(energy_type, page_text)

        record = {
            'country_code': 'ES',
            'source_month': f'{data_year}-{data_month:02d}-01',
            'brand_name_raw': None,  # 能源类型数据无品牌
            'brand_id': None,
            'model_name': None,
            'vehicle_type': 'VP',
            'energy_type': energy_type_normalized,
            'segment': None,
            'raw_unit': 'unit',
            'sales_volume_raw': sales,
            'sales_volume_normalized': sales,
            'revision_no': 1,
            'is_latest': True,
            'pub_date': f'{data_year}-{data_month:02d}-01',
            'crawl_time': datetime.now(),
            'data_source': 'ANFAC_Energy_Matriculaciones',
            'notes': f'ANFAC_ENERGY_{energy_type_normalized}_{data_year}-{data_month:02d} | share={share}% | variation={variation}% | cumulative={cumulative_volume}',
        }
        return record

    def _normalize_energy_type(self, energy_type, page_text=''):
        """规范化能源类型名称
        
        ANFAC能源类型: GASOLINA, DIÉSEL/DIESEL, RESTO COMBUSTIBLES
        RESTO COMBUSTIBLES包含: BEV, PHEV, HEV, EREV, FCEV, GNC, GNL, GLP
        """
        text = (energy_type or '').upper()
        
        if 'GASOLINA' in text:
            return 'GASOLINA'
        elif 'DIÉSEL' in text or 'DIESEL' in text:
            return 'DIESEL'
        elif 'RESTO' in text and 'COMBUSTIBLE' in text:
            return 'RESTO_COMBUSTIBLES'
        else:
            # 从页面文本推断
            page_upper = (page_text or '').upper()
            if 'GASOLINA' in page_upper:
                return 'GASOLINA'
            elif 'DIÉSEL' in page_upper or 'DIESEL' in page_upper:
                return 'DIESEL'
            elif 'RESTO COMBUSTIBLES' in page_upper:
                return 'RESTO_COMBUSTIBLES'
            return 'UNKNOWN'

    def _get_energy_type_from_page(self, page_text):
        """从页面文本推断能源类型"""
        if not page_text:
            return None
        
        text_upper = page_text.upper()
        
        # 检查GASOLINA
        if 'GASOLINA' in text_upper:
            return 'GASOLINA'
        # 检查DIÉSEL/DIESEL
        if 'DIÉSEL' in text_upper or 'DIESEL' in text_upper:
            return 'DIESEL'
        # 检查RESTO COMBUSTIBLES
        if 'RESTO COMBUSTIBLES' in text_upper:
            return 'RESTO_COMBUSTIBLES'
        
        return None

    def extract_records_from_tables(self, tables, data_year, data_month):
        """从所有表格提取销售记录"""
        records = []

        for table_info in tables:
            page_text = table_info.get('page_text', '')
            table_type = self._identify_table_type(table_info['rows'], page_text)
            if not table_type:
                continue

            self.logger.info(f'识别表格类型: {table_type} (page {table_info["page"]})')

            if table_type == 'ENERGY':
                # 能源类型表格：只提取TOTAL行（第3行，index 3）
                energy_type = self._get_energy_type_from_page(page_text)
                if energy_type:
                    total_row = table_info['rows'][3] if len(table_info['rows']) > 3 else None
                    if total_row:
                        record = self._parse_energy_row(total_row, data_year, data_month, energy_type, page_text)
                        if record:
                            records.append(record)
                            self.logger.info(f'能源类型: {energy_type}, 销量: {record["sales_volume_normalized"]}')
            else:
                # 其他类型表格：跳过表头行，从数据行开始解析
                for row in table_info['rows'][3:]:  # 前3行是表头
                    if table_type == 'BRAND':
                        record = self._parse_brand_row(row, data_year, data_month, 'VP')
                        if record:
                            records.append(record)
                    elif table_type == 'LCV_BRAND':
                        record = self._parse_lcv_brand_row(row, data_year, data_month)
                        if record:
                            records.append(record)
                    # MODEL类型暂不处理（车型级数据）

        return records

    def crawl_month(self, data_year, data_month):
        """爬取指定月份数据"""
        self.logger.info(f'=== 开始爬取 {data_year}-{data_month:02d} ===')

        pdf_content = self.download_pdf(data_year, data_month)
        if not pdf_content:
            self.logger.warning(f'{data_year}-{data_month:02d} PDF下载失败，跳过')
            return 0

        tables = self.parse_pdf_tables(pdf_content)
        if not tables:
            self.logger.warning(f'{data_year}-{data_month:02d} 无表格数据')
            return 0

        records = self.extract_records_from_tables(tables, data_year, data_month)
        self.logger.info(f'提取到 {len(records)} 条记录')

        saved_count = 0
        for record in records:
            if self.save_sales(record):
                saved_count += 1

        self.logger.info(f'{data_year}-{data_month:02d}: 保存 {saved_count} 条记录')
        return saved_count

    def crawl_range(self, start_year, start_month, end_year, end_month):
        """爬取时间范围"""
        self.logger.info(f'=== ANFAC西班牙销量爬虫启动 ===')
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
    crawler = AnfacCrawler()

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
