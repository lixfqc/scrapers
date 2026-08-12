# -*- coding: utf-8 -*-
"""
汽车之家配置爬虫 v7 — 效率优化版
- 优化1: 空车系(0款)仅等5s（预留，当前统一用主延迟）
- 优化2: 去除长休眠概率
- 优化3: 批次休眠5-12分钟
- 优化4: 2线程并发 (ThreadPoolExecutor)
- 优化5: 连接复用 + 每20次换Cookie
"""
import urllib.request, urllib.error, gzip, re, json, time, random, logging, sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import psycopg2

# ==================== 配置 ====================
DB = dict(host='pgm-bp1sf8zujdx18698io.pg.rds.aliyuncs.com', port=5432, user='Levin001', password='Li800124', dbname='peizhibiao')

ANTI_CRAWL = {
    'delay_with_data': (20, 35),          # 有数据车系间隔（安全优先）
    'delay_empty': (8, 15),               # 空车系间隔
    'delay_skip': (1, 3),                 # 全部款型已存在-快速跳过
    'delay_batch_done': (5*60, 12*60),    # 有数据批次后休眠
    'delay_batch_empty': (1*60, 4*60),    # 空车系批次后休眠
    'batch_size': (40, 60),
    'error_sleep_range': (10*60, 30*60),
    'max_consecutive_errors': 5,
    'max_total_errors': 20,
    'workers': 2,
    # 空车系快速通道：如果本轮80%以上为空，下一轮用更短延迟
    'empty_ratio_threshold': 0.8,
    'quick_scan_delay': (10, 20),        # 快速预扫延迟
}

# PC端UA（汽车之家配置页是PC端页面，用PC UA避免指纹矛盾）
UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0',
]

# ==================== 日志 ====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s',
    handlers=[logging.FileHandler('scraper_v7.log', encoding='utf-8'), logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)
err_logger = logging.getLogger('errors')
err_handler = logging.FileHandler('scraper_v7_errors.log', encoding='utf-8')
err_handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
err_logger.addHandler(err_handler)
err_logger.setLevel(logging.WARNING)

# ==================== 连接复用（每N次请求换Cookie，避免全量关联）====================
_opener = None
_opener_lock = threading.Lock()
_request_count = 0
_COOKIE_RESET_INTERVAL = 20  # 每20次请求换新的Cookie Jar

def get_opener():
    global _opener, _request_count
    if _opener is None or _request_count >= _COOKIE_RESET_INTERVAL:
        with _opener_lock:
            if _opener is None or _request_count >= _COOKIE_RESET_INTERVAL:
                _opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
                _request_count = 0
    return _opener

# ==================== 字段定义 ====================
ITEM_ID_MAP = {
    34: 'cruise_system', 8424: 'assist_system', 8419: 'assist_level',
    8438: 'ultrasonic_radar_count', 8439: 'mmwave_radar_count', 8440: 'lidar_count',
    8464: 'camera_count', 8648: 'lane_centering', 9059: 'drive_section',
    8706: 'memory_park', 8421: 'remote_park', 8407: 'lane_change_assist',
    8709: 'signal_recognition', 9046: 'front_camera_type', 9049: 'in_cabin_camera_count',
    9050: 'lidar_brand', 9052: 'lidar_lines', 35: 'auto_park', 8414: 'hd_map',
    32: 'assist_image', 8409: 'chassis540', 8767: 'steering_wheel_detect',
    8707: 'ramp_auto_exit', 7074: 'trace_reverse',
    8436: 'chip_name', 8437: 'chip_tops',
    2: 'abs_system', 7: 'ebd_system', 9: 'brake_assist',
    10: 'asr_system', 11: 'esc_system', 21: 'tire_pressure',
    14: 'active_brake', 13: 'lane_departure',
    8405: 'dow_warning', 8406: 'front_collision', 8430: 'rear_collision', 8434: 'sentinel_mode',
    8423: 'infotainment_system', 111: 'screen_size', 110: 'screen_type',
    113: 'voice_control', 117: 'car_connectivity', 6101: 'ota_upgrade',
    8412: 'network_type', 82: 'hud_display',
}

FIELD_MAP = {
    'price_guide': 'guide_price', 'assist_system': 'adas_system',
    'assist_level': 'adas_level', 'total_max_power_kw': 'max_power_kw',
    'total_max_torque_nm': 'max_torque_nm',
    'battery_fast_charge_hour': 'fast_charge_hour',
    'battery_fast_charge_range': 'fast_charge_range',
    'emission_standard': 'emission_standard',
    'max_load_kg': 'max_load_kg', 'towing_weight_kg': 'towing_weight_kg',
    'warranty': 'warranty',
    'min_battery_fuel_consumption': 'min_battery_fuel_consumption',
    'oil_electric_consumption': 'oil_electric_consumption',
    'motor_count': 'motor_count', 'motor_layout': 'motor_layout',
}

SPEC_STATE_MAP = {10: '未售', 20: '在售', 30: '停售', 40: '停售'}

# ==================== 参数匹配 ====================
def match_param(name, val):
    if '厂' in name and '()' in name and val and (val.replace('.','').replace('-','').isdigit() or '万' in val):
        return 'price_guide'
    if name.startswith('厂') and '()' not in name: return None
    if name.startswith('级'): return None
    if '能源类' in name: return 'energy_type'
    if '上市' in name: return 'listing_date'
    if 'CLTC' in name and '纯电' in name: return 'cltc_range_km'
    if 'WLTC' in name and '纯电' in name: return 'wltc_range_km'
    if 'WLTC' in name and '续航' in name and '纯电' not in name: return None
    if 'CLTC' in name and '续航' in name and '纯电' not in name: return None
    if 'WLTC' in name and 'L/100km' in name: return 'wltc_fuel_consumption'
    if 'WLTC' in name: return 'wltc_range_km'
    if 'NEDC' in name: return None
    if '电池' in name and 'kWh' in name: return 'battery_capacity_kwh'
    if '电池' in name and '小时' in name: return 'battery_fast_charge_hour'
    if '电池' in name and '范围' in name: return 'battery_fast_charge_range'
    if '电池' in name and '类型' in name: return None
    if '综合' in name and 'kW' in name: return 'total_max_power_kw'
    if '综合' in name and 'N·m' in name: return 'total_max_torque_nm'
    if ('后' in name or '前' in name) and '电动' in name: return None
    if '最大' in name and 'kW' in name: return 'max_power_kw'
    if '最大' in name and 'N·m' in name: return 'max_torque_nm'
    if '车身' in name: return 'body_structure'
    if '电动' in name and '总' in name and 'kW' in name: return 'total_max_power_kw'
    if '电动' in name and '总' in name and 'N·m' in name: return 'total_max_torque_nm'
    if '电动' in name and '总' in name and ('Ps' in name or '马力' in name): return 'motor_ps'
    if '电动' in name and ('品牌' in name or '型' in name): return None
    if '电机' in name and '类型' in name: return None
    if '电动' in name and ('Ps' in name or '马力' in name): return 'motor_ps'
    if '驱动' in name and '电机' in name and '数' in name: return 'motor_count'
    if '电机' in name and '布局' in name: return 'motor_layout'
    if '长' in name and '宽' in name: return 'dimensions_mm'
    if '官方' in name or ('0-100' in name and 's' in name.lower()): return 'acceleration_0_100'
    if '最高' in name and 'km' in name: return 'max_speed_kmh'
    if 'L/100km' in name and '最低' in name: return 'min_battery_fuel_consumption'
    if 'L/100km' in name and '油电' in name: return 'oil_electric_consumption'
    if 'L/100km' in name or '燃料消耗' in name: return 'energy_consumption'
    if '发动机' in name and ('型' in name or '布局' in name): return None
    if '发动机' in name: return 'engine_info'
    if '环保' in name: return 'emission_standard'
    if '准拖' in name and '(kg)' in name: return 'towing_weight_kg'
    if '满载' in name and '(kg)' in name: return 'max_load_kg'
    if '整车' in name or '质保' in name: return 'warranty'
    if '最大' in name and '(kg)' in name: return None
    if '(kg)' in name: return 'curb_weight_kg'
    return None

# ==================== 网络请求 ====================
def fetch_html(url, timeout=30, retry=2):
    """请求页面，支持重试和错误分类"""
    last_err = None
    for attempt in range(retry + 1):
        try:
            global _request_count
            opener = get_opener()
            _request_count += 1  # 计数用于定期换Cookie
            req = urllib.request.Request(url, headers={
                'User-Agent': random.choice(UA_POOL),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Referer': 'https://www.autohome.com.cn/',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'max-age=0',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
            })
            resp = opener.open(req, timeout=timeout)
            data = resp.read()
            if resp.getheader('Content-Encoding') == 'gzip': data = gzip.decompress(data)
            return data.decode('utf-8', errors='replace')
        except urllib.error.HTTPError as e:
            last_err = f'HTTP_{e.code}'
            if e.code in (403, 503):
                raise Exception(f'FATAL_HTTP_{e.code}') from e  # 致命，上层触发长休眠
            if attempt < retry:
                time.sleep(random.uniform(5, 15))
        except Exception as e:
            last_err = str(e)[:80]
            if attempt < retry:
                time.sleep(random.uniform(3, 10))
    raise Exception(last_err or 'UNKNOWN')

def clean(t):
    return re.sub(r'<[^>]+>', '', t or '').strip()

# 汽车之家配置页 option 区域的 CSS 混淆映射（index→content，是固定的）
# 通过浏览器 document.styleSheets 提取，index 为 hs_kw{N} 中的 N
_OPTION_CSS_INDEX_MAP = {
    0: "适", 1: "万", 2: "摄像头", 3: "舒", 4: "制动力分配", 5: "比例",
    6: "加热", 7: "前", 8: "驻车", 9: "碳纤", 10: "成功",
    11: "悬架", 12: "行车电脑", 13: "放倒", 14: "中央", 15: "合金",
    16: "调节", 17: "风", 18: "接口", 19: "空气", 20: "铝",
    21: "高度", 22: "仪表盘", 23: "充电桩", 24: "前排", 25: "并线",
    26: "远光灯", 27: "蓝牙", 28: "气囊", 29: "电话", 30: "商",
    31: "升", 32: "上下", 33: "喇叭", 34: "后排", 35: "支撑",
    36: "独立", 37: "全液晶", 38: "真皮", 39: "无钥匙", 40: "牵引力控制",
    41: "前后", 42: "预警", 43: "影像", 44: "儿童座椅", 45: "名称",
    46: "扬声器", 47: "质量", 48: "稳定", 49: "材质", 50: "通风",
    51: "近光灯", 52: "号", 53: "导", 54: "城市",
}

def _all_specs_exist(series_id, spec_ids):
    conn = psycopg2.connect(**DB)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM data_peizhibiao WHERE series_id=%s AND spec_id = ANY(%s)", (series_id, list(spec_ids)))
        return cur.fetchone()[0] == len(spec_ids)
    finally:
        conn.close()

def _extract_css_map(html):
    """从 HTML 中提取 CSS 混淆映射（hs_kw 类 → ::before content）
    策略：从 JS 脚本提取后缀，结合硬编码的 index→content 映射构建完整表
    返回: dict { 'hs_kw54_optionio': '城市', ... }
    """
    css_map = {}
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    for s in scripts:
        # 修复(2026-08-11): 去掉 '_option' 硬限制，接受 _option 和 _config 两种后缀
        # 去掉 break（否则只取到第一个 _option 脚本块就退出，_config 脚本永远轮不到）
        if '$InsertRule$' not in s or len(s) > 80000:
            continue
        # 提取后缀：从 $GetClassName$ 函数中提取
        # 格式: return '.hs_kw' + $index$ + '_optionXX'; 或 '_configAJ'
        suffix_m = re.search(r"\+ \$index\$ \+ '([^']*)'", s)
        if suffix_m:
            suffix = suffix_m.group(1)
            # 用硬编码的 index→content 映射构建完整 CSS 映射
            # _option 沿用 _OPTION_CSS_INDEX_MAP；_config 也先尝试同一套 index→char
            # （实测帝豪/启源 _config 命中后还原正确；若个别页面 index→char 不一致，
            #   由 phase3b spec_dom_repair.py 用 DOM 真值兜底回填）
            for idx, content in _OPTION_CSS_INDEX_MAP.items():
                cls_name = f"hs_kw{idx}{suffix}"
                css_map[cls_name] = content
    return css_map

def _resolve_css_text(raw_text, css_map):
    """解析 CSS 混淆的 subname 文本
    如: "全速自<span class='hs_kw0_optionJC'></span>应巡航" + css_map → "全速自适应巡航"
    修复: 用 re.sub 在位替换 span 标签，而非把映射字符拼接到开头
    """
    if not raw_text or '<span' not in raw_text:
        return clean(raw_text)
    
    def replace_span(match):
        full_tag = match.group(0)
        cls_m = re.search(r"class='(hs_kw\d+_\w+)'", full_tag)
        if cls_m:
            return css_map.get(cls_m.group(1), '')
        return ''
    
    result = re.sub(r'<span[^>]*></span>', replace_span, raw_text)
    return clean(result)

def extract_json(html, varname):
    idx = html.find(varname + ' = {')
    if idx < 0: return None
    start = html.find('{', idx)
    depth = 1; end = start + 1
    while end < len(html) and depth > 0:
        if html[end] == '{': depth += 1
        elif html[end] == '}': depth -= 1
        end += 1
    js = html[start:end]
    try: return json.loads(js)
    except:
        for term in [';\nvar ', ';var ', ';\nwindow.', ';window.']:
            p = js.find(term)
            if p > 5000:
                try: return json.loads(js[:p])
                except: continue
    return None

def extract_real_series_name(html):
    title_match = re.search(r'<title>([^<]+)</title>', html)
    if title_match:
        parts = title_match.group(1).split('|')
        if len(parts) >= 2: return parts[1].strip()
    return None

def verify_series_mapping(series_id, expected_name, real_name):
    if not real_name: return True, "无法提取真实车系名，跳过验证"
    def normalize(name):
        return re.sub(r'[\s\-_]', '', name or '')
    ne, nr = normalize(expected_name), normalize(real_name)
    if ne == nr: return True, "完全匹配"
    if ne in nr or nr in ne: return True, f"部分匹配: expected='{expected_name}', real='{real_name}'"
    return False, f"映射错误! expected='{expected_name}', real='{real_name}', series_id={series_id}"

# ==================== 爬取 ====================
def scrape(series_id):
    html = fetch_html('https://car.autohome.com.cn/config/series/' + str(series_id) + '.html')
    if not html or len(html) < 10000: return [], None, None, None, None
    real_series_name = extract_real_series_name(html)
    cfg = extract_json(html, 'var config')
    opt = extract_json(html, 'var option')
    if not cfg: return [], None, real_series_name, None, None

    specs_list = cfg.get('result', {}).get('speclist', [])
    # 空车系：speclist 为空（真正停产/无配置页），不按 HTML 长度判断
    if not specs_list:
        return [], None, real_series_name, cfg, opt  # 标记空车系，但传递 cfg/opt 供后续处理
    spec_state = None
    raw_state = specs_list[0].get('specstate')
    if raw_state is not None:
        spec_state = SPEC_STATE_MAP.get(raw_state, f'未知({raw_state})')

    all_sids = set(s.get('specid') for s in specs_list if s.get('specid'))
    # 快速比对：全部款型已在库中？是则跳过参数解析
    if all_sids and _all_specs_exist(series_id, all_sids):
        return None, None, real_series_name, None, None
    records = {}

    # 修复(2026-08-11): css_map 提前到 cfg 循环前构建，
    # 否则下面 config 分支的 spec_name 赋值时 css_map 还没建
    css_map = _extract_css_map(html)

    for pt in cfg.get('result', {}).get('paramtypeitems', []):
        for pi in pt.get('paramitems', []):
            clean_name = clean(pi.get('name', ''))
            for item in pi.get('valueitems', []):
                sid = item.get('specid')
                if not sid or sid not in all_sids: continue
                if sid not in records: records[sid] = {'spec_id': sid, 'spec_name': ''}
                # 修复(2026-08-11): config 分支的 value 也走 CSS 还原（原 clean() 只剥标签会丢字）
                val = _resolve_css_text(item.get('value', ''), css_map)
                if '车型' in clean_name:
                    if val and not records[sid].get('spec_name'): records[sid]['spec_name'] = val
                    continue
                if not val or val in ('-', ''): continue
                field = match_param(clean_name, val)
                if field: records[sid][field] = val

    if opt:
        for ct in opt.get('result', {}).get('configtypeitems', []):
            for ci in ct.get('configitems', []):
                item_id = ci.get('id')
                if item_id not in ITEM_ID_MAP: continue
                db_col = ITEM_ID_MAP[item_id]
                for item in ci.get('valueitems', []):
                    sid = item.get('specid')
                    if not sid: continue
                    sl = item.get('sublist', [])
                    if sl:
                        # 拼接所有 sublist 项的 subname（用、分隔）
                        parts = []
                        for sub in sl:
                            subname = _resolve_css_text(sub.get('subname', ''), css_map)
                            if subname and subname not in ('-', ''):
                                parts.append(subname)
                        val = '、'.join(parts) if parts else ''
                    else:
                        val = clean(item.get('value', ''))
                    if val and val not in ('-', ''):
                        if sid not in records: records[sid] = {'spec_id': sid, 'spec_name': ''}
                        records[sid][db_col] = val

    return [r for r in records.values() if r.get('spec_name')], spec_state, real_series_name, cfg, opt

# ==================== 数据保存 ====================
def save_records(series_id, series_name, manufacturer, brand_name, records, spec_state, cfg_raw=None, opt_raw=None):
    conn = psycopg2.connect(**DB)
    cur = None
    try:
        conn.autocommit = True
        cur = conn.cursor()
        found = len(records); new = 0; updated = 0

        INT_FIELDS = {'lidar_count', 'lidar_lines', 'mmwave_radar_count', 'ultrasonic_radar_count',
                      'camera_count', 'in_cabin_camera_count', 'motor_ps', 'max_speed_kmh',
                      'curb_weight_kg', 'wheelbase_mm'}

        def clean_val(field, val):
            if not val or val in ('-', ''): return val
            if field in INT_FIELDS:
                m = re.search(r'(\d+)', str(val))
                return m.group(1) if m else None
            if field in ('guide_price', 'max_power_kw', 'max_torque_nm', 'acceleration_0_100',
                         'battery_capacity_kwh', 'energy_consumption', 'wltc_fuel_consumption',
                         'oil_electric_consumption', 'chip_tops'):
                m = re.search(r'([\d.]+)', str(val))
                return m.group(1) if m else None
            if field in ('cltc_range_km', 'wltc_range_km'):
                m = re.search(r'(\d+)', str(val))
                return m.group(1) if m else None
            return val

        for r in records:
            sid = r['spec_id']; sname = r.get('spec_name', '')
            sale_status = spec_state or '在售'
            mapped = {}
            for k, v in r.items():
                if k == 'spec_id' or k == 'spec_name': continue
                target = FIELD_MAP.get(k, k)
                if target is not None: mapped[target] = clean_val(target, v)

            has_adas = False
            for cf in ['adas_level', 'adas_system', 'lane_centering', 'auto_park', 'lane_change_assist', 'active_brake']:
                val = mapped.get(cf, '')
                # val 为 '○' 表示"选配"，仍算"有智驾"
                if val and val not in ('', '-', '0', 'L0'):
                    has_adas = True
                    break

            cur.execute("SELECT id FROM data_peizhibiao WHERE series_id=%s AND spec_id=%s", (series_id, sid))
            existing = cur.fetchone()

            if existing:
                update_sets = []; update_vals = []
                for f, v in mapped.items():
                    if f in ('series_id', 'spec_id'): continue
                    update_sets.append(f'"{f}"=%s'); update_vals.append(v)
                if update_sets:
                    update_vals.extend([has_adas, sale_status, datetime.now(), series_id, sid])
                    cur.execute(f'''UPDATE data_peizhibiao SET {",".join(update_sets)},
                        has_adas=%s, sale_status=%s, updated_at=%s
                        WHERE series_id=%s AND spec_id=%s''', update_vals)
                    updated += 1
            else:
                cols = ['series_id', 'spec_id', 'series_name', 'spec_name', 'manufacturer', 'brand_name',
                        'has_adas', 'sale_status', 'scraped_at', 'created_at', 'updated_at']
                vals = [series_id, sid, series_name, sname, manufacturer, brand_name,
                        has_adas, sale_status, datetime.now(), datetime.now(), datetime.now()]
                for f, v in mapped.items():
                    cols.append(f'"{f}"'); vals.append(v)
                # 保存原始 JSON（便于后续回溯和重新解析）
                if cfg_raw is not None:
                    cols.append('config_raw')
                    vals.append(json.dumps(cfg_raw.get('result', {}), ensure_ascii=False))
                if opt_raw is not None:
                    cols.append('option_raw')
                    vals.append(json.dumps(opt_raw.get('result', {}), ensure_ascii=False))
                ph = ','.join(['%s'] * len(vals))
                cur.execute(f'''INSERT INTO data_peizhibiao ({",".join(cols)})
                    VALUES ({ph}) ON CONFLICT (spec_id) DO NOTHING''', vals)
                new += 1

        # 更新款型ID缓存
        all_spec_ids = [r['spec_id'] for r in records]
        if all_spec_ids:
            cur.execute("""
                INSERT INTO series_spec_cache (series_id, spec_ids, total_specs)
                VALUES (%s, %s, %s)
                ON CONFLICT (series_id) DO UPDATE SET
                    spec_ids = EXCLUDED.spec_ids,
                    total_specs = EXCLUDED.total_specs,
                    last_seen = NOW()
            """, (series_id, all_spec_ids, len(all_spec_ids)))

        return found, new, updated
    finally:
        if cur: cur.close()
        if conn: conn.close()

def mark_progress(series_id, status, found=0, new=0, error_msg=None):
    conn = psycopg2.connect(**DB)
    cur = None
    try:
        conn.autocommit = True
        cur = conn.cursor()
        if status == 'done':
            cur.execute("""INSERT INTO scrape_progress_v2 (series_id, status, spec_count_found, spec_count_new, scraped_at)
                VALUES (%s, 'done', %s, %s, NOW())
                ON CONFLICT (series_id) DO UPDATE SET
                    status='done', spec_count_found=%s, spec_count_new=%s, scraped_at=NOW(), updated_at=NOW()""",
                (series_id, found, new, found, new))
        elif status == 'error':
            cur.execute("""INSERT INTO scrape_progress_v2 (series_id, status, error_count, last_error, updated_at)
                VALUES (%s, 'error', 1, %s, NOW())
                ON CONFLICT (series_id) DO UPDATE SET
                    status='error', error_count=scrape_progress_v2.error_count+1, last_error=%s, updated_at=NOW()""",
                (series_id, error_msg, error_msg))
    finally:
        if cur: cur.close()
        if conn: conn.close()

# ==================== 并发爬取 ====================
_delay_lock = threading.Lock()
_last_request_time = 0

def wait_delay(has_data=True, delay_range=None):
    """请求前随机延迟，避免频率过高。
    delay_range 为空时自动按 has_data 选择间隔，非空时（如 skip）直接使用传入值"""
    global _last_request_time
    if delay_range is None:
        delay_range = ANTI_CRAWL['delay_with_data'] if has_data else ANTI_CRAWL['delay_empty']
    target_delay = random.uniform(*delay_range)
    with _delay_lock:
        elapsed = time.time() - _last_request_time
        if elapsed < target_delay:
            time.sleep(target_delay - elapsed)
        _last_request_time = time.time()

def crawl_one(args):
    """爬取单个车系，返回 (sid, sname, result_dict)"""
    sid, sname, mfr, brand = args
    try:
        wait_delay(has_data=True)
        recs, spec_state, real_name, cfg, opt = scrape(sid)
        # 全部款型已存在 → 快速跳过
        if recs is None:
            log.info(f'→ {sname} ({sid}): 全部款型已在库，跳过')
            wait_delay(delay_range=ANTI_CRAWL['delay_skip'])
            mark_progress(sid, 'done', 0, 0)
            return (sid, sname, {'done': True, 'found': 0, 'new': 0, 'updated': 0, 'has_data': False, 'state': 'skipped'})
        is_match, verify_msg = verify_series_mapping(sid, sname, real_name)
        if not is_match:
            log.warning(f'映射验证: {verify_msg}（数据仍保存）')
        
        has_data = len(recs) > 0
        f, n, u = save_records(sid, sname, mfr, brand, recs, spec_state, cfg, opt)
        mark_progress(sid, 'done', f, n)
        return (sid, sname, {'done': True, 'found': f, 'new': n, 'updated': u, 'has_data': has_data, 'state': spec_state})
    except Exception as e:
        err_msg = str(e)[:100]
        mark_progress(sid, 'error', error_msg=err_msg)
        return (sid, sname, {'error': err_msg, 'has_data': False})

# ==================== 主循环 ====================
def run_scraper():
    conn = psycopg2.connect(**DB); cur = conn.cursor()
    batch_size = random.randint(*ANTI_CRAWL['batch_size'])
    cur.execute(f"""
        SELECT b.series_id, b.series_name, COALESCE(b.manufacturer, b.brand_name, ''), COALESCE(b.brand_name, '')
        FROM brand_series_v2 b
        LEFT JOIN scrape_progress_v2 p ON b.series_id = p.series_id
        WHERE p.series_id IS NULL OR p.status IN ('pending', 'error')
        ORDER BY RANDOM()
        LIMIT {batch_size}
    """)
    tasks = cur.fetchall()
    cur.close(); conn.close()

    if not tasks: return 0

    start_time = time.time()
    log.info(f'v7 本轮 {len(tasks)} 个车系 | {ANTI_CRAWL["workers"]}线程并发')

    done = 0; fail = 0; total_new = 0; total_updated = 0
    total_found = 0; empty_count = 0
    consecutive_errors = 0; total_errors = 0

    with ThreadPoolExecutor(max_workers=ANTI_CRAWL['workers']) as executor:
        futures = {}
        for i, task in enumerate(tasks):
            # 错误升级
            if consecutive_errors >= ANTI_CRAWL['max_consecutive_errors']:
                sleep_min = ANTI_CRAWL['error_sleep_range'][0] / 60
                log.warning(f'连续 {consecutive_errors} 次错误，休眠 {sleep_min:.0f} 分钟')
                time.sleep(random.uniform(*ANTI_CRAWL['error_sleep_range']))
                consecutive_errors = 0
            if total_errors >= ANTI_CRAWL['max_total_errors']:
                log.error(f'累计 {total_errors} 次错误，停止')
                break

            # 提交任务到线程池
            future = executor.submit(crawl_one, task)
            futures[future] = (i, task)

        # 收集结果
        for future in as_completed(futures):
            i, (sid, sname, mfr, brand) = futures[future]
            try:
                sid, sname, result = future.result()
                if 'error' in result:
                    fail += 1; consecutive_errors += 1; total_errors += 1
                    log.warning(f'[{i+1}/{len(tasks)}] ✗ {sname} ({sid}): {result["error"]}')
                else:
                    done += 1; total_new += result['new']; total_updated += result['updated']
                    total_found += result['found']
                    consecutive_errors = 0
                    if result['has_data']:
                        log.info(f'[{i+1}/{len(tasks)}] ✓ {sname} ({sid}): {result["found"]}款(新{result["new"]}/更{result["updated"]}) {result["state"]}')
                    else:
                        empty_count += 1
                        log.info(f'[{i+1}/{len(tasks)}] ○ {sname} ({sid}): 0款')
            except Exception as e:
                fail += 1; consecutive_errors += 1; total_errors += 1
                log.warning(f'[{i+1}/{len(tasks)}] ✗ {sname} ({sid}) future异常: {e}')

    elapsed = (time.time() - start_time) / 60
    log.info(f'本轮完成: {done}成功/{fail}失败 | {total_found}款(新{total_new}/更{total_updated}) | 空{empty_count}个 | 耗时{elapsed:.1f}分钟')

    # 根据空车系比例调整批次休眠
    total_processed = done + fail
    if total_processed > 0:
        empty_ratio = empty_count / max(total_processed, 1)
        if empty_ratio >= ANTI_CRAWL['empty_ratio_threshold']:
            sleep_range = ANTI_CRAWL['delay_batch_empty']
            log.info(f'空车系比例 {empty_ratio:.0%}，缩短休眠')
        else:
            sleep_range = ANTI_CRAWL['delay_batch_done']
        sleep_sec = random.uniform(*sleep_range)
        log.info(f'批次休眠 {sleep_sec/60:.1f} 分钟...')
        time.sleep(sleep_sec)

    return done

# ==================== 入口 ====================
if __name__ == '__main__':
    log.info('=== 汽车之家配置爬虫 v7 启动 ===')
    log.info(f'优化: 空车系短延迟 | 无长休眠 | 批次休眠2-5min | {ANTI_CRAWL["workers"]}线程并发 | 连接复用')
    # 先同步品牌/厂商/车系关系表（去重增量）
    from crawl_brand_series import crawl_and_sync
    crawl_and_sync()

    while True:
        n = run_scraper()
        if n == 0:
            log.info('无待爬取任务，60秒后重试...')
            time.sleep(60)