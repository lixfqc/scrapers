# -*- coding: utf-8 -*-
"""B电脑说"都处理完了"的客观验收脚本（A电脑直接跑，4套指标全量化，不口头判断）。

验收指标对应上午文档P0-P2问题：
  验收1 M2: spec_name 截断（模式A首字丢 + 模式B版型丢字尾）
  验收2 M1: drive_section 单目+城市路段 39条残留 + seg_cnt分布
  验收3 : assist_image LENGTH(49/50) 物理截断残留 + 列长度结构
  验收4 : assist_image drive_section lane_centering 等7字段 varchar(N) 总览（补文档§2.7）
"""
import sys, re
import psycopg2
sys.path.insert(0, r'd:\数据\配置表')
from cloud_db import HOST, PORT, USER, PASS

conn = psycopg2.connect(host=HOST, port=PORT, user=USER, password=PASS, dbname='peizhibiao', sslmode='disable')
conn.autocommit = True; cur = conn.cursor()

print('='*96)
print('【B电脑处理完毕客观验收 2026-08-11 18:30 A电脑侧执行】')
print('='*96)

# ---------- 验收1：spec_name 截断（前摄单目2896样本，模式A+B 353 -> ?） ----------
print('\n--- 验收1 M2 spec_name 截断（前摄单目样本 N=2896，模式A+B 353 → ?） ---')
# 判据修正(2026-08-12)：模式B（"以[智尊享耀越领贵豪]结尾且缺版/型"）会误报合法版本名。
# 以下 18 个 spec_id 经 DOM 后验（spec_dom_repair --custom-list）确认：配置页真值 == 数据库值，
# 属合法版本名（如"穿越/尊享/尊耀/星耀/智/臻享/誉尊/威享/天越"），非丢字污染 → 验收时排除。
LEGAL_SPECNAME_IDS = {61130,70712,73185,72233,75231,76337,69416,77964,71803,
                      70000,69434,75064,72068,75947,38132,50764,59167,53134}
id_list = ','.join(str(i) for i in sorted(LEGAL_SPECNAME_IDS))
sql_a = """
SELECT COUNT(*) FROM data_peizhibiao
WHERE front_camera_type = '单目'
  AND LENGTH(series_name) > 1
  AND SUBSTRING(spec_name, 1, POSITION(' ' IN spec_name || ' ') - 1) = SUBSTRING(series_name, 1, 1)
  AND SUBSTRING(spec_name, 1, LENGTH(series_name)) <> series_name;
"""
sql_b = f"""
SELECT COUNT(*) FROM data_peizhibiao
WHERE front_camera_type = '单目'
  AND (spec_name ~ %s AND spec_name !~ %s)
  AND spec_id NOT IN ({id_list});
"""
sql_tot = "SELECT COUNT(*) FROM data_peizhibiao WHERE front_camera_type = '单目';"
cur.execute(sql_tot); N_total = cur.fetchone()[0]
cur.execute(sql_a); A_now = cur.fetchone()[0]
cur.execute(sql_b, [r'[智尊享耀越领贵豪]\s*$', r'[版型]\s*$']); B_now = cur.fetchone()[0]
sql_dup = f"""
SELECT COUNT(DISTINCT spec_id) FROM data_peizhibiao
WHERE front_camera_type = '单目' AND (
  (LENGTH(series_name) > 1
    AND SUBSTRING(spec_name, 1, POSITION(' ' IN spec_name || ' ') - 1) = SUBSTRING(series_name, 1, 1)
    AND SUBSTRING(spec_name, 1, LENGTH(series_name)) <> series_name)
  OR (spec_name ~ %s AND spec_name !~ %s)
) AND spec_id NOT IN ({id_list});
"""
cur.execute(sql_dup, [r'[智尊享耀越领贵豪]\s*$', r'[版型]\s*$']); AB_uniq = cur.fetchone()[0]
pct = round(100.0*AB_uniq/N_total, 2) if N_total else 0
print(f'  样本总数  front_camera_type=单目 : {N_total:>5}')
print(f'  模式A（车系名只剩首字）         : {A_now:>5}  （修复前 15）')
print(f'  模式B（版型丢字尾，缺版/型）     : {B_now:>5}  （修复前 340；现剔除{len(LEGAL_SPECNAME_IDS)}条DOM确认合法版本名）')
print(f'  两模式去重合计                   : {AB_uniq:>5}  （修复前 353 / 12.18%）')
print(f'  当前占比                         : {AB_uniq}/{N_total} = {pct:.2f}%')
print(f'  判定阈值（报告§4验收）: 异常条数 ≤ 5 → 通过；否则未通过')
print(f'  → 【验收1 ：{"✅ PASS" if AB_uniq <= 5 else "❌ FAIL: 仍有 %d 条未修复" % AB_uniq}】')

# ---------- 验收2 M1: drive_section 单目+高速在前污染残留 + seg_cnt分布 ----------
print('\n--- 验收2 M1 drive_section 污染残留（高速在前"高速路段 城市路段" 39 → ?） + 分段分布前后对比 ---')
# 判据修正(2026-08-12)：M1污染形态 = "高速路段 城市路段"（高速在前，整行串联把邻列"城市路段"带进来）。
# "城市路段 高速路段"（城市在前）是合法双路段真值（奥迪A6L/Q6L e-tron、帝豪、红旗EH7，DOM已验证），不误判。
cur.execute("""
SELECT COUNT(*) FROM data_peizhibiao
WHERE front_camera_type = '单目' AND drive_section ILIKE %s
""", ['%高速路段 城市路段%']); city_now = cur.fetchone()[0]
print(f'  2.1 单目前摄 + drive_section 高速在前"高速路段 城市路段" : {city_now:>5}  （修复前 39）')
print(f'      → 阈值（报告§4验收）: ≤ 3 → 通过；否则未通过')
print(f'      → 【2.1：{"✅ PASS" if city_now <= 3 else "❌ FAIL: 仍有 %d 条" % city_now}】')

# seg_cnt 分布（原值 seg=2 无价格占 71.8%，修完应该明显下降）
cur.execute("SELECT COUNT(*) FROM data_peizhibiao WHERE drive_section IS NOT NULL AND LENGTH(TRIM(drive_section))>0")
ds_tot = cur.fetchone()[0]
print(f'\n  2.2 drive_section 非空总数: {ds_tot}  （修复前 1495）')
print(f'      seg_cnt 分布:')
buckets = [
    ('1（单路段）', 1, False),
    ('2（双路段，无价格）', 2, False),
    ('2（单路段+选装价）', 2, True),
    ('3+（多路段/组合）', None, None),
]
seg_sql = """
SELECT
  LENGTH(REGEXP_REPLACE(REGEXP_REPLACE(TRIM(drive_section), '\\s*\\([^)]*\\)\\s*', '', 'g'),
         '[\\s]+', ' ', 'g')) -
  LENGTH(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(TRIM(drive_section), '\\s*\\([^)]*\\)\\s*', '', 'g'),
         '[\\s]+', ' ', 'g'), '\\s', '', 'g')) + 1 AS seg,
  CASE WHEN drive_section ~ '[\\(（].*[万w元块]' THEN 1 ELSE 0 END has_price,
  COUNT(*)
FROM data_peizhibiao
WHERE drive_section IS NOT NULL AND LENGTH(TRIM(drive_section))>0
GROUP BY 1, 2 ORDER BY 1, 2;
"""
cur.execute(seg_sql)
rows = cur.fetchall()
print(f'      {"seg":<10} {"has_price":>10} {"count":>7}  {"pct":>6}  修复前对照')
print(f'      {"-"*10} {"-"*10} {"-"*7}  {"-"*6}  --------')
before = {1: 416, (2,0): 1073, (2,1): 5, (3,): 1, (0,): 0}
seg_map_cnt = {}
for seg, hp, cnt in rows:
    seg_map_cnt[(seg, hp)] = seg_map_cnt.get((seg, hp), 0) + cnt
    pct = round(100.*cnt/ds_tot, 1) if ds_tot else 0
    bef = before.get((seg, hp), '-')
    if seg >= 3:
        pass
    print(f'      {str(seg):<10} {str(bool(hp)):>10} {cnt:>7}  {pct:>5.1f}%  bef: {bef}')
# 判据修正(2026-08-12)：M1主嫌疑仅统计"高速在前污染形态"，排除"城市在前"合法双路段（DOM已验证为真值）。
cur.execute("SELECT COUNT(*) FROM data_peizhibiao WHERE drive_section LIKE '%高速路段 城市路段%'")
seg2_poll = cur.fetchone()[0]
pct2 = round(100.*seg2_poll/ds_tot, 1) if ds_tot else 0
print(f'\n      关键指标: 高速在前"高速路段 城市路段"（M1主嫌疑）= {seg2_poll} 条，占 {pct2}%（修复前 39 条，整行串联）')
print(f'      → 【2.2 分布：{"✅ 已清零/达标" if seg2_poll <= 3 else "⚠️ 仍有 "+str(seg2_poll)+" 条污染残留需处理"}（阈值 ≤3 条）】')

# ---------- 验收3 assist_image 物理截断 ----------
print('\n--- 验收3 assist_image 物理截断（LENGTH=49/50） + 字段长度结构 ---')
cur.execute("""
SELECT LENGTH(assist_image), COUNT(*) FROM data_peizhibiao
WHERE assist_image IS NOT NULL
GROUP BY LENGTH(assist_image) ORDER BY LENGTH(assist_image) DESC LIMIT 10;
""")
len_rows = cur.fetchall()
cur.execute("SELECT COUNT(*) FROM data_peizhibiao WHERE assist_image IS NOT NULL")
ai_tot = cur.fetchone()[0]
trunc49_50 = sum(c for ln, c in len_rows if ln in (49, 50))
print(f'  assist_image 非空总数: {ai_tot}')
print(f'  LENGTH=49/50 条数: {trunc49_50}  （修复前 614 + DB侧物理截断）')
print(f'  前十 length 分布（倒序）:')
for ln, cnt in len_rows:
    print(f'    len={ln:>4}: {cnt:>5} 条')
print(f'  → 阈值：如已扩列 v500 → 应出现大量 len>50 且 LENGTH(49/50) 明显下降；否则 FAIL')
print(f'  → 【验收3.1 截断残留：{"✅ PASS" if trunc49_50 <= 50 else "⚠️ 仍有 "+str(trunc49_50)+" 条卡在49/50（未扩列或未重跑）"}】')

# 列结构：information_schema.columns 查 assist_image/drive_section 实际 varchar 长度
print('\n  3.2 字段真实列长度（information_schema.columns 查证，不看文档看实际DDL）:')
fields_check = ['spec_name','drive_section','assist_image','lane_centering','auto_park','lane_change_assist','active_brake']
placeholders = ','.join(['%s']*len(fields_check))
cur.execute(f"""
SELECT column_name, data_type, character_maximum_length,
       CASE WHEN character_maximum_length IS NULL THEN 'text/unbound'
            WHEN character_maximum_length >= 500 THEN 'varchar(≥500)充足'
            WHEN character_maximum_length >= 200 THEN 'varchar(200+)宽松'
            ELSE 'varchar(<200)偏短' END AS status
FROM information_schema.columns
WHERE table_name='data_peizhibiao' AND table_schema='public'
  AND column_name IN ({placeholders})
ORDER BY column_name
""", fields_check)
max_map = {c: 0 for c in fields_check}
for r in cur.fetchall():
    col, dtype, mlen, status = r
    print(f'    {col:<22} {dtype:<15} len={str(mlen):<10} → {status}')
    max_map[col] = mlen or 999999
# 各列实际占用 max( LENGTH(col) )
cur.execute("SELECT " + ", ".join(f"MAX(LENGTH({c})) AS max_len_{c}" for c in fields_check) +
            " FROM data_peizhibiao;")
row = cur.fetchone()
print(f'\n  3.3 各列实际占用最大值（实际数据的 max LENGTH 对 DDL 长度）:')
for i, c in enumerate(fields_check):
    occ = row[i] or 0
    ddl = max_map[c]
    occ_pct = round(100.*occ/ddl, 1) if ddl and ddl<99999 else 0
    print(f'    {c:<22}: 实际占用={occ:>4}字 / DDL={ddl if ddl<99999 else "text"}  占用率={occ_pct if ddl<99999 else "—（无上限）"}%')
short_fields = [c for c in fields_check if max_map[c] < 200 and max_map[c] < 99999]
print(f'  → 【验收3.2 列扩列：{"✅ 无偏短列" if not short_fields else "❌ 仍有偏短DDL: "+str(short_fields)}（阈值 <200 视为偏短）】')

cur.close(); conn.close()
print('\n===== 四项验收执行完毕 =====')
print('  （若有 FAIL 项，建议 A 电脑直接跑 spec_dom_repair.py 路线3清存脏，不等 B 电脑再修一遍）')
