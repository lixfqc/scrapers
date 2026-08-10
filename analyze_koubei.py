# -*- coding: utf-8 -*-
"""分析口碑数据的时间分布和统计信息"""

from sqlalchemy import create_engine, text
from datetime import datetime

db_config = {
    'user': 'postgres',
    'password': '800124',
    'host': 'localhost',
    'port': 5432,
    'dbname': 'koubei'
}

conn_str = f'postgresql+psycopg2://{db_config["user"]}:{db_config["password"]}@{db_config["host"]}:{db_config["port"]}/{db_config["dbname"]}'
engine = create_engine(conn_str)

with engine.connect() as conn:
    print("=" * 60)
    print("【口碑数据分析】")
    print("=" * 60)

    result = conn.execute(text("SELECT COUNT(*) FROM data_koubei"))
    total = result.fetchone()[0]
    print(f"\n总记录数: {total}")

    result = conn.execute(text("SELECT COUNT(DISTINCT chexi) FROM data_koubei"))
    chexi_count = result.fetchone()[0]
    print(f"涉及车系数: {chexi_count}")

    print("\n各车系列数据量（TOP 10）:")
    result = conn.execute(text("SELECT chexi, COUNT(*) as cnt FROM data_koubei GROUP BY chexi ORDER BY cnt DESC LIMIT 10"))
    for row in result:
        print(f"  {row.chexi:12s}: {row.cnt} 条")

    print("\n最近14天的数据分布:")
    result = conn.execute(text("""
        SELECT fabiao_time, COUNT(*) as cnt 
        FROM data_koubei 
        WHERE fabiao_time >= (CURRENT_DATE - INTERVAL '14 days')
        GROUP BY fabiao_time 
        ORDER BY fabiao_time DESC
    """))
    for row in result:
        print(f"  {row.fabiao_time:10s}: {row.cnt} 条")

    print("\n爬取时间分布（最近7天）:")
    result = conn.execute(text("""
        SELECT DATE(paqu_time) as crawl_date, COUNT(*) as cnt
        FROM data_koubei 
        WHERE paqu_time >= (CURRENT_DATE - INTERVAL '7 days')
        GROUP BY DATE(paqu_time)
        ORDER BY crawl_date DESC
    """))
    for row in result:
        print(f"  {str(row.crawl_date):10s}: {row.cnt} 条")

    print("\n评分分布:")
    result = conn.execute(text("SELECT pingfen, COUNT(*) as cnt FROM data_koubei WHERE pingfen IS NOT NULL GROUP BY pingfen ORDER BY pingfen DESC"))
    for row in result:
        print(f"  评分 {row.pingfen}: {row.cnt} 条")

print("\n" + "=" * 60)