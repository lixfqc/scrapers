"""
全能云端数据库查询工具 — 阿里云 RDS PostgreSQL 多库查询

直接用法:
  python cloud_db.py "SELECT * FROM v_data_peizhibiao LIMIT 5"
  python cloud_db.py --db=gonggao "SELECT * FROM ..."
  python cloud_db.py --db=guobiezhinan "SELECT ..."
  python cloud_db.py --list-dbs          # 列出所有可用数据库

快捷命令:
  python cloud_db.py --tables             # 当前库的所有表
  python cloud_db.py --stats              # 当前库统计信息
  python cloud_db.py --help               # 帮助

可用数据库: peizhibiao, baoxian, chukou, gonggao, guobiezhinan, voc, julei

记忆提示（给 AI 用）：
  当用户说"查云端数据"、"从阿里云查"、"连云端查"等关键词时，
  调用本脚本连接阿里云 RDS。默认连 peizhibiao 库，用 --db=xxx 切换数据库。
  云数据库地址: pgm-bp1sf8zujdx18698io.pg.rds.aliyuncs.com
"""

import sys
import json
import psycopg2

# ── 所有可用数据库 ──
AVAILABLE_DBS = {
    'peizhibiao':   '配置表（汽车之家车型配置）',
    'baoxian':      '保险',
    'chukou':       '出口',
    'gonggao':      '公告',
    'guobiezhinan': '国别指南',
    'voc':          '语义',
    'julei':        '聚类',
}

HOST = 'pgm-bp1sf8zujdx18698io.pg.rds.aliyuncs.com'
PORT = 5432
USER = 'Levin001'
PASS = 'Li800124'


def get_conn(dbname='peizhibiao'):
    return psycopg2.connect(host=HOST, port=PORT, user=USER, password=PASS, dbname=dbname)


def query(sql, dbname='peizhibiao', fmt='table'):
    conn = get_conn(dbname)
    cur = conn.cursor()
    try:
        cur.execute(sql)
        if cur.description:
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            tag = f'[{dbname}] '
            if fmt == 'json':
                print(json.dumps([dict(zip(cols, r)) for r in rows], ensure_ascii=False, default=str))
            else:
                col_widths = [len(c) for c in cols]
                for r in rows[:100]:
                    for i, v in enumerate(r):
                        col_widths[i] = max(col_widths[i], len(str(v)) if v else 4)
                header = tag + ' | '.join(c.ljust(col_widths[i]) for i, c in enumerate(cols))
                sep = tag + '-+-'.join('-' * w for w in col_widths)
                print(header)
                print(sep)
                for r in rows:
                    line = tag + ' | '.join((str(v) if v else '').ljust(col_widths[i]) for i, v in enumerate(r))
                    print(line)
                print(f'\n{tag}共 {len(rows)} 行')
        else:
            # 非查询语句（INSERT/UPDATE/DELETE/DDL 等）：提交事务，避免连接关闭时回滚丢失
            conn.commit()
            print(f'受影响行数: {cur.rowcount}')
            # 判断是否为 DDL（CREATE/ALTER/DROP 等），DDL 无行数概念，提示已提交
            head = sql.lstrip().split()[0].upper() if sql.strip() else ''
            if head in ('CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'GRANT', 'REVOKE'):
                print(f'✅ {head} 已执行并提交')
            else:
                print(f'✅ 已提交 {cur.rowcount} 行变更')
    except Exception as e:
        print(f'SQL 执行失败: {e}')
        print(f'SQL: {sql[:500]}')
    finally:
        cur.close()
        conn.close()


def show_tables(dbname='peizhibiao'):
    conn = get_conn(dbname)
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT table_name,
                   pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) as size,
                   (SELECT reltuples::int FROM pg_class WHERE oid = quote_ident(table_name)::regclass) as rows
            FROM information_schema.tables
            WHERE table_schema='public' AND table_type='BASE TABLE'
            ORDER BY pg_total_relation_size(quote_ident(table_name)) DESC
        """)
        rows = cur.fetchall()
        print(f'[peizhibiao] 数据库: {dbname}\n')
        for t, s, r in rows:
            print(f'  {t:35s} {s:>8}  {r:>6} 行')
    finally:
        cur.close()
        conn.close()


def show_stats(dbname='peizhibiao'):
    """通用统计：表数量 + 数据量排序"""
    conn = get_conn(dbname)
    cur = conn.cursor()
    try:
        print(f'📊 [{dbname}] 数据库概况\n')
        cur.execute("""
            SELECT table_name,
                   pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) as size,
                   (SELECT reltuples::int FROM pg_class WHERE oid = quote_ident(table_name)::regclass) as approx_rows
            FROM information_schema.tables
            WHERE table_schema='public' AND table_type='BASE TABLE'
            ORDER BY pg_total_relation_size(quote_ident(table_name)) DESC
        """)
        rows = cur.fetchall()
        print(f'  共 {len(rows)} 张表\n')
        for t, s, r in rows:
            print(f'  {t:35s} {s:>8}  ~{r:>7} 行')

        cur.execute("SELECT viewname FROM pg_views WHERE schemaname='public' ORDER BY viewname")
        views = cur.fetchall()
        if views:
            print(f'\n  视图 ({len(views)}):')
            for v in views:
                print(f'    {v[0]}')
    finally:
        cur.close()
        conn.close()


def list_dbs():
    print('可用数据库:\n')
    for name, desc in sorted(AVAILABLE_DBS.items()):
        # 快速查询每个库的表数量
        try:
            conn = get_conn(name)
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")
            n = cur.fetchone()[0]
            cur.close()
            conn.close()
            print(f'  {name:20s} {desc:<20s}  ({n} 张表)')
        except:
            print(f'  {name:20s} {desc:<20s}  (连接失败)')


def show_help():
    print(__doc__)


if __name__ == '__main__':
    # 解析 --db=xxx 参数
    dbname = 'peizhibiao'
    sql_args = []
    for arg in sys.argv[1:]:
        if arg.startswith('--db='):
            dbname = arg.split('=', 1)[1]
            if dbname not in AVAILABLE_DBS:
                print(f'未知数据库: {dbname}，可用: {", ".join(AVAILABLE_DBS.keys())}')
                sys.exit(1)
        elif arg.startswith('-d') and len(arg) > 2:
            dbname = arg[2:]
        elif arg in ('--list-dbs',):
            list_dbs()
            sys.exit(0)
        else:
            sql_args.append(arg)

    if not sql_args:
        if not sys.stdin.isatty():
            sql = sys.stdin.read().strip()
            if sql:
                query(sql, dbname=dbname)
            else:
                show_help()
        else:
            show_help()
    else:
        cmd = sql_args[0]
        if cmd in ('--help', '-h'):
            show_help()
        elif cmd in ('--tables', '-t'):
            show_tables(dbname=dbname)
        elif cmd in ('--stats', '-s'):
            show_stats(dbname=dbname)
        else:
            query(' '.join(sql_args), dbname=dbname)
