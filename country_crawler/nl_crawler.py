# -*- coding: utf-8 -*-
"""
BOVAG/RAI 荷兰汽车销量爬虫

数据源: BOVAG/RAAI Vereniging 月度乘用车销量报告
数据来源: https://www.bovag.nl/pers/persberichten/
下载链接: Sanity CDN (https://cdn.sanity.io/files/j02l2p79/production_bovag/)
数据格式: PDF表格 - 品牌/车型 + 本月 + 本年累计 + 上月 + 上年同期

特点:
- 需要从sitemap获取新闻稿URL，再从页面提取PDF下载链接
- PDF为品牌+车型层级数据，需解析多品牌多车型
- 数字格式使用点号作为千分位（如"1.255" = 1255）
"""
import os
import sys
import re
import io
import time
import random
import logging
import requests
import pdfplumber
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_crawler import BaseCrawler


# 荷兰品牌名标准化映射
NL_BRAND_MAP = {
    'MERCEDES-BENZ': 'MERCEDES-BENZ',
    'MERCEDES BENZ': 'MERCEDES-BENZ',
    'MERCEDES': 'MERCEDES-BENZ',
    'MB': 'MERCEDES-BENZ',
    'LAND ROVER': 'LAND ROVER',
    'LANDROVER': 'LAND ROVER',
    'LYNK & CO': 'LYNK&CO',
    'LYNKCO': 'LYNK&CO',
    'LYNK': 'LYNK&CO',
    'ALFA ROMEO': 'ALFA ROMEO',
    'ALFA': 'ALFA ROMEO',
    'VOLKSWAGEN': 'VOLKSWAGEN',
    'VW': 'VOLKSWAGEN',
    'BMW': 'BMW',
    'MERCEDES-BENZ': 'MERCEDES-BENZ',
    'BENTLEY': 'BENTLEY',
    'ROLLS-ROYCE': 'ROLLS-ROYCE',
    'ROLLS ROYCE': 'ROLLS-ROYCE',
    'MASERATI': 'MASERATI',
    'LAMBORGHINI': 'LAMBORGHINI',
    'FERRARI': 'FERRARI',
    'PORSCHE': 'PORSCHE',
    'ASTON MARTIN': 'ASTON MARTIN',
    'ASTONMARTIN': 'ASTON MARTIN',
    'MCLAREN': 'MCLAREN',
    'BUGATTI': 'BUGATTI',
    'KOENIGSEGG': 'KOENIGSEGG',
    'PAGANI': 'PAGANI',
    'FISKER': 'FISKER',
    'AIWAYS': 'AIWAYS',
    'NIO': 'NIO',
    'XPENG': 'XPENG',
    'LEAPMOTOR': 'LEAPMOTOR',
    'MAXUS': 'MAXUS',
    'CUPRA': 'CUPRA',
    'SEAT': 'SEAT',
    'SKODA': 'SKODA',
    'ŠKODA': 'SKODA',
    'DACI': 'DACIA',
    'DACIA': 'DACIA',
    'RENAULT': 'RENAULT',
    'PEUGEOT': 'PEUGEOT',
    'CITROEN': 'CITROEN',
    'DS': 'DS',
    'OPEL': 'OPEL',
    'VAUXHALL': 'OPEL',
    'FORD': 'FORD',
    'TOYOTA': 'TOYOTA',
    'HONDA': 'HONDA',
    'MAZDA': 'MAZDA',
    'NISSAN': 'NISSAN',
    'SUBARU': 'SUBARU',
    'SUZUKI': 'SUZUKI',
    'MITSUBISHI': 'MITSUBISHI',
    'KIA': 'KIA',
    'HYUNDAI': 'HYUNDAI',
    'GENESIS': 'GENESIS',
    'SSANGYONG': 'SSANGYONG',
    'KGM': 'KGM',
    'MG': 'MG',
    'SAIC': 'SAIC',
    'BYD': 'BYD',
    'GEELY': 'GEELY',
    'CHERY': 'CHERY',
    'GREAT WALL': 'GREAT WALL',
    'HAVAL': 'HAVAL',
    'JETOUR': 'JETOUR',
    'EXEED': 'EXEED',
    'CHANGAN': 'CHANGAN',
    'DONGFENG': 'DONGFENG',
    'DFSK': 'DFSK',
    'FAW': 'FAW',
    'SAIC MAXUS': 'MAXUS',
    'VOYAH': 'VOYAH',
    'AITO': 'AITO',
    'SERES': 'SERES',
    'JEEP': 'JEEP',
    'LANCIA': 'LANCIA',
    'FIAT': 'FIAT',
    'ABARTH': 'ABARTH',
    'ALPINE': 'ALPINE',
    'BUGATTI': 'BUGATTI',
}

# 需要跳过的汇总行
SKIP_KEYWORDS = {'TOTAAL', 'TOTAL', 'MERK', 'MODEL', 'MERK/MODEL', 'MERCEDES-BENZ'}

# 荷兰语月份缩写
MONTHS_NL = {
    'jan': 1, 'januari': 1, 'feb': 2, 'februari': 2,
    'mrt': 3, 'maart': 3, 'apr': 4, 'april': 4,
    'mei': 5, 'jun': 6, 'juni': 6,
    'jul': 7, 'juli': 7, 'aug': 8, 'augustus': 8,
    'sep': 9, 'september': 9, 'okt': 10, 'oktober': 10,
    'nov': 11, 'november': 11, 'dec': 12, 'december': 12
}


def _dutch_number_to_int(num_str):
    """荷兰数字格式转整数：'1.255' -> 1255, '25.601' -> 25601"""
    if not num_str or num_str.strip() in ('', '-', '—'):
        return None
    # 移除空格
    cleaned = num_str.strip().replace(' ', '')
    # 移除千分位点号（荷兰用点号做千分位）
    if '.' in cleaned:
        cleaned = cleaned.replace('.', '')
    # 如果还有逗号，可能是小数点
    if ',' in cleaned:
        # 荷兰逗号是小数点，乘1000转整数
        parts = cleaned.split(',')
        if len(parts) == 2 and len(parts[1]) == 3:
            # 可能是千分位的另一种格式
            cleaned = parts[0] + parts[1]
        else:
            cleaned = parts[0]
    try:
        val = int(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


def _extract_month_from_text(text):
    """从文本中提取月份
    
    格式示例:
    - "1 mei-31 mei" -> 5
    - "1 jan.-31 mei" -> 5 (取结束月份)
    - "1 mrt.-31 mrt." -> 3
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    # 匹配 "数字-月份" 模式
    # 如 "1 mei-31 mei" 或 "1 jan.-31 mei"
    pattern = r'(\d{1,2})\s*(januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec)\.?\s*-\s*(\d{1,2})\s*(januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|jan|feb|mrt|apr|jun|jul|aug|sep|okt|nov|dec)\.?'
    
    match = re.search(pattern, text_lower)
    if match:
        start_month_name = match.group(2)
        end_month_name = match.group(4)
        
        # 取结束月份作为数据月份
        end_month = MONTHS_NL.get(end_month_name)
        if end_month:
            return end_month
    
    return None


def _extract_year_from_text(text):
    """从文本中提取当前年份
    
    PDF格式:
    - "2026 2025" -> 当前年是2026（左边的年份）
    - 单个年份 -> 直接返回
    """
    if not text:
        return None
    
    years = re.findall(r'\b(20[0-9]{2})\b', text)
    if not years:
        return None
    
    # 如果有两个年份，左边的是当前年
    if len(years) >= 2:
        return int(years[0])
    
    # 单个年份
    return int(years[0])


class BovagCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(source_name='bovag', country_code='NL')
        self._brand_id_cache = {}
        self.session = requests.Session()
        # 使用自定义headers，不继承BaseCrawler的Accept-Encoding
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'nl-NL,nl;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
        })
        
    def _get_sitemap_urls(self):
        """从BOVAG sitemap获取新闻稿URL列表"""
        self.logger.info('获取BOVAG sitemap...')
        
        try:
            # 直接使用自定义headers获取sitemap
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
            }
            r = requests.get('https://www.bovag.nl/sitemap.xml', headers=headers, timeout=30)
            if r.status_code != 200:
                self.logger.error(f'Sitemap获取失败: {r.status_code}')
                return []
            
            # 提取persberichten URL
            urls = re.findall(r'<loc>(https://www\.bovag\.nl/pers/persberichten/[^<]+)</loc>', r.text)
            
            self.logger.info(f'Sitemap中找到 {len(urls)} 个persberichten URL')
            
            # 更精确的筛选：必须同时包含销量关键词
            # 优先级高的关键词（强相关）
            strong_keywords = ['autoverkoop', 'autoregistratie', 'personenauto', 'nieuwe-auto', 'verkooprecord']
            # 辅助关键词（弱相关）
            weak_keywords = ['verkoop', 'registratie', 'nieuwe']
            
            filtered_urls = []
            for url in urls:
                url_lower = url.lower()
                # 必须包含至少一个强关键词
                has_strong = any(kw in url_lower for kw in strong_keywords)
                # 或者包含"verkoop"和"auto"两个词
                has_both = 'verkoop' in url_lower and 'auto' in url_lower
                
                if has_strong or has_both:
                    filtered_urls.append(url)
            
            self.logger.info(f'筛选后相关URL: {len(filtered_urls)} 个 (精确筛选)')
            return filtered_urls
            
        except Exception as e:
            self.logger.error(f'Sitemap获取异常: {e}')
            import traceback
            traceback.print_exc()
            return []
    
    def _extract_pdf_from_page(self, page_url):
        """从新闻稿页面提取PDF下载链接"""
        try:
            r = self.session.get(page_url, timeout=15)
            if r.status_code != 200:
                self.logger.warning(f'页面获取失败 {page_url}: status={r.status_code}')
                return None
            
            # 查找Sanity CDN PDF链接
            pdf_links = re.findall(r'https://cdn\.sanity\.io/files/[^\s"\')]+?\.pdf', r.text)
            
            if pdf_links:
                # 去重并返回第一个
                unique_links = list(set(pdf_links))
                if len(unique_links) > 1:
                    self.logger.debug(f'页面有 {len(unique_links)} 个PDF链接: {unique_links[:3]}...')
                return unique_links[0]
            
            # 调试：检查页面是否包含Sanity CDN
            sanity_count = r.text.count('sanity.io')
            if sanity_count > 0:
                self.logger.debug(f'页面包含 {sanity_count} 个sanity.io引用但未匹配到PDF链接')
                # 尝试其他模式
                other_pdfs = re.findall(r'href="([^"]*sanity[^"]*\.pdf[^"]*)"', r.text, re.IGNORECASE)
                if other_pdfs:
                    self.logger.debug(f'其他PDF链接模式匹配: {other_pdfs[:2]}')
            
            self.logger.debug(f'页面无PDF链接: {page_url} (页面长度: {len(r.text)}, sanity.io引用: {sanity_count})')
            return None
            
        except Exception as e:
            self.logger.warning(f'页面访问失败 {page_url}: {e}')
            import traceback
            traceback.print_exc()
            return None
    
    def download_pdf(self, pdf_url):
        """下载PDF文件"""
        try:
            r = self.session.get(pdf_url, timeout=60, stream=True)
            if r.status_code == 200 and len(r.content) > 1000:
                self.logger.info(f'PDF下载成功: {pdf_url} ({len(r.content)} bytes)')
                return r.content
            else:
                self.logger.warning(f'PDF下载失败: status={r.status_code}')
                return None
        except Exception as e:
            self.logger.error(f'PDF下载异常: {e}')
            return None
    
    def parse_pdf(self, pdf_content):
        """解析BOVAG PDF文件，提取品牌销量数据
        
        PDF结构:
        - 首页标题: "RAI BOVAG Persbericht Verkopen Personenauto's"
        - 周期信息: "1 mei-31 mei 1 jan.-31 mei"
        - 表头: "MERK / MODEL"
        - 数据行: "AUDI Q3 164 1.141 14 154"
        - 品牌汇总行: "AUDI 1.255 5.956 1.213 6.013"
        
        列含义:
        - 本月销量 (当月)
        - 本年累计 (YTD)
        - 上月销量
        - 上年同期累计
        """
        records = []
        
        try:
            with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
                # 从首页提取周期信息
                first_page = pdf.pages[0]
                first_page_text = first_page.extract_text() or ''
                
                # 提取年份和月份
                year = _extract_year_from_text(first_page_text)
                month = _extract_month_from_text(first_page_text)
                
                self.logger.info(f'PDF周期: {year}年{month}月')
                
                if not year or not month:
                    self.logger.warning('无法从PDF提取周期信息')
                    return records
                
                source_month = f'{year}-{month:02d}-01'
                
                # 解析所有页面的表格
                for page in pdf.pages:
                    tables = page.extract_tables()
                    if not tables:
                        # 尝试直接解析文本
                        text_records = self._parse_text_lines(page.extract_text() or '', source_month)
                        records.extend(text_records)
                    else:
                        for table in tables:
                            table_records = self._parse_table(table, source_month)
                            records.extend(table_records)
                
                # 如果表格解析失败，回退到文本行解析
                if not records:
                    full_text = ''
                    for page in pdf.pages:
                        full_text += (page.extract_text() or '') + '\n'
                    records = self._parse_text_lines(full_text, source_month)
                
        except Exception as e:
            self.logger.error(f'PDF解析异常: {e}')
            import traceback
            traceback.print_exc()
        
        return records
    
    def _parse_table(self, table, source_month):
        """解析表格数据"""
        records = []
        
        if not table or len(table) < 3:
            return records
        
        for row_idx, row in enumerate(table):
            # 清理单元格
            cells = [str(c).strip() if c else '' for c in row]
            
            # 过滤空行
            if not any(cells):
                continue
            
            # 过滤表头行
            row_text = ' '.join(cells).upper()
            if any(kw in row_text for kw in ['MERK', 'MODEL', 'TOTAAL', 'TOTAL', 'REGISTRATIES']):
                continue
            
            # 解析行数据
            record = self._parse_row(cells, source_month)
            if record:
                records.append(record)
        
        return records
    
    def _parse_text_lines(self, text, source_month):
        """从文本行解析数据（回退方案）"""
        records = []
        
        if not text:
            return records
        
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 跳过标题和空行
            if any(kw in line.upper() for kw in ['MERK', 'MODEL', 'TOTAAL', 'TOTAL', 'REGISTRATIES', 'AANTAL']):
                continue
            
            # 尝试解析行数据
            record = self._parse_line(line, source_month)
            if record:
                records.append(record)
        
        return records
    
    def _parse_row(self, cells, source_month):
        """解析单行表格数据"""
        # BOVAG PDF表格列数可能不稳定
        # 尝试找到品牌/车型列和数字列
        
        # 找到包含品牌名的列
        brand_model_col = None
        sales_cols = []
        
        for idx, cell in enumerate(cells):
            cell_upper = cell.upper().strip()
            
            # 检查是否包含品牌/车型名（以字母开头，不是纯数字）
            if cell_upper and not cell_upper.replace('.', '').replace(',', '').replace(' ', '').isdigit():
                if len(cell_upper) >= 3:
                    # 排除一些关键词
                    if cell_upper not in SKIP_KEYWORDS and not cell_upper.startswith('AANTAL'):
                        if brand_model_col is None:
                            brand_model_col = idx
                        elif cell_upper[0].isalpha() and len(cell_upper) > 5:
                            brand_model_col = idx
        
        # 找到数字列（销量数据）
        for idx, cell in enumerate(cells):
            if idx == brand_model_col:
                continue
            # 检查是否是数字格式（包含数字和千分位符号）
            cell_clean = cell.replace('.', '').replace(',', '').replace(' ', '')
            if cell_clean.isdigit() and len(cell_clean) >= 1:
                sales_cols.append(idx)
        
        if brand_model_col is None or not sales_cols:
            return None
        
        # 提取品牌/车型信息
        brand_model_text = cells[brand_model_col].strip()
        
        # 跳过空行和无效行
        if not brand_model_text or brand_model_text.upper() in SKIP_KEYWORDS:
            return None
        
        # 提取销量数据（第一列是本月销量）
        sales_col = sales_cols[0]
        sales_raw = cells[sales_col]
        sales_volume = _dutch_number_to_int(sales_raw)
        
        if sales_volume is None:
            return None
        
        # 判断是车型行还是品牌汇总行
        # 品牌汇总行：只有品牌名，没有车型名（如 "AUDI 1.255 ..." 但这里"AUDI"后面是数字）
        # 车型行：品牌名 + 车型名（如 "AUDI Q3 164 ..."）
        
        # 提取品牌和车型
        brand_name, model_name = self._extract_brand_model(brand_model_text)
        
        if not brand_name:
            return None
        
        # 构建记录
        record = {
            'country_code': self.country_code,
            'source_month': source_month,
            'brand_name_raw': brand_name,
            'brand_id': None,
            'model_name': model_name,  # None表示品牌级，有值表示车型级
            'vehicle_type': 'passenger_car',
            'energy_type': 'unknown',
            'segment': None,
            'raw_unit': 'unit',
            'sales_volume_raw': sales_volume,
            'sales_volume_normalized': sales_volume,
            'revision_no': 1,
            'is_latest': True,
            'pub_date': None,
            'crawl_time': datetime.now(),
            'data_source': self.source_name,
            'notes': f'BOVAG PDF解析 - {brand_model_text}'
        }
        
        return record
    
    def _parse_line(self, line, source_month):
        """从单行文本解析数据"""
        # 移除多余空格
        line = re.sub(r'\s+', ' ', line).strip()
        
        # 模式：品牌/车型 + 数字 + 数字 + 数字 + 数字
        # 如: "AUDI Q3 164 1.141 14 154"
        # 如: "AUDI 1.255 5.956 1.213 6.013" (品牌汇总行)
        
        # 尝试用正则匹配
        # 匹配: 文字部分 + 4个数字（用点号做千分位）
        pattern = r'^([A-Za-z][A-Za-z0-9\s\-\/\.]+?)\s+(\d[\d.]*)\s+(\d[\d.]*)\s+(\d[\d.]*)\s+(\d[\d.]*)$'
        match = re.match(pattern, line)
        
        if not match:
            return None
        
        brand_model_text = match.group(1).strip()
        
        # 跳过无效行
        if brand_model_text.upper() in SKIP_KEYWORDS:
            return None
        
        # 提取本月销量（第2组）
        sales_raw = match.group(2)
        sales_volume = _dutch_number_to_int(sales_raw)
        
        if sales_volume is None:
            return None
        
        # 提取品牌和车型
        brand_name, model_name = self._extract_brand_model(brand_model_text)
        
        if not brand_name:
            return None
        
        # 构建记录
        record = {
            'country_code': self.country_code,
            'source_month': source_month,
            'brand_name_raw': brand_name,
            'brand_id': None,
            'model_name': model_name,
            'vehicle_type': 'passenger_car',
            'energy_type': 'unknown',
            'segment': None,
            'raw_unit': 'unit',
            'sales_volume_raw': sales_volume,
            'sales_volume_normalized': sales_volume,
            'revision_no': 1,
            'is_latest': True,
            'pub_date': None,
            'crawl_time': datetime.now(),
            'data_source': self.source_name,
            'notes': f'BOVAG文本解析 - {brand_model_text}'
        }
        
        return record
    
    def _extract_brand_model(self, text):
        """从文本中提取品牌名和车型名
        
        规则:
        - 品牌汇总行: "AUDI" -> brand="AUDI", model=None
        - 车型行: "AUDI Q3" -> brand="AUDI", model="Q3"
        - 特殊: 需要处理多品牌名（如"ALFA ROMEO"）
        
        判断逻辑:
        - 如果文本仅包含已知品牌名（或品牌名变体），则为品牌汇总行
        - 如果文本包含品牌名 + 额外文字，则为车型行
        """
        text_upper = text.upper().strip()
        words = text_upper.split()
        
        if not words:
            return None, None
        
        # 尝试匹配完整品牌名（多词品牌）
        # 按品牌名长度从长到短排序
        brand_names = sorted(NL_BRAND_MAP.keys(), key=len, reverse=True)
        
        matched_brand = None
        remaining_text = text_upper
        
        # 尝试匹配多词品牌名
        for brand_name in brand_names:
            brand_upper = brand_name.upper()
            # 检查文本是否以品牌名开头
            if text_upper.startswith(brand_upper):
                # 提取剩余部分
                remaining = text_upper[len(brand_upper):].strip()
                # 排除品牌名是另一个品牌的子串的情况
                if not matched_brand or len(brand_upper) > len(matched_brand):
                    matched_brand = brand_upper
                    remaining_text = remaining
        
        # 如果没有匹配，尝试用第一个词作为品牌名
        if not matched_brand:
            first_word = words[0]
            # 检查是否是已知品牌名的一部分
            for brand_name in brand_names:
                if brand_name.upper() == first_word:
                    matched_brand = brand_name.upper()
                    remaining_text = ' '.join(words[1:])
                    break
            
            if not matched_brand:
                # 使用第一个词作为品牌名
                matched_brand = first_word
                remaining_text = ' '.join(words[1:]) if len(words) > 1 else ''
        
        # 标准化品牌名
        brand_clean = NL_BRAND_MAP.get(matched_brand, matched_brand)
        
        # 如果有剩余文本，作为车型名
        model_name = None
        if remaining_text and remaining_text not in ('', '-', '—'):
            model_name = remaining_text.strip()
            if not model_name or model_name == '-':
                model_name = None
        
        return brand_clean, model_name
    
    def crawl_incremental(self, max_pages=50, model_only=True):
        """增量爬取：只保存比库中 MAX(source_month) 更新的记录

        遍历 sitemap 新闻稿URL，提取PDF并解析，仅保留
        source_month > 库中 MAX 的记录入库（save_sales 幂等，历史记录自动跳过）。
        """
        self.logger.info('开始BOVAG荷兰增量爬取')
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='NL'")
        row = cur.fetchone()
        max_month = row['m'] if row else None
        self.logger.info(f'库中 NL MAX(source_month) = {max_month}')

        urls = self._get_sitemap_urls()
        if not urls:
            self.logger.error('未找到任何URL')
            return 0

        processed_pdfs = set()
        new_records = []
        for i, url in enumerate(urls[:max_pages]):
            self.logger.info(f'[{i+1}/{min(len(urls), max_pages)}] 处理: {url.split("/")[-1]}')
            pdf_url = self._extract_pdf_from_page(url)
            if not pdf_url or pdf_url in processed_pdfs:
                continue
            processed_pdfs.add(pdf_url)
            pdf_content = self.download_pdf(pdf_url)
            if not pdf_content:
                continue
            records = self.parse_pdf(pdf_content)
            if not records:
                continue
            if model_only:
                records = [r for r in records if r.get('model_name') is not None]
            for r in records:
                sm = r.get('source_month')
                if sm is None:
                    continue
                if isinstance(sm, str):
                    try:
                        sm = datetime.strptime(sm, '%Y-%m-%d').date()
                    except ValueError:
                        continue
                if max_month is None or sm > max_month:
                    new_records.append(r)
            time.sleep(random.uniform(1, 2))

        self.logger.info(f'增量: 共解析到 {len(new_records)} 条新记录 (MAX={max_month})')
        saved = 0
        for record in new_records:
            if self.save_sales(record):
                saved += 1
        self.logger.info(f'BOVAG增量保存成功 {saved}/{len(new_records)} 条')
        return saved

    def crawl_all(self, max_pages=50, model_only=True):
        """爬取所有可用的历史数据
        
        Args:
            max_pages: 最多处理的页面数
            model_only: 是否只保存车型级数据（过滤掉品牌级汇总行）
        """
        self.logger.info(f'开始爬取BOVAG荷兰汽车销量数据 (model_only={model_only})')
        
        # 1. 获取新闻稿URL列表
        urls = self._get_sitemap_urls()
        if not urls:
            self.logger.error('未找到任何URL')
            return False
        
        # 2. 遍历URL，提取PDF并下载解析
        processed_pdfs = set()
        all_records = []
        no_pdf_count = 0
        duplicate_count = 0
        download_fail_count = 0
        parse_empty_count = 0
        
        for i, url in enumerate(urls[:max_pages]):
            self.logger.info(f'[{i+1}/{min(len(urls), max_pages)}] 处理: {url.split("/")[-1]}')
            
            # 提取PDF链接
            pdf_url = self._extract_pdf_from_page(url)
            if not pdf_url:
                no_pdf_count += 1
                self.logger.info(f'  ⚠️  未找到PDF链接')
                continue
            
            if pdf_url in processed_pdfs:
                duplicate_count += 1
                self.logger.info(f'  ⏭️  跳过重复PDF: {pdf_url.split("/")[-1]}')
                continue
            
            processed_pdfs.add(pdf_url)
            
            # 下载PDF
            pdf_content = self.download_pdf(pdf_url)
            if not pdf_content:
                download_fail_count += 1
                self.logger.info(f'  ❌ PDF下载失败')
                continue
            
            # 解析PDF
            records = self.parse_pdf(pdf_content)
            if records:
                # 过滤品牌级数据（如果model_only=True）
                if model_only:
                    original_count = len(records)
                    records = [r for r in records if r.get('model_name') is not None]
                    self.logger.info(f'  ✅ 解析到 {original_count} 条记录 (过滤后 {len(records)} 条车型级)')
                else:
                    self.logger.info(f'  ✅ 解析到 {len(records)} 条记录')
                all_records.extend(records)
            else:
                parse_empty_count += 1
                self.logger.info(f'  ⚠️  PDF解析结果为空')
            
            # 礼貌性延迟
            time.sleep(random.uniform(1, 3))
        
        self.logger.info(f'=== 处理统计 ===')
        self.logger.info(f'处理页面数: {min(len(urls), max_pages)}')
        self.logger.info(f'找到PDF数: {len(processed_pdfs)}')
        self.logger.info(f'未找到PDF: {no_pdf_count}')
        self.logger.info(f'重复PDF跳过: {duplicate_count}')
        self.logger.info(f'下载失败: {download_fail_count}')
        self.logger.info(f'解析为空: {parse_empty_count}')
        self.logger.info(f'共解析到 {len(all_records)} 条记录')
        
        # 3. 保存数据
        saved = 0
        for record in all_records:
            if self.save_sales(record):
                saved += 1
        
        self.logger.info(f'保存成功 {saved}/{len(all_records)} 条')
        
        # 4. 记录运行日志
        self.log_crawl_run('success', saved if saved > 0 else 0)
        
        return True
    
    def crawl_single_pdf(self, pdf_url):
        """单独爬取一个PDF文件"""
        self.logger.info(f'爬取单个PDF: {pdf_url}')
        
        # 下载PDF
        pdf_content = self.download_pdf(pdf_url)
        if not pdf_content:
            return False
        
        # 解析PDF
        records = self.parse_pdf(pdf_content)
        self.logger.info(f'解析到 {len(records)} 条记录')
        
        # 保存数据
        saved = 0
        for record in records:
            if self.save_sales(record):
                saved += 1
        
        self.logger.info(f'保存成功 {saved}/{len(records)} 条')
        
        return True


def main():
    """主函数"""
    crawler = BovagCrawler()
    
    try:
        # 爬取所有数据
        crawler.crawl_all(max_pages=50)
        
    except Exception as e:
        crawler.logger.error(f'爬虫异常: {e}')
        crawler.log_crawl_run('error', error_msg=str(e))
        import traceback
        traceback.print_exc()
    finally:
        crawler.close()


if __name__ == '__main__':
    main()
