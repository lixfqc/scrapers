# -*- coding: utf-8 -*-
"""
补充比利时Febiac爬虫未匹配的品牌映射
"""
import sys
sys.path.insert(0, '.')
import psycopg2
from psycopg2.extras import RealDictCursor

DB_CONFIG = {
    'host': 'pgm-bp1sf8zujdx18698io.pg.rds.aliyuncs.com',
    'port': 5432,
    'user': 'Levin001',
    'password': 'Li800124',
    'dbname': 'guobiezhinan'
}

# 需要补充的品牌映射 (canonical_name, brand_name_cn)
NEW_BRANDS = [
    ('TRIPOD', '探路者'),
    ('ALLIED VEHICLES LTD', '联盟车辆'),
    ('TREMONIA', '特雷莫尼亚'),
    ('ALPINA', '阿尔宾娜'),
    ('RUF', '鲁夫'),
    ('API', 'API'),
    ('DREAMER', '梦想家'),
    ('AMF', 'AMF'),
    ('B-STYLE&FLEX-I-TRANS', 'B风格'),
    ('MOKE', 'MOKE'),
    ('KOENIGSEGG', '柯尼塞格'),
]

def main():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    inserted = 0
    skipped = 0
    
    for canonical_name, brand_name_cn in NEW_BRANDS:
        # 检查是否已存在
        cur.execute("""
            SELECT id FROM brand_name_mapping
            WHERE LOWER(canonical_name) = LOWER(%s)
            LIMIT 1
        """, (canonical_name,))
        existing = cur.fetchone()
        
        if existing:
            print(f"跳过已存在: {canonical_name} (ID: {existing['id']})")
            skipped += 1
        else:
            # 插入新品牌
            cur.execute("""
                INSERT INTO brand_name_mapping 
                    (canonical_name, brand_name_cn, country_of_origin, 
                     is_chinese_brand, vehicle_type, status, created_at)
                VALUES 
                    (%s, %s, 'BE', false, 'passenger', 'active', NOW())
                RETURNING id
            """, (canonical_name, brand_name_cn))
            new_id = cur.fetchone()['id']
            print(f"新增: {canonical_name} (ID: {new_id})")
            inserted += 1
    
    conn.commit()
    print(f"\n完成！新增 {inserted} 个品牌，跳过 {skipped} 个已存在品牌")
    
    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
