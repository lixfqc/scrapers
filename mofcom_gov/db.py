# -*- coding: utf-8 -*-
"""
数据库操作：policy_doc / tariff_rate / tax_rule / crawl_task_log
所有落库幂等：URL/UNIQUE 冲突时视为已存在（去重跳过）
"""
import hashlib
from datetime import datetime

import psycopg2

from config import DB_CONFIG


def connect():
    return psycopg2.connect(**DB_CONFIG)


def checksum(text):
    return hashlib.md5((text or '').encode('utf-8')).hexdigest()


class Db:
    def __init__(self, conn=None):
        self.conn = conn or connect()
        self.conn.autocommit = False
        self.cur = self.conn.cursor()

    def close(self):
        self.cur.close()
        self.conn.close()

    # ---------- policy_doc ----------
    def upsert_policy_doc(self, country_id, title, url, source, content_text,
                          doc_date=None, doc_type='经商处动态', confidence='P0', status='现行'):
        """
        幂等落 policy_doc
        返回 (doc_id, is_new)；url 已存在 -> is_new=False（去重跳过）
        """
        self.cur.execute(
            'SELECT doc_id FROM policy_doc WHERE url = %s', (url,))
        row = self.cur.fetchone()
        if row:
            self.cur.execute(
                'UPDATE policy_doc SET last_crawled = now() WHERE doc_id = %s',
                (row[0],))
            self.conn.commit()
            return row[0], False
        self.cur.execute("""
            INSERT INTO policy_doc
                (country_id, doc_type, title, url, source, lang, content_text,
                 doc_date, first_crawled, last_crawled, status, confidence)
            VALUES (%s, %s, %s, %s, %s, 'zh', %s, %s, now(), now(), %s, %s)
            RETURNING doc_id
        """, (country_id, doc_type, title, url, source, content_text,
              doc_date, status, confidence))
        doc_id = self.cur.fetchone()[0]
        self.conn.commit()
        return doc_id, True

    # ---------- tariff_rate ----------
    def upsert_tariff_rate(self, country_id, hs_code, goods_scope, tariff_type,
                           rate_pct, duty_base, currency, effective_date,
                           source, url, confidence='P1'):
        """
        幂等落 tariff_rate（UNIQUE(country_id, hs_code, goods_scope, tariff_type, effective_date)）
        返回 (tariff_id, is_new)
        """
        self.cur.execute("""
            SELECT tariff_id FROM tariff_rate
            WHERE country_id = %s AND hs_code = %s AND goods_scope = %s
              AND tariff_type = %s AND effective_date = %s
        """, (country_id, hs_code, goods_scope, tariff_type, effective_date))
        row = self.cur.fetchone()
        if row:
            self.cur.execute("""
                UPDATE tariff_rate SET rate_pct = %s, rate_specific = %s, duty_base = %s,
                    currency = %s, goods_scope = %s, source = %s, url = %s,
                    confidence = %s, info_date = now()
                WHERE tariff_id = %s
            """, (rate_pct, None, duty_base, currency, goods_scope, source,
                  url, confidence, row[0]))
            self.conn.commit()
            return row[0], False
        self.cur.execute("""
            INSERT INTO tariff_rate
                (country_id, hs_code, goods_scope, tariff_type, rate_pct, rate_specific,
                 duty_base, currency, effective_date, info_date, source, confidence, url)
            VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s, now(), %s, %s, %s)
            RETURNING tariff_id
        """, (country_id, hs_code, goods_scope, tariff_type, rate_pct,
              duty_base, currency, effective_date, source, confidence, url))
        tariff_id = self.cur.fetchone()[0]
        self.conn.commit()
        return tariff_id, True

    # ---------- tax_rule（二手车专属附加税费：超龄罚款/排量额外/右舵惩罚） ----------
    def upsert_tax_rule(self, country_id, tax_type, rate=None, basis=None,
                        amount=None, unit=None, effective_date=None,
                        source_doc_id=None, confidence='P1'):
        """
        幂等落 tax_rule（实际表无 UNIQUE/hs_code/url/source，
        以 country_id+tax_type+effective_date 为键查重，命中则 UPDATE 覆盖为新口径）
        返回 (tax_id, is_new)
        """
        self.cur.execute("""
            SELECT tax_id, basis FROM tax_rule
            WHERE country_id = %s AND tax_type = %s
              AND effective_date IS NOT DISTINCT FROM %s
              AND rate IS NOT DISTINCT FROM %s
            ORDER BY tax_id
        """, (country_id, tax_type, effective_date, rate))
        rows = self.cur.fetchall()
        if rows:
            # 同 key（country+tax_type+effective_date+rate）已有：口径更新则 UPDATE
            tid, cur_basis = rows[0]
            if cur_basis != basis or confidence != 'P1':
                self.cur.execute("""
                    UPDATE tax_rule SET basis = %s, confidence = %s,
                        amount = %s, unit = %s, is_current = true
                    WHERE tax_id = %s
                """, (basis, confidence, amount, unit, tid))
            self.conn.commit()
            return tid, False
        self.cur.execute("""
            INSERT INTO tax_rule
                (country_id, tax_type, rate, basis, amount, unit,
                 effective_date, source_doc_id, confidence, is_current)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true)
            RETURNING tax_id
        """, (country_id, tax_type, rate, basis, amount, unit,
              effective_date, source_doc_id, confidence))
        tax_id = self.cur.fetchone()[0]
        self.conn.commit()
        return tax_id, True

    # ---------- crawl_task_log ----------
    def log_crawl(self, country_id, source_site, source_level, crawl_strategy,
                  target_url, target_type, status, http_code=None,
                  result_doc_id=None, content_checksum=None,
                  duration_ms=None, delay_ms=None, retry_count=0, error_msg=None):
        """记 crawl_task_log 一条；UNIQUE(target_url, crawl_time) 冲突时忽略"""
        try:
            self.cur.execute("""
                INSERT INTO crawl_task_log
                    (country_id, source_site, source_level, crawl_strategy,
                     target_url, target_type, status, http_code, result_doc_id,
                     checksum, duration_ms, delay_ms, retry_count, error_msg)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (target_url, crawl_time) DO NOTHING
            """, (country_id, source_site, source_level, crawl_strategy,
                  target_url, target_type, status, http_code, result_doc_id,
                  content_checksum, duration_ms, delay_ms, retry_count, error_msg))
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            print(f'[crawl_task_log 写入失败] {e}')

    # ---------- 查询 ----------
    def get_seed_doc(self, country_id):
        """查该国的种子 policy_doc（url LIKE 'seed-%'）doc_id，无则 None"""
        self.cur.execute(
            "SELECT doc_id FROM policy_doc WHERE country_id = %s AND url LIKE 'seed-%%' "
            "ORDER BY doc_id LIMIT 1", (country_id,))
        row = self.cur.fetchone()
        return row[0] if row else None

    def get_country(self, iso_alpha3=None, country_name=None):
        """按 iso_alpha3 或中文名查 dim_country，返回 dict 或 None"""
        sql = 'SELECT country_id, country_name, iso_alpha2, iso_alpha3 FROM dim_country WHERE '
        if iso_alpha3:
            sql += 'iso_alpha3 = %s'
            args = (iso_alpha3,)
        else:
            sql += 'country_name = %s'
            args = (country_name,)
        self.cur.execute(sql, args)
        row = self.cur.fetchone()
        if not row:
            return None
        return {'country_id': row[0], 'country_name': row[1],
                'iso_alpha2': row[2], 'iso_alpha3': row[3]}

    def count(self, table):
        self.cur.execute(f'SELECT count(*) FROM {table}')
        return self.cur.fetchone()[0]

    def count_by(self, table, field):
        """GROUP BY 分布统计，返回 [(key, cnt)]"""
        self.cur.execute(f'SELECT {field}, count(*) FROM {table} GROUP BY {field} ORDER BY 2 DESC')
        return self.cur.fetchall()