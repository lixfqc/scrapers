# -*- coding: utf-8 -*-
"""
Statistik Austria 奥地利汽车月度新注册爬虫
数据源: https://data.statistik.gv.at/ (OGD开放数据, CC BY 4.0)
数据类型: 品牌级乘用车月度新注册 (Neuzulassungen)
数据范围: 2000-01 ~ 当前月, 全量CSV
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import io
import re
import logging
import requests
import psycopg2
from datetime import datetime, date
from psycopg2.extras import RealDictCursor
from base_crawler import BaseCrawler, DB_CONFIG

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

# OGD 数据集
OGD_BASE = 'https://data.statistik.gv.at/data'
DATASET_ID = 'OGD_fkfzul0759_OD_PkwNZL_1'
MAIN_CSV = f'{OGD_BASE}/{DATASET_ID}.csv'
BRAND_CODE_CSV = f'{OGD_BASE}/{DATASET_ID}_C-J59-0.csv'
MONTH_CODE_CSV = f'{OGD_BASE}/{DATASET_ID}_C-A10-0.csv'

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# 特殊品牌名替换映射
ALT_BRAND_MAP = {
    'VW': 'VOLKSWAGEN',
    'MERCEDES': 'MERCEDES-BENZ',
    'HONG QI': 'HONGQI',
    'CHERRY': 'CHERY',
    'GREAT WALL MOTOR': 'GREAT WALL',
    'SSANG-YONG': 'SSANGYONG',
    'CHEVROLET / DAEWOO': 'CHEVROLET',
    'AUTO DACIA': 'DACIA',
    'DAIMLER': 'MERCEDES-BENZ',
}

# 聚合行（无品牌概念，保持 NULL brand_id）
AGG_BRANDS = {'ANDERE MARKEN', 'NICHT KLASSIFIZIERBAR'}


class AustriaCrawler(BaseCrawler):
    """Statistik Austria 奥地利乘用车新注册爬虫"""

    def __init__(self):
        super().__init__(source_name='statistik_austria', country_code='AT')
        self.session = requests.Session()
        self.headers = {'User-Agent': UA}
        self.brand_code_map = {}  # J59-xxx -> name
        self._brand_id_cache = {}

    # ---------- 数据获取 ----------
    def download_csv(self, url):
        resp = self.session.get(url, headers=self.headers, timeout=60)
        if resp.status_code != 200:
            self.logger.error(f'下载失败: {url} HTTP {resp.status_code}')
            return None
        return resp.text

    def load_brand_codes(self):
        """加载品牌码表: J59-xxx -> 'AUDI (D) <040540>'"""
        text = self.download_csv(BRAND_CODE_CSV)
        if not text:
            return
        for ln in text.splitlines()[1:]:
            parts = ln.rstrip('\n').split(';')
            if len(parts) >= 2 and parts[0] and parts[1]:
                self.brand_code_map[parts[0]] = parts[1]
        self.logger.info(f'品牌码表加载: {len(self.brand_code_map)} 个')

    # ---------- 品牌名处理 ----------
    def clean_brand_raw(self, raw):
        """brand_name_raw: 去 <内部码>, 保留国家码 -> 'OPEL (D)'"""
        raw = raw.strip()
        m = re.search(r'(.+?)\s*<\S*>', raw)
        if m:
            raw = m.group(1).strip()
        return raw

    def core_brand(self, raw):
        """匹配用核心名: 再去尾部国家码括号 -> 'OPEL'"""
        raw = raw.strip()
        m = re.search(r'(.+?)\s*<\S*>', raw)
        if m:
            raw = m.group(1).strip()
        raw = re.sub(r'\s*\([^)]*\)\s*$', '', raw).strip()
        return raw

    def get_brand_id(self, brand_raw):
        """匹配 brand_id（不限制 status，兼容 discontinued）"""
        key = brand_raw
        if key in self._brand_id_cache:
            return self._brand_id_cache[key]

        core = self.core_brand(brand_raw)
        core_up = core.upper()

        if core_up in AGG_BRANDS:
            self._brand_id_cache[key] = None
            return None

        # 特殊替换
        lookup = ALT_BRAND_MAP.get(core_up, core_up)

        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT id FROM brand_name_mapping
                WHERE UPPER(canonical_name) = %s OR UPPER(brand_name_cn) = %s
                LIMIT 1
            """, (lookup, lookup))
            row = cur.fetchone()
            if row:
                self._brand_id_cache[key] = row['id']
                cur.close(); conn.close()
                return row['id']
            # variant 回退
            cur.execute("""
                SELECT bv.brand_id FROM brand_name_variant bv
                WHERE UPPER(bv.variant_name) = %s
                LIMIT 1
            """, (lookup,))
            row = cur.fetchone()
            cur.close(); conn.close()
            if row:
                self._brand_id_cache[key] = row['brand_id']
                return row['brand_id']
        except Exception as e:
            self.logger.error(f'brand_id 查询失败: {e}')
        self._brand_id_cache[key] = None
        return None

    # ---------- 解析 ----------
    def parse_main_csv(self, text):
        """解析主CSV长表 -> records"""
        records = []
        total = 0
        unmatched = set()
        for ln in text.splitlines()[1:]:
            parts = ln.rstrip('\n').split(';')
            if len(parts) < 4:
                continue
            brand_code, month_code, veh_code, value = parts[0], parts[1], parts[2], parts[3]
            if veh_code != 'EK7-1':  # 仅乘用车
                continue
            if not month_code.startswith('A10-'):
                continue
            try:
                y, m = int(month_code[4:8]), int(month_code[8:10])
                sales = int(value)
            except (ValueError, TypeError):
                continue

            raw_name = self.brand_code_map.get(brand_code, brand_code)
            brand_raw = self.clean_brand_raw(raw_name)
            brand_id = self.get_brand_id(raw_name)
            if brand_id is None and raw_name not in self.brand_code_map:
                pass
            if brand_id is None and self.core_brand(raw_name).upper() not in AGG_BRANDS:
                unmatched.add(f'{brand_code}:{raw_name}')

            records.append({
                'country_code': 'AT',
                'source_month': date(y, m, 1),
                'brand_name_raw': brand_raw,
                'brand_id': brand_id,
                'model_name': None,
                'vehicle_type': 'passenger_car',
                'energy_type': None,
                'segment': None,
                'raw_unit': 'units',
                'sales_volume_raw': sales,
                'sales_volume_normalized': sales,
                'revision_no': 1,
                'is_latest': True,
                'pub_date': None,
                'crawl_time': datetime.now(),
                'data_source': 'statistik_austria',
                'notes': 'Statistik Austria OGD Pkw Neuzulassungen',
            })
            total += sales

        self.logger.info(f'解析 {len(records)} 条, 总销量 {total}')
        if unmatched:
            self.logger.warning(f'未匹配品牌({len(unmatched)}): {sorted(unmatched)[:30]}')
        return records

    # ---------- 主流程 ----------
    def crawl_full(self):
        self.load_brand_codes()
        text = self.download_csv(MAIN_CSV)
        if not text:
            return 0
        records = self.parse_main_csv(text)
        saved = 0
        for rec in records:
            if self.save_sales(rec):
                saved += 1
        self.logger.info(f'奥地利全量入库完成: {saved}/{len(records)}')
        return saved

    def crawl_incremental(self):
        """增量更新：解析全量CSV，但只插入比库中已有 MAX(source_month) 更新的月份"""
        self.load_brand_codes()
        text = self.download_csv(MAIN_CSV)
        if not text:
            return 0
        records = self.parse_main_csv(text)
        if not records:
            return 0
        conn, cur = self.get_connection()
        cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code='AT'")
        row = cur.fetchone()
        max_month = row['m'] if row else None
        new_records = [r for r in records if max_month is None or r['source_month'] > max_month]
        self.logger.info(f'AT 增量: 库中已有最大月 {max_month}, 待插入 {len(new_records)}/{len(records)} 条')
        saved = 0
        for rec in new_records:
            if self.save_sales(rec):
                saved += 1
        self.logger.info(f'奥地利增量入库完成: {saved}/{len(new_records)}')
        return saved

    def save_sales(self, record):
        return super().save_sales(record)


def main():
    crawler = AustriaCrawler()
    n = crawler.crawl_full()
    print(f'\n=== 奥地利入库完成: {n} 条 ===')


if __name__ == '__main__':
    main()
