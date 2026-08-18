# -*- coding: utf-8 -*-
"""英国ONS能源类型数据爬虫
解析ONS发布的UK New Vehicle Registrations Excel，提取能源类型数据
数据源: https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/uknewvehicleregistrationsandproduction
"""
import sys
sys.path.insert(0, '.')
import requests
import openpyxl
import io
import logging
from datetime import datetime, date
from kba_crawler import DB_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)

# ONS数据URL（2026年版本，包含最新数据）
ONS_URL_2026 = 'https://www.ons.gov.uk/file?uri=/economy/economicoutputandproductivity/output/datasets/uknewvehicleregistrationsandproduction/2026/smmtvehicleregandproddataset060826.xlsx'
ONS_URL_2025 = 'https://www.ons.gov.uk/file?uri=/economy/economicoutputandproductivity/output/datasets/uknewvehicleregistrationsandproduction/2025/smmtvehicleregandproddataset111225.xlsx'

# 能源类型映射（ONS列名 -> 标准化能源类型）
ENERGY_TYPE_MAP = {
    'Petrol': 'GASOLINE',
    'Diesel': 'DIESEL',
    'BEV': 'BEV',
    'PHEV': 'PHEV',
    'HEV': 'HEV',
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def download_ons_excel():
    """下载ONS最新Excel文件"""
    logging.info('下载ONS车辆注册数据Excel...')
    
    # 先尝试2026版本
    for url in [ONS_URL_2026, ONS_URL_2025]:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                logging.info(f'下载成功: {len(resp.content)} bytes')
                return resp.content
        except Exception as e:
            logging.warning(f'下载失败 {url}: {e}')
    
    raise Exception('无法下载ONS Excel文件')


def parse_energy_data(excel_content, start_year=2024):
    """解析能源类型数据
    
    返回: [(year, month, energy_type, sales), ...]
    """
    wb = openpyxl.load_workbook(io.BytesIO(excel_content))
    ws = wb['2.CarRegsByFuelType']
    
    records = []
    
    # 数据从第7行开始（前6行是表头和元数据）
    for row in ws.iter_rows(min_row=7, values_only=True):
        if not row or row[0] is None:
            continue
        
        # 解析日期
        date_val = row[0]
        if isinstance(date_val, datetime):
            year = date_val.year
            month = date_val.month
        elif isinstance(date_val, date):
            year = date_val.year
            month = date_val.month
        else:
            # 尝试解析字符串
            continue
        
        # 只处理指定年份及之后的数据
        if year < start_year:
            continue
        
        # 解析能源类型数据（NSA = 非季节调整）
        # 列结构（从索引0开始）:
        # 0: Month
        # 1: Total cars, NSA
        # 2: Petrol cars, NSA
        # 3: Diesel cars, NSA
        # 4: BEV cars, NSA
        # 5: PHEV cars, NSA
        # 6: HEV cars, NSA
        
        # 总销量（所有能源类型之和）
        total_sales = row[1]
        
        # 各能源类型销量
        energy_sales = {
            'GASOLINE': row[2],  # Petrol
            'DIESEL': row[3],    # Diesel
            'BEV': row[4],       # BEV
            'PHEV': row[5],      # PHEV
            'HEV': row[6],       # HEV
        }
        
        # 验证数据有效性
        if total_sales is None or total_sales == '[x]':
            continue
        
        # 转换数值
        try:
            total_sales = int(total_sales)
        except (ValueError, TypeError):
            continue
        
        # 添加总销量记录（能源类型为ALL或留空表示总销量）
        records.append({
            'year': year,
            'month': month,
            'energy_type': 'TOTAL',
            'sales': total_sales,
        })
        
        # 添加各能源类型记录
        for energy_type, sales_val in energy_sales.items():
            if sales_val is None or sales_val == '[x]':
                continue
            try:
                sales = int(sales_val)
                records.append({
                    'year': year,
                    'month': month,
                    'energy_type': energy_type,
                    'sales': sales,
                })
            except (ValueError, TypeError):
                continue
    
    logging.info(f'解析到 {len(records)} 条能源类型记录')
    return records


def save_to_database(records):
    """保存数据到数据库"""
    if not records:
        logging.warning('无数据可保存')
        return 0
    
    import psycopg2
    
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    now = datetime.now()
    
    total_saved = 0
    total_updated = 0
    
    for record in records:
        source_month = date(record['year'], record['month'], 1)
        
        # 检查是否已存在
        cur.execute("""
            SELECT id FROM market_sales_monthly
            WHERE country_code = 'GB'
              AND source_month = %s
              AND brand_name_raw = 'ALL'
              AND vehicle_type = 'passenger'
              AND energy_type = %s
              AND revision_no = 1
            LIMIT 1
        """, (source_month, record['energy_type']))
        row = cur.fetchone()
        
        if row:
            # 更新
            cur.execute("""
                UPDATE market_sales_monthly SET
                    sales_volume_raw = %s,
                    sales_volume_normalized = %s,
                    crawl_time = %s,
                    notes = %s
                WHERE id = %s
            """, (record['sales'], record['sales'], now, 'ONS能源类型数据', row['id']))
            total_updated += 1
        else:
            # 插入
            cur.execute("""
                INSERT INTO market_sales_monthly
                    (country_code, source_month, brand_name_raw, vehicle_type, 
                     energy_type, raw_unit, sales_volume_raw, sales_volume_normalized,
                     revision_no, is_latest, pub_date, crawl_time, data_source, notes)
                VALUES
                    ('GB', %s, 'ALL', 'passenger', %s, 'units', %s, %s,
                     1, true, %s, %s, 'ons', 'ONS能源类型数据')
            """, (source_month, record['energy_type'], record['sales'], record['sales'], now, now))
            total_saved += 1
    
    conn.commit()
    cur.close()
    conn.close()
    
    logging.info(f'保存 {total_saved} 条新记录，更新 {total_updated} 条记录')
    return total_saved + total_updated


def main():
    """主函数：爬取英国能源类型数据"""
    logging.info('=== 开始爬取英国ONS能源类型数据 ===')
    
    # 1. 下载Excel
    excel_content = download_ons_excel()
    
    # 2. 解析数据（从2024年开始）
    records = parse_energy_data(excel_content, start_year=2024)
    
    if not records:
        logging.warning('未解析到有效数据')
        return
    
    # 3. 显示数据预览
    logging.info('\n数据预览（前10条）:')
    for record in records[:10]:
        logging.info(f"  {record['year']}-{record['month']:02d} {record['energy_type']}: {record['sales']:,}")
    
    # 4. 保存到数据库
    saved = save_to_database(records)
    
    logging.info(f'\n完成：共保存 {saved} 条能源类型数据记录')


if __name__ == '__main__':
    main()
