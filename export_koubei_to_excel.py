# -*- coding: utf-8 -*-
"""
从本地 PostgreSQL 数据库 koubei.data_koubei 导出数据到本地 Excel
"""

import os
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime


def main():
    OUTPUT_DIR = r"D:\数据\口碑"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    xlsx_path = os.path.join(OUTPUT_DIR, f"口碑数据_{timestamp}.xlsx")
    csv_path = os.path.join(OUTPUT_DIR, f"口碑数据_{timestamp}.csv")

    db_config = {
        'user': 'postgres',
        'password': '800124',
        'host': 'localhost',
        'port': 5432,
        'dbname': 'koubei',
    }

    print("=" * 60)
    print("  口碑数据导出工具（本地数据库）")
    print(f"  输出目录: {OUTPUT_DIR}")
    print("=" * 60)

    try:
        print("\n[1/4] 连接数据库...")
        conn_str = (
            f'postgresql+psycopg2://{db_config["user"]}:{db_config["password"]}'
            f'@{db_config["host"]}:{db_config["port"]}/{db_config["dbname"]}'
        )
        engine = create_engine(conn_str, client_encoding='utf8')

        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM data_koubei"))
            total = result.fetchone()[0]
            print(f"  data_koubei 表共 {total} 条记录")

        print("\n[2/4] 查询数据...")
        query = """
            SELECT
                chexi          AS 车型,
                chekuan        AS 车款,
                niankuan       AS 年款,
                fabiao_time    AS 发表时间,
                xingshi        AS 行驶里程,
                jiage          AS 购车价格,
                goumai_time    AS 购车时间,
                goumai_didian  AS 购车地点,
                chezhu_weizhi  AS 车主城市,
                pingfen        AS 评分,
                zhaiyao        AS 口碑摘要
            FROM data_koubei
            ORDER BY 车型, 发表时间 DESC
        """
        df = pd.read_sql(query, con=engine)

        if df.empty:
            print("  数据库中没有数据")
            return

        print(f"  查询到 {len(df)} 条数据，共 {len(df.columns)} 个字段")

        print(f"\n[3/4] 导出 Excel...")
        df.to_excel(xlsx_path, index=False, engine='openpyxl')
        file_size_mb = os.path.getsize(xlsx_path) / 1024 / 1024
        print(f"  OK {xlsx_path}")
        print(f"    大小: {file_size_mb:.2f} MB")

        print(f"\n[4/4] 导出 CSV（utf-8-sig 编码）...")
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        file_size_mb = os.path.getsize(csv_path) / 1024 / 1024
        print(f"  OK {csv_path}")
        print(f"    大小: {file_size_mb:.2f} MB")

        print("\n" + "=" * 60)
        print(f"  导出完成！")
        print(f"  数据条数: {len(df)} 条")
        print(f"  xlsx: {xlsx_path}")
        print(f"  csv:  {csv_path}")
        print("=" * 60)

    except Exception as e:
        print(f"\n导出失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
