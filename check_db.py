# -*- coding: utf-8 -*-
"""检查数据库中的口碑数据"""

from sqlalchemy import create_engine, text

db_config = {
    'user': 'postgres',
    'password': '800124',
    'host': 'localhost',
    'port': 5432,
    'dbname': 'koubei'
}

try:
    connection_string = f'postgresql+psycopg2://{db_config["user"]}:{db_config["password"]}@{db_config["host"]}:{db_config["port"]}/{db_config["dbname"]}'
    engine = create_engine(connection_string)

    with engine.connect() as conn:
        print("=" * 60)
        print("【数据库数据检查】")
        print("=" * 60)

        result = conn.execute(text("SELECT COUNT(*) FROM data_koubei"))
        total = result.fetchone()[0]
        print(f"\n总记录数: {total}")

        print("\n各车系列数据量:")
        result = conn.execute(text("SELECT chexi, COUNT(*) as cnt FROM data_koubei GROUP BY chexi ORDER BY cnt DESC"))
        for row in result:
            print(f"  {row.chexi:12s}: {row.cnt} 条")

        print("\n最近5天的数据分布:")
        result = conn.execute(text("""
            SELECT fabiao_time, COUNT(*) as cnt 
            FROM data_koubei 
            WHERE fabiao_time >= (CURRENT_DATE - INTERVAL '5 days')
            GROUP BY fabiao_time 
            ORDER BY fabiao_time DESC
        """))
        for row in result:
            print(f"  {row.fabiao_time:10s}: {row.cnt} 条")

except Exception as e:
    print(f"错误: {str(e)}")