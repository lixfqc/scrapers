# -*- coding: utf-8 -*-
"""第4步：DB 扩列 — 备份 6 字段 + 扩列到 varchar(500) + 验证"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import psycopg2
DB = dict(host='pgm-bp1sf8zujdx18698io.pg.rds.aliyuncs.com', port=5432, user='Levin001',
          password='Li800124', dbname='peizhibiao')
conn = psycopg2.connect(**DB); conn.autocommit = True; cur = conn.cursor()

FIELDS = ['assist_image', 'drive_section', 'lane_centering', 'auto_park', 'lane_change_assist', 'active_brake']

print('=' * 70)
print('第4步：DB 扩列（备份 → 扩列到 varchar(500) → 验证）')
print('=' * 70)

# ① 备份
print('\n① 备份 6 字段当前值到 data_peizhibiao_prewiden_20260811 ...')
cur.execute("""
    CREATE TABLE IF NOT EXISTS data_peizhibiao_prewiden_20260811 AS
    SELECT spec_id, spec_name, assist_image, drive_section, lane_centering,
           auto_park, lane_change_assist, active_brake
    FROM data_peizhibiao
""")
cur.execute("SELECT COUNT(*) FROM data_peizhibiao_prewiden_20260811")
print(f'   备份完成: {cur.fetchone()[0]} 行')

# ② 删视图解除依赖（两个视图都依赖这些列，DirectAlter 会被视图规则挡住）
print('\n② 删除依赖视图（扩列后重建）...')
cur.execute('DROP VIEW IF EXISTS v_cleaned_config_data CASCADE')
print('   v_cleaned_config_data 已删除')
cur.execute('DROP VIEW IF EXISTS v_data_peizhibiao CASCADE')
print('   v_data_peizhibiao 已删除')

# ③ 扩列
print('\n③ 扩列到 varchar(500) ...')
for f in FIELDS:
    cur.execute(f'ALTER TABLE data_peizhibiao ALTER COLUMN {f} TYPE varchar(500)')
    print(f'   {f}: varchar(500) ✅')

# ④ 重建视图（按原定义）
print('\n④ 重建视图 v_data_peizhibiao ...')
cur.execute('''
    CREATE OR REPLACE VIEW v_data_peizhibiao AS
    SELECT d.id,
        d.series_id, d.series_name, d.spec_name, d.guide_price, d.energy_type,
        d.adas_level, d.adas_system, d.cruise_system, d.signal_recognition,
        d.lane_centering, d.lidar_count, d.lidar_brand, d.max_power_kw,
        d.max_torque_nm, d.battery_capacity_kwh, d.battery_type, d.electric_range,
        d.fuel_type, d.sale_status, d.spec_state, d.created_at, d.updated_at,
        d.spec_id, d.price_range, d.body_type, d.seat_count, d.engine_type,
        d.emission_standard, d.wheelbase, d.range_km, d.fast_charge_time,
        d.curb_weight, d.config_hash, d.scraped_at, d.fast_charge_hour,
        d.fast_charge_range, d.max_load_kg, d.towing_weight_kg, d.warranty,
        d.min_battery_fuel_consumption, d.oil_electric_consumption,
        d.motor_count, d.motor_layout, d.abs_system, d.acceleration_0_100,
        d.active_brake, d.asr_system, d.assist_image, d.body_structure,
        d.brake_assist, d.camera_count, d.car_connectivity, d.chassis540,
        d.chip_name, d.chip_tops, d.cltc_range_km, d.config_raw,
        d.curb_weight_kg, d.data_source, d.dimensions_mm, d.dow_warning,
        d.drive_section, d.ebd_system, d.energy_consumption, d.engine_info,
        d.esc_system, d.front_camera_type, d.front_collision, d.hd_map,
        d.hud_display, d.in_cabin_camera_count, d.infotainment_system,
        d.lane_change_assist, d.lane_departure, d.lidar_lines, d.listing_date,
        d.max_speed_kmh, d.mmwave_radar_count, d.motor_ps, d.network_type,
        d.option_raw, d.ota_upgrade, d.ramp_auto_exit, d.rear_collision,
        d.screen_size, d.screen_type, d.sentinel_mode, d.steering_wheel_detect,
        d.tire_pressure, d.trace_reverse, d.ultrasonic_radar_count,
        d.voice_control, d.wheelbase_mm, d.wltc_fuel_consumption,
        d.wltc_range_km, d.has_adas, d.auto_park, d.memory_park, d.remote_park,
        d.model_year,
        COALESCE(b.brand_name, d.brand_name) AS brand_name,
        COALESCE(b.manufacturer, d.manufacturer) AS manufacturer
    FROM data_peizhibiao d
    LEFT JOIN brand_series_v2 b ON d.series_id = b.series_id
''')
print('   v_data_peizhibiao 已重建')

# ⑤ 重建 v_cleaned_config_data（按原定义）
print('\n⑤ 重建视图 v_cleaned_config_data ...')
cur.execute('''
    CREATE OR REPLACE VIEW v_cleaned_config_data AS
    SELECT spec_id,
        voice_control AS "语音控制",
        adas_system AS "adas系统",
        lidar_brand AS "激光雷达品牌",
        drive_section AS "驾驶路段",
        hd_map AS "高清地图",
        assist_image AS "辅助影像",
        updated_at AS "更新时间"
    FROM data_peizhibiao
    WHERE (voice_control IS NOT NULL AND voice_control <> ''::text AND voice_control <> '-'::text)
       OR (adas_system IS NOT NULL AND adas_system <> ''::text AND adas_system <> '-'::text)
       OR (lidar_brand IS NOT NULL AND lidar_brand <> ''::text AND lidar_brand <> '-'::text)
       OR (drive_section IS NOT NULL AND drive_section <> ''::text AND drive_section <> '-'::text)
       OR (hd_map IS NOT NULL AND hd_map <> ''::text AND hd_map <> '-'::text)
       OR (assist_image IS NOT NULL AND assist_image <> ''::text AND assist_image <> '-'::text)
''')
print('   v_cleaned_config_data 已重建')

# ③ 验证
print('\n③ 验证列长度 ...')
cur.execute("""
    SELECT column_name, character_maximum_length
    FROM information_schema.columns
    WHERE table_name='data_peizhibiao' AND table_schema='public'
      AND column_name = ANY(%s)
    ORDER BY column_name
""", (FIELDS,))
ok = True
for col, mlen in cur.fetchall():
    status = '✅' if mlen == 500 else '❌'
    if mlen != 500: ok = False
    print(f'   {col:<22} len={mlen:<5} {status}')

cur.close(); conn.close()
print('\n' + '=' * 70)
print('扩列完成！' if ok else '扩列未完全成功，请检查！')