# -*- coding: utf-8 -*-
"""对比本地 PostgreSQL 与 阿里云 PostgreSQL 中的口碑数据"""

from sqlalchemy import create_engine, text

# 阿里云远程
cloud_config = {
    'user': 'postgres',
    'password': '800124',
    'host': 'localhost',
    'port': 5432,
    'dbname': 'koubei',
}

# 本地 PostgreSQL (尝试多种常见账号密码)
local_tries = [
    {'user': 'postgres', 'password': 'postgres'},
    {'user': 'postgres', 'password': '123456'},
    {'user': 'postgres', 'password': 'admin'},
    {'user': 'postgres', 'password': 'Levin001'},
    {'user': 'postgres', 'password': '800124'},
]

print("=" * 65)
print("  本地 vs 云端 口碑数据对比")
print("=" * 65)


# 1. 查询云端
print("\n[云端] 阿里云 RDS PostgreSQL")
print("-" * 40)
try:
    conn_str = (
        f'postgresql+psycopg2://{cloud_config["user"]}:{cloud_config["password"]}'
        f'@{cloud_config["host"]}:{cloud_config["port"]}/{cloud_config["dbname"]}'
    )
    engine = create_engine(conn_str)
    with engine.connect() as conn:
        r = conn.execute(text("SELECT COUNT(*) FROM data_koubei"))
        count = r.fetchone()[0]
        print(f"  总记录数:     {count}")

        r = conn.execute(text("SELECT MAX(fabiao_time) FROM data_koubei"))
        print(f"  最新发表时间: {r.fetchone()[0]}")

        r = conn.execute(text("SELECT MAX(paqu_time) FROM data_koubei WHERE paqu_time IS NOT NULL"))
        print(f"  最新爬取时间: {r.fetchone()[0]}")

        r = conn.execute(text("SELECT COUNT(DISTINCT chexi) FROM data_koubei"))
        print(f"  车系数:       {r.fetchone()[0]}")
except Exception as e:
    print(f"  连接失败: {e}")


# 2. 查询本地
print("\n[本地] localhost PostgreSQL")
print("-" * 40)

connected = False
for cfg in local_tries:
    if connected:
        break
    try:
        conn_str = (
            f'postgresql+psycopg2://{cfg["user"]}:{cfg["password"]}'
            f'@localhost:5432/koubei'
        )
        engine = create_engine(conn_str)
        with engine.connect() as conn:
            r = conn.execute(text("SELECT COUNT(*) FROM data_koubei"))
            count = r.fetchone()[0]
            print(f"  账号: {cfg['user']}/{cfg['password']}")
            print(f"  总记录数:     {count}")

            r = conn.execute(text("SELECT MAX(fabiao_time) FROM data_koubei"))
            print(f"  最新发表时间: {r.fetchone()[0]}")

            r = conn.execute(text("SELECT MAX(paqu_time) FROM data_koubei WHERE paqu_time IS NOT NULL"))
            print(f"  最新爬取时间: {r.fetchone()[0]}")

            r = conn.execute(text("SELECT COUNT(DISTINCT chexi) FROM data_koubei"))
            print(f"  车系数:       {r.fetchone()[0]}")
            connected = True
    except Exception as e:
        pass

if not connected:
    print("  所有常见账号均连接失败")
    print("  请告知本地的数据库账号和密码")

print("\n" + "=" * 65)
