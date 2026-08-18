# -*- coding: utf-8 -*-
"""
BaseCrawler 基类 - 独立模块
提供数据库连接、品牌匹配、爬取日志等通用功能
"""
import os
import sys
import json
import time
import random
import logging
import requests
import re
from datetime import datetime, date
import psycopg2
from psycopg2.extras import RealDictCursor

# ============================================
# 全局配置
# ============================================
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
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0'
]
MIN_DELAY = 3
MAX_DELAY = 8
BATCH_RESTART = 35
BATCH_SLEEP_MIN = 180
BATCH_SLEEP_MAX = 300
MAX_RETRIES = 3
BACKOFF_BASE = 1
MAX_FAILURES = 5


class BaseCrawler:
    def __init__(self, source_name, country_code=None):
        self.source_name = source_name
        self.country_code = country_code
        self.logger = self._setup_logger()
        self.conn = None
        self.cur = None
        self.failure_count = 0
        self.page_count = 0

    def _setup_logger(self):
        logger = logging.getLogger(f'crawler.{self.source_name}')
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            fh = logging.FileHandler(f'crawler_{self.source_name}.log', encoding='utf-8')
            fh.setLevel(logging.INFO)
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
            fh.setFormatter(formatter)
            ch.setFormatter(formatter)
            logger.addHandler(fh)
            logger.addHandler(ch)
        return logger

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

    def random_delay(self):
        delay = random.uniform(MIN_DELAY, MAX_DELAY)
        self.logger.info(f'随机延迟 {delay:.1f}s')
        time.sleep(delay)

    def batch_restart(self):
        if self.page_count > 0 and self.page_count % BATCH_RESTART == 0:
            sleep_time = random.uniform(BATCH_SLEEP_MIN, BATCH_SLEEP_MAX)
            self.logger.info(f'批次长休 {sleep_time:.0f}s（已爬 {self.page_count} 页）')
            time.sleep(sleep_time)

    def get_headers(self):
        return {
            'User-Agent': random.choice(UA_LIST),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }

    def is_duplicate(self, country_code, source_month, brand_name_raw, model_name=None, data_source=None):
        conn, cur = self.get_connection()
        query = """
            SELECT id FROM market_sales_monthly
            WHERE country_code = %s AND source_month = %s
              AND brand_name_raw = %s AND is_latest = TRUE
        """
        params = [country_code, source_month, brand_name_raw]
        if model_name:
            query += ' AND model_name = %s'
            params.append(model_name)
        else:
            query += ' AND model_name IS NULL'
        if data_source:
            query += ' AND data_source = %s'
            params.append(data_source)
        cur.execute(query, params)
        return cur.fetchone() is not None

    def save_sales(self, record):
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

    def save_to_pending(self, record, errors):
        conn, cur = self.get_connection()
        try:
            cur.execute("""
                INSERT INTO market_sales_pending
                    (country_code, source_month, brand_name_raw, model_name,
                     sales_volume_raw, raw_unit, data_source, validation_errors, crawl_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                record.get('country_code'),
                record.get('source_month'),
                record.get('brand_name_raw'),
                record.get('model_name'),
                record.get('sales_volume_raw'),
                record.get('raw_unit', 'unit'),
                record.get('data_source', self.source_name),
                json.dumps(errors, ensure_ascii=False),
                datetime.now()
            ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            self.logger.error(f'入暂存表失败: {e}')

    def retry_request(self, func, *args, **kwargs):
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                wait = BACKOFF_BASE * (2 ** attempt)
                self.logger.warning(f'请求失败（{attempt+1}/{MAX_RETRIES}）：{e}，{wait}s 后重试')
                time.sleep(wait)
        self.failure_count += 1
        if self.failure_count >= MAX_FAILURES:
            self.logger.error(f'连续失败 {self.failure_count} 次，熔断停止')
        return None

    def log_crawl_run(self, status, records_count=0, error_msg=None):
        conn, cur = self.get_connection()
        try:
            try:
                cur.execute("""
                    INSERT INTO crawl_run_log
                        (source_name, country_code, started_at, status, new_items, error_summary)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    self.source_name,
                    self.country_code,
                    datetime.now(),
                    status,
                    records_count,
                    error_msg
                ))
                conn.commit()
            except Exception:
                cur.execute("""
                    INSERT INTO crawl_run_log
                        (module, status, started_at)
                    VALUES (%s, %s, %s)
                """, (
                    f'{self.source_name}_crawler',
                    status,
                    datetime.now()
                ))
                conn.commit()
        except Exception as e:
            conn.rollback()
            self.logger.warning(f'记录运行日志失败（不影响主流程）: {e}')

    def _match_brand(self, brand_raw):
        """
        品牌匹配：先查品牌全名/中文名，再查变体表
        """
        conn, cur = self.get_connection()
        cur.execute("""
            SELECT id FROM brand_name_mapping
            WHERE canonical_name ILIKE %s OR brand_name_cn ILIKE %s
            LIMIT 1
        """, (brand_raw, brand_raw))
        row = cur.fetchone()
        if row:
            return row['id']

        cur.execute("""
            SELECT brand_id FROM brand_name_variant
            WHERE variant_name ILIKE %s
            LIMIT 1
        """, (brand_raw,))
        row = cur.fetchone()
        return row['brand_id'] if row else None
