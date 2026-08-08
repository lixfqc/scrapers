#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工信部新车公告数据自动爬取定时任务
功能：自动检测新批次 → 爬取数据 → 存入数据库
"""

import requests
import json
import time
import os
import sys
import re
import pandas as pd
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import psycopg2
from psycopg2.extras import execute_batch
import io
import urllib3

# 关闭SSL证书验证警告（工信部网站SSL存在兼容性问题）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Windows 编码兼容
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ============ 配置 ============
BASE_URL = "https://www.miit.gov.cn"
LIST_API = "/api-gateway/jpaas-publish-server/front/page/build/unit"

# 工信部 xcpgs 系列的 jpaas API 配置（2026年最新有效参数）
WEB_ID = "b3eba6883f9240e2b51025f690afbae8"       # xcpgs 系列 webId
TPLSET_ID = "9a9a7b87a4444169bdef99ff1f84e1aa"     # xcpgs 系列 tplSetId

# 已知批次路径（从工信部网站发现，路径含随机后缀）
# 格式：批次号 -> (路径后缀, ColId/pageId)
KNOWN_BATCH_PATHS = {
    390: ("xcpgs390ssew", "7aa01c413a514c5fadc673bb660baca9"),
    391: ("xcpgs391sqwimf", "518bf6b699e8410b96d5f58ad36548b8"),
    392: ("xcpgs392n2ssssss", "0103ff165e5f4bf09300fa6452a98caf"),
    393: ("xcpgs393sdwwe", "93fa22a2437146d38054887d6e619fdf"),
    394: ("xcpgs39441wsd", "bd298a5e586f415e8bfc00d3712c81d3"),
    395: ("xcpgs395sfwe85", "f90f45c07d0548e99f8ba203d70b8fd1"),
    396: ("xcpgs396dwoirw", "0ab3f5253cd745fda8b47db94a64b45d"),
    397: ("xcpgs397", "cc2b6416fa824af0b15f7562cbc3b9bf", "dljdclscqyjcpgg054894"),  # 特殊路径
    398: ("xcpgs398suedusi", "163c6dfe50d14e8baa703e3c0ed3dc1c"),
    399: ("xcpgs399uweuigwrds", "3861cdf262ba4ef2a9c216668786b76c"),
    400: ("xcpgs400wegwew", "4d3bb87ed9a843f1a74dbe468b24a74a"),
    401: ("xcpgs401wewedsf", "6d3fc770bca84a35b01338f3e3793c92"),
    402: ("xcpgs402sduwe2e", "2df7cc934e3b4c1eb0567c4dc7f65578"),
    404: ("xcpgs404wdsdww", "48219b1d73d34f4793b12878f6c92f4e"),
    405: ("xcpgs405dwe2rw", "e4ab78c1e9c6454e8969ee6e7960b749"),
}
XCPGS_BASE_PATH = "/datainfo/dljdclscqyjcpgg"

# 数据库配置
DB_CONFIG = {
    "host": "pgm-bp1sf8zujdx18698io.pg.rds.aliyuncs.com",
    "port": 5432,
    "user": "Levin001",
    "password": "Li800124",
    "dbname": "gonggao"
}

# 输出目录
OUTPUT_DIR = r"D:\公众号文章素材\工信部公告数据"

# 批次参数文件（持久化发现的批次路径）
BATCH_PARAMS_FILE = os.path.join(OUTPUT_DIR, "batch_params.json")

# 日志锁
print_lock = threading.Lock()


# ============ 批次参数持久化 ============
def load_cached_batches():
    """从缓存文件加载已发现的批次路径"""
    cached_batches = {}
    try:
        if os.path.exists(BATCH_PARAMS_FILE):
            with open(BATCH_PARAMS_FILE, 'r', encoding='utf-8') as f:
                cached_batches = json.load(f)
            log(f"从缓存加载了 {len(cached_batches)} 个批次路径")
    except Exception as e:
        log(f"加载缓存文件失败: {e}")
    return cached_batches


def save_cached_batches(cached_batches):
    """保存发现的批次路径到缓存"""
    try:
        os.makedirs(os.path.dirname(BATCH_PARAMS_FILE), exist_ok=True)
        with open(BATCH_PARAMS_FILE, 'w', encoding='utf-8') as f:
            json.dump(cached_batches, f, ensure_ascii=False, indent=2)
        log(f"已保存 {len(cached_batches)} 个批次路径到缓存")
    except Exception as e:
        log(f"保存缓存文件失败: {e}")


def search_batch_by_bing(batch_num):
    """通过Bing搜索发现批次路径"""
    try:
        import urllib.parse
        query = f'site:miit.gov.cn dljdclscqyjcpgg xcpgs{batch_num}'
        bing_url = f'https://cn.bing.com/search?q={urllib.parse.quote(query)}&count=5'
        
        r = requests.get(bing_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, timeout=10, verify=False)
        r.encoding = 'utf-8'
        
        # 提取路径
        paths = re.findall(
            r'miit\.gov\.cn(/datainfo/[^\s"\'<>&]*xcpgs' + str(batch_num) + r'[^\s"\'<>&]*)',
            r.text
        )
        
        if paths:
            xcpgs_path = paths[0].rstrip('/')
            # 访问路径获取 ColId
            full_url = BASE_URL + xcpgs_path + '/'
            r2 = requests.get(full_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }, timeout=10, verify=False)
            
            if r2.status_code == 200:
                # 尝试多种方式提取 pageId/ColId
                m = re.search(r'<meta name="ColId" content="([^"]+)"', r2.text)
                if not m:
                    m = re.search(r'pageId["\s]*[=:]["\s]*["\x27]([a-f0-9]{32})["\x27]', r2.text)
                
                if m:
                    col_id = m.group(1)
                    return {
                        'batch': batch_num,
                        'pageId': col_id,
                        'xcpgs_url': full_url,
                        'webId': WEB_ID,
                        'tplSetId': TPLSET_ID,
                    }
    except Exception as e:
        log(f"  Bing搜索第{batch_num}批失败: {e}")
    
    return None


def search_batch_by_baidu(batch_num):
    """通过百度搜索发现批次路径（补充Bing）"""
    try:
        import urllib.parse
        query = f'工信部 dljdclscqyjcpgg xcpgs{batch_num}'
        baidu_url = f'https://www.baidu.com/s?wd={urllib.parse.quote(query)}&rn=5'
        
        r = requests.get(baidu_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, timeout=10, verify=False)
        r.encoding = 'utf-8'
        
        # 提取路径
        paths = re.findall(
            r'miit\.gov\.cn(/datainfo/[^\s"\'<>&]*xcpgs' + str(batch_num) + r'[^\s"\'<>&]*)',
            r.text
        )
        
        if paths:
            xcpgs_path = paths[0].rstrip('/')
            # 访问路径获取 ColId
            full_url = BASE_URL + xcpgs_path + '/'
            r2 = requests.get(full_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }, timeout=10, verify=False)
            
            if r2.status_code == 200:
                m = re.search(r'<meta name="ColId" content="([^"]+)"', r2.text)
                if not m:
                    m = re.search(r'pageId["\s]*[=:]["\s]*["\x27]([a-f0-9]{32})["\x27]', r2.text)
                
                if m:
                    col_id = m.group(1)
                    return {
                        'batch': batch_num,
                        'pageId': col_id,
                        'xcpgs_url': full_url,
                        'webId': WEB_ID,
                        'tplSetId': TPLSET_ID,
                    }
    except Exception as e:
        log(f"  百度搜索第{batch_num}批失败: {e}")
    
    return None


def log(msg):
    """线程安全日志"""
    with print_lock:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {msg}", flush=True)


# ============ 数据库操作 ============
def get_db_connection():
    """获取数据库连接"""
    return psycopg2.connect(**DB_CONFIG)


def check_batch_exists(batch_num):
    """检查批次是否已存在于数据库"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM vehicle_product_publicity WHERE batch = %s",
            (f'第{batch_num}批',)
        )
        count = cursor.fetchone()[0]
        return count > 0
    finally:
        cursor.close()
        conn.close()


def get_latest_batch_in_db():
    """获取数据库中最新批次号"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT MAX(CAST(REPLACE(batch, '第', '') AS INTEGER)) 
            FROM vehicle_product_publicity 
            WHERE batch ~ '^第[0-9]+批$'
        """)
        result = cursor.fetchone()[0]
        return result if result else 0
    except:
        return 0
    finally:
        cursor.close()
        conn.close()


# ============ 批次发现 ============
def get_xcpgs_page_id(batch_num):
    """通过访问 xcpgsXXX 页面获取 ColId（即 pageId）"""
    batch_info = KNOWN_BATCH_PATHS.get(batch_num)
    if not batch_info:
        return None, None
    
    # 支持特殊路径格式（如第397批）
    if len(batch_info) == 3:
        path_suffix, col_id, parent_dir = batch_info
        xcpgs_url = f"{BASE_URL}/datainfo/{parent_dir}/{path_suffix}/"
    else:
        path_suffix, col_id = batch_info[0], batch_info[1]
        xcpgs_url = f"{BASE_URL}{XCPGS_BASE_PATH}/{path_suffix}/"
    
    # 如果已知 ColId，直接返回
    if col_id:
        return col_id, xcpgs_url
    
    # 访问页面提取 ColId
    try:
        r = requests.get(xcpgs_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': BASE_URL + '/datainfo/cpgg/'
        }, timeout=15, verify=False)
        
        if r.status_code == 200:
            # 从 meta 标签提取 ColId
            m = re.search(r'<meta name="ColId" content="([^"]+)"', r.text)
            if m:
                return m.group(1), xcpgs_url
            
            # 从 script queryData 提取 pageId
            m2 = re.search(r'pageId["\s]*[=:]["\s]*["\x27]([a-f0-9]{32})["\x27]', r.text)
            if m2:
                return m2.group(1), xcpgs_url
    except Exception as e:
        log(f"  获取第{batch_num}批 ColId 出错: {e}")
    
    return None, xcpgs_url


def discover_new_batches_v2(latest_db_batch):
    """发现新的公告批次（新版：基于已知路径直接访问）"""
    log("=== 开始发现新批次（新版机制）===")
    
    new_batches = {}
    
    # 策略1：检查已知路径中是否有新批次未入库
    for batch_num, batch_info in sorted(KNOWN_BATCH_PATHS.items()):
        if batch_num <= latest_db_batch:
            continue
        
        col_id, xcpgs_url = get_xcpgs_page_id(batch_num)
        if col_id and xcpgs_url:
            new_batches[batch_num] = {
                'batch': batch_num,
                'pageId': col_id,
                'xcpgs_url': xcpgs_url,
                'webId': WEB_ID,
                'tplSetId': TPLSET_ID,
            }
            log(f"  ✓ 第{batch_num}批可访问: pageId={col_id}")
        else:
            log(f"  第{batch_num}批路径不可访问")
    
    # 策略2：尝试通过 Bing 搜索发现更新批次路径
    # 仅当没有通过已知路径发现新批次时触发
    if not new_batches:
        log("  尝试通过搜索引擎发现新批次路径...")
        try:
            import urllib.parse
            # 搜索可能的新批次
            search_batches = list(range(latest_db_batch + 1, latest_db_batch + 10))
            for batch_num in search_batches[:3]:  # 只搜索最近3批
                query = f'site:miit.gov.cn dljdclscqyjcpgg xcpgs{batch_num}'
                bing_url = f'https://cn.bing.com/search?q={urllib.parse.quote(query)}&count=5'
                r = requests.get(bing_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }, timeout=10, verify=False)
                r.encoding = 'utf-8'
                
                paths = re.findall(
                    r'miit\.gov\.cn(/datainfo/[^\s"\'<>&]*xcpgs' + str(batch_num) + r'[^\s"\'<>&]*)',
                    r.text
                )
                if paths:
                    xcpgs_path = paths[0].rstrip('/')
                    # 访问路径获取 ColId
                    full_url = BASE_URL + xcpgs_path + '/'
                    r2 = requests.get(full_url, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }, timeout=10, verify=False)
                    if r2.status_code == 200:
                        m = re.search(r'<meta name="ColId" content="([^"]+)"', r2.text)
                        if m:
                            col_id = m.group(1)
                            new_batches[batch_num] = {
                                'batch': batch_num,
                                'pageId': col_id,
                                'xcpgs_url': full_url,
                                'webId': WEB_ID,
                                'tplSetId': TPLSET_ID,
                            }
                            log(f"  ✓ 搜索发现第{batch_num}批: {xcpgs_path}")
                time.sleep(0.5)
        except Exception as e:
            log(f"  搜索引擎发现失败: {e}")
    
    log(f"共发现 {len(new_batches)} 个待处理批次")
    return new_batches


def discover_new_batches(start_batch=390, end_batch=450):
    """发现新的公告批次（兼容旧接口，已失效的API方式 + 新方式）"""
    log("=== 开始发现新批次 ===")
    
    new_batches = {}
    
    # 旧方式：通过 cpgg 列表页 API（已于2026年初失效，保留用于记录）
    # 新方式：直接通过已知路径访问
    
    # 策略：对所有已知路径（start_batch ~ end_batch范围内）进行扫描
    for batch_num, batch_info in sorted(KNOWN_BATCH_PATHS.items()):
        if batch_num < start_batch or batch_num > end_batch:
            continue
        
        if len(batch_info) == 3:
            path_suffix, col_id, parent_dir = batch_info
            xcpgs_url = f"{BASE_URL}/datainfo/{parent_dir}/{path_suffix}/"
        else:
            path_suffix, col_id = batch_info[0], batch_info[1]
            xcpgs_url = f"{BASE_URL}{XCPGS_BASE_PATH}/{path_suffix}/"
        
        # 如果 ColId 未知，尝试访问获取
        if not col_id:
            try:
                r = requests.get(xcpgs_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': BASE_URL + '/datainfo/cpgg/'
                }, timeout=15, verify=False)
                if r.status_code == 200:
                    m = re.search(r'<meta name="ColId" content="([^"]+)"', r.text)
                    if m:
                        col_id = m.group(1)
            except Exception as e:
                log(f"  访问第{batch_num}批路径出错: {e}")
        
        if col_id:
            full_article_url = xcpgs_url  # 用 xcpgs 路径作为"文章URL"
            new_batches[batch_num] = full_article_url
            log(f"发现第{batch_num}批: {xcpgs_url}")
        else:
            log(f"第{batch_num}批路径不可访问或 ColId 未知")
        
        time.sleep(0.2)
    
    log(f"共发现 {len(new_batches)} 个批次")
    return new_batches


def get_batch_params(batch_num, article_url):
    """获取批次的爬取参数（基于新版 xcpgsXXX 直接访问机制）"""
    try:
        batch_info = KNOWN_BATCH_PATHS.get(batch_num)
        
        # 先检查已知 ColId
        col_id = None
        if batch_info:
            col_id = batch_info[1] if len(batch_info) >= 2 else None
        
        # 如果没有已知 ColId，从 URL 访问获取
        if not col_id:
            r = requests.get(article_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': BASE_URL + '/datainfo/cpgg/'
            }, timeout=15, verify=False)
            r.encoding = 'utf-8'
            
            if r.status_code == 200:
                m = re.search(r'<meta name="ColId" content="([^"]+)"', r.text)
                if m:
                    col_id = m.group(1)
                else:
                    # 尝试从 script queryData 提取
                    m2 = re.search(r'pageId["\s]*[=:]["\s]*["\x27]([a-f0-9]{32})["\x27]', r.text)
                    if m2:
                        col_id = m2.group(1)
        
        if not col_id:
            log(f"  无法获取第{batch_num}批的 ColId")
            return None
        
        # 确定 xcpgs 路径
        if batch_info and len(batch_info) == 3:
            path_suffix, _, parent_dir = batch_info
            xcpgs_path = f"/datainfo/{parent_dir}/{path_suffix}"
        elif batch_info:
            path_suffix = batch_info[0]
            xcpgs_path = f"{XCPGS_BASE_PATH}/{path_suffix}"
        else:
            # 从 URL 推断路径
            m_path = re.search(r'(/datainfo[^/]+/xcpgs\d+[^/]*)', article_url)
            xcpgs_path = m_path.group(1) if m_path else f"{XCPGS_BASE_PATH}/xcpgs{batch_num}"
        
        return {
            'batch': batch_num,
            'iframe_path': xcpgs_path,
            'iframe_prefix': f'{batch_num}',
            'webId': WEB_ID,
            'pageId': col_id,
            'tplSetId': TPLSET_ID,
            'article_url': article_url
        }
        
    except Exception as e:
        log(f"  获取第{batch_num}批参数出错: {e}")
    
    return None


# ============ 数据爬取 ============
def get_list_page(batch_params, page_no, page_size=100):
    """获取列表页"""
    param_json = json.dumps({
        "pageNo": page_no,
        "pageSize": page_size,
        "loadEnabled": True,
        "search": json.dumps({
            "title": "",
            "PICI": str(batch_params['batch']),
            "QYMC": "",
            "CPSB": "",
            "CPMC": "",
            "CPXH": ""
        })
    })
    
    params = {
        'parseType': 'buildstatic',
        'webId': batch_params['webId'],
        'tplSetId': batch_params['tplSetId'],
        'pageType': 'column',
        'tagId': '信息列表',
        'editType': 'null',
        'pageId': batch_params['pageId'],
        'paramJson': param_json,
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': f'https://www.miit.gov.cn{batch_params["iframe_path"]}',
        'Accept': 'application/json, text/javascript, */*; q=0.01'
    }
    
    for attempt in range(3):
        try:
            r = requests.get(BASE_URL + LIST_API, headers=headers, params=params, timeout=30, verify=False)
            data = r.json()
            if data.get('success'):
                return data['data']['html']
        except Exception as e:
            log(f"  Page {page_no} attempt {attempt+1} failed: {e}")
            time.sleep(2)
    return None


def parse_list_html(html):
    """解析列表HTML"""
    soup = BeautifulSoup(html, 'html.parser')
    
    total = 0
    for div in soup.find_all(attrs={"id": True}):
        if 'pagination' in div.get('id', ''):
            qd = div.get('querydata', div.get('queryData', '{}')).replace("'", '"')
            try:
                qd_data = json.loads(qd)
                total = int(qd_data.get('count', 0))
            except:
                pass
    
    urls = []
    seen = set()
    table = soup.find('table')
    if table:
        for tr in table.find_all('tr')[1:]:
            link = tr.find('a', href=True)
            if link:
                href = link['href']
                if href not in seen and '/art/' in href:
                    seen.add(href)
                    urls.append(href)
    
    return urls, total


def get_product_detail(path, batch_params):
    """获取产品详情"""
    url = BASE_URL + path
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': f'https://www.miit.gov.cn{batch_params["iframe_path"]}'
    }
    
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=30, verify=False)
            r.encoding = 'utf-8'
            return parse_detail_html(r.text, url)
        except:
            if attempt < 2:
                time.sleep(1)
    return None


def parse_table_by_header(table, header_keywords):
    """从表格提取数据"""
    rows = table.find_all('tr')
    if len(rows) < 2:
        return {}
    
    headers = [c.get_text(strip=True) for c in rows[0].find_all(['th', 'td'])]
    if not any(kw in headers for kw in header_keywords):
        return {}
    
    result = {}
    data_rows = [r for r in rows[1:] if any(c.get_text(strip=True) for c in r.find_all(['th','td']))]
    
    if len(data_rows) == 1:
        values = [c.get_text(strip=True) for c in data_rows[0].find_all(['th', 'td'])]
        for h, v in zip(headers, values):
            if h:
                result[h] = v
    else:
        col_values = {h: [] for h in headers if h}
        for row in data_rows:
            vals = [c.get_text(strip=True) for c in row.find_all(['th', 'td'])]
            for h, v in zip(headers, vals):
                if h:
                    col_values[h].append(v)
        for h, vlist in col_values.items():
            result[h] = '; '.join(v for v in vlist if v)
    
    return result


def parse_detail_html(html, url=""):
    """解析详情页HTML"""
    soup = BeautifulSoup(html, 'html.parser')
    record = {'_url': url}
    
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    
    # 提取底盘和发动机信息
    for table in soup.find_all('table'):
        chassis = parse_table_by_header(table, ['底盘ID', '底盘型号', '底盘生产企业'])
        if chassis:
            for k, v in chassis.items():
                col_name = f'底盘_{k}' if k not in ('是否同期申报',) else k
                record[col_name] = v
        
        engine = parse_table_by_header(table, ['发动机型号', '发动机企业'])
        if engine:
            for k, v in engine.items():
                col_name = f'发动机_{k}' if k not in ('油耗(L/100km)',) else k
                record[col_name] = v
    
    # 提取文本字段
    body_text = soup.get_text('|', strip=True)
    parts = [p.strip() for p in body_text.split('|') if p.strip()]
    stop_keywords = ['意见反馈', '不得发表', '留言', '详细信息', '取消']
    
    i = 0
    while i < len(parts):
        part = parts[i]
        if any(s in part for s in stop_keywords):
            break
        if part.endswith('：') and 2 <= len(part) <= 30:
            key = part.rstrip('：').strip()
            if i + 1 < len(parts):
                next_part = parts[i + 1]
                if next_part.endswith('：') and 2 <= len(next_part) <= 30:
                    record[key] = ''
                else:
                    if not any(s in next_part for s in stop_keywords):
                        record[key] = next_part
                        i += 2
                        continue
                    else:
                        record[key] = ''
            else:
                record[key] = ''
        i += 1
    
    return record


def scrape_batch(batch_params):
    """爬取单个批次"""
    batch_num = batch_params['batch']
    log(f"\n{'='*60}")
    log(f"开始爬取第{batch_num}批")
    log(f"{'='*60}")
    
    # 获取所有URL
    log("[Step 1] 获取产品列表...")
    html = get_list_page(batch_params, 1, 100)
    if not html:
        log("ERROR: 无法获取列表页")
        return None
    
    urls, total = parse_list_html(html)
    log(f"总产品数: {total}, 第1页: {len(urls)} 条")
    
    total_pages = (total + 100 - 1) // 100
    all_urls = list(urls)
    
    for page in range(2, total_pages + 1):
        log(f"  获取第{page}/{total_pages}页...")
        html = get_list_page(batch_params, page, 100)
        if html:
            page_urls, _ = parse_list_html(html)
            all_urls.extend(page_urls)
        time.sleep(0.2)
    
    all_urls = list(dict.fromkeys(all_urls))
    log(f"列表完成: {len(all_urls)} 个唯一URL")
    
    # 获取详情
    log(f"[Step 2] 获取详情页 ({len(all_urls)} 条)...")
    results = [None] * len(all_urls)
    done_count = [0]
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_idx = {
            executor.submit(get_product_detail, url, batch_params): i 
            for i, url in enumerate(all_urls)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            done_count[0] += 1
            try:
                data = future.result()
                if data:
                    results[idx] = data
            except:
                pass
            
            if done_count[0] % 100 == 0 or done_count[0] == len(all_urls):
                log(f"  进度: {done_count[0]}/{len(all_urls)} ({done_count[0]*100//len(all_urls)}%)")
    
    records = [r for r in results if r is not None]
    log(f"成功获取 {len(records)} 条记录")
    
    return records


def build_dataframe(records):
    """构建DataFrame"""
    priority_fields = [
        '产品商标', '产品型号', '产品名称', '企业名称',
        '注册地址', '目录序号', '生产地址',
        '外形尺寸(mm)', '货箱栏板内尺寸(mm)', '排放依据标准',
        '燃料种类', '最高车速(km/h)', '总质量(kg)',
        '整备质量(kg)', '轴距(mm)', '轮胎规格',
        '额定载客（含驾驶员）（座位数）', '驾驶室准乘人数（人）',
        '防抱死制动系统', '车辆识别代号（VIN）',
        '前悬/后悬(mm)', '轮距（前/后)mm',
        '接近角/离去角（度）', '其它',
        '是否同期申报', '底盘_底盘ID', '底盘_底盘型号', '底盘_底盘生产企业', '底盘_底盘类别',
        '发动机_发动机型号', '发动机_发动机企业', '发动机_排量(ml)', '发动机_功率(kw)', '油耗(L/100km)',
    ]
    
    field_count = {}
    for rec in records:
        for k in rec:
            if not k.startswith('_'):
                field_count[k] = field_count.get(k, 0) + 1
    
    all_cols = list(priority_fields)
    for f in sorted(field_count.keys(), key=lambda x: -field_count[x]):
        if f not in all_cols:
            all_cols.append(f)
    
    df = pd.DataFrame(records)
    cols_available = [c for c in all_cols if c in df.columns]
    extra_cols = [c for c in df.columns if c not in cols_available and not c.startswith('_')]
    final_cols = cols_available + extra_cols
    if '_url' in df.columns:
        final_cols.append('_url')
    
    df = df[final_cols]
    df = df.rename(columns={'_url': '详情链接'})
    
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].fillna('').astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()
            df[col] = df[col].replace('nan', '')
    
    return df


def save_excel(df, batch_num):
    """保存Excel"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f'第{batch_num}批产品公示.xlsx')
    
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='产品公示')
        ws = writer.sheets['产品公示']
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                try:
                    cell_len = len(str(cell.value)) if cell.value else 0
                    max_len = max(max_len, cell_len)
                except:
                    pass
            ws.column_dimensions[col_letter].width = min(max_len + 2, 50)
    
    log(f"Excel已保存: {path}")
    return path


# ============ 数据库上传 ============
COLUMN_MAPPING = {
    '产品商标': 'product_trademark',
    '产品型号': 'product_model',
    '产品名称': 'product_name',
    '企业名称': 'enterprise_name',
    '注册地址': 'registered_address',
    '目录序号': 'catalog_number',
    '生产地址': 'production_address',
    '外形尺寸(mm)': 'overall_dimensions',
    '货箱栏板内尺寸(mm)': 'cargo_box_dimensions',
    '排放依据标准': 'emission_standard',
    '燃料种类': 'fuel_type',
    '最高车速(km/h)': 'max_speed',
    '总质量(kg)': 'total_mass',
    '整备质量(kg)': 'curb_weight',
    '轴距(mm)': 'wheelbase',
    '轮胎规格': 'tire_specification',
    '额定载客（含驾驶员）（座位数）': 'seating_capacity',
    '驾驶室准乘人数（人）': 'cab_capacity',
    '防抱死制动系统': 'abs_system',
    '车辆识别代号（VIN）': 'vin_pattern',
    '前悬/后悬(mm)': 'front_rear_overhang',
    '轮距（前/后)mm': 'front_rear_track',
    '接近角/离去角（度）': 'approach_departure_angle',
    '其它': 'other_info',
    '是否同期申报': 'simultaneous_declaration',
    '底盘_底盘ID': 'chassis_id',
    '底盘_底盘型号': 'chassis_model',
    '底盘_底盘生产企业': 'chassis_manufacturer',
    '底盘_底盘类别': 'chassis_category',
    '发动机_发动机型号': 'engine_model',
    '发动机_发动机企业': 'engine_manufacturer',
    '发动机_排量(ml)': 'engine_displacement',
    '发动机_功率(kw)': 'engine_power',
    '油耗(L/100km)': 'fuel_consumption',
    '载质量利用系数': 'load_utilization_coefficient',
    '额定载质量(kg)': 'rated_load',
    '转向型式': 'steering_type',
    '轴数': 'axle_count',
    '准拖挂车总质量(kg)': 'max_towing_mass',
    '钢板弹簧片数（前/后）': 'leaf_spring_count',
    '半挂车鞍座最大允许承载质量(kg)': 'fifth_wheel_load',
    '轮胎数': 'tire_count',
    '反光标识生产企业': 'reflective_material_mfg',
    '反光标识型号': 'reflective_material_model',
    '反光标识商标': 'reflective_material_trademark',
    '说明': 'remarks',
    '油耗申报值(L/100km)': 'declared_fuel_consumption',
    '详情链接': 'detail_link',
}


def upload_to_database(df, batch_num):
    """上传数据到数据库"""
    log(f"[Step 3] 上传数据到数据库...")
    
    batch = f'第{batch_num}批'
    records = []
    
    for _, row in df.iterrows():
        record = {'batch': batch}
        
        for excel_col, db_col in COLUMN_MAPPING.items():
            if excel_col in df.columns:
                value = row[excel_col]
                if pd.isna(value):
                    value = None
                # 截断超长字段
                if isinstance(value, str) and len(value) > 500:
                    value = value[:500]
                record[db_col] = value
        
        record['data_source'] = '工信部公告'
        records.append(record)
    
    if not records:
        log("没有记录需要上传")
        return 0
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 先删除该批次的旧数据（避免重复）
        cursor.execute("DELETE FROM vehicle_product_publicity WHERE batch = %s", (batch,))
        log(f"  已清除旧数据")
        
        # 插入新数据
        db_columns = list(records[0].keys())
        columns_str = ', '.join(db_columns)
        placeholders = ', '.join(['%s'] * len(db_columns))
        
        sql = f"""
            INSERT INTO vehicle_product_publicity ({columns_str})
            VALUES ({placeholders})
        """
        
        values = [tuple(r.get(col) for col in db_columns) for r in records]
        execute_batch(cursor, sql, values, page_size=1000)
        conn.commit()
        
        log(f"成功上传 {len(values)} 条记录到数据库")
        return len(values)
        
    except Exception as e:
        conn.rollback()
        log(f"数据库上传失败: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# ============ 主流程 ============
def run_single_batch(batch_num, batch_params=None):
    """运行单个批次爬取"""
    try:
        # 检查是否已存在
        if check_batch_exists(batch_num):
            log(f"第{batch_num}批已存在于数据库，跳过")
            return True
        
        # 如果没有提供参数，需要获取
        if batch_params is None:
            log(f"需要获取第{batch_num}批的参数...")
            # 这里简化处理，实际需要从发现流程获取
            return False
        
        # 爬取数据
        records = scrape_batch(batch_params)
        if not records:
            log(f"第{batch_num}批没有获取到数据")
            return False
        
        # 构建DataFrame
        df = build_dataframe(records)
        log(f"DataFrame: {df.shape}")
        
        # 保存Excel
        save_excel(df, batch_num)
        
        # 上传到数据库
        upload_to_database(df, batch_num)
        
        log(f"第{batch_num}批处理完成！")
        return True
        
    except Exception as e:
        log(f"第{batch_num}批处理失败: {e}")
        import traceback
        log(traceback.format_exc())
        return False


def run_auto_discovery():
    """自动发现并处理新批次（使用新版机制）"""
    log("\n" + "="*60)
    log("开始自动发现新批次")
    log("="*60)
    
    # 获取数据库中最新批次
    latest_batch = get_latest_batch_in_db()
    log(f"数据库最新批次: 第{latest_batch}批")
    
    # 使用新版发现机制（基于已知路径 + Bing 搜索）
    new_batches_info = discover_new_batches_v2(latest_batch)
    
    if not new_batches_info:
        log("没有发现需要处理的新批次")
        return []
    
    # 构建批次参数列表
    batch_params_list = []
    for batch_num in sorted(new_batches_info.keys()):
        info = new_batches_info[batch_num]
        
        # 再次确认不在数据库中（双重检查）
        if check_batch_exists(batch_num):
            log(f"  第{batch_num}批已存在于数据库，跳过")
            continue
        
        params = {
            'batch': batch_num,
            'iframe_path': f"{XCPGS_BASE_PATH}/{KNOWN_BATCH_PATHS.get(batch_num, (f'xcpgs{batch_num}', None))[0]}",
            'iframe_prefix': f'{batch_num}',
            'webId': info['webId'],
            'pageId': info['pageId'],
            'tplSetId': info['tplSetId'],
            'article_url': info['xcpgs_url'],
        }
        batch_params_list.append(params)
        log(f"  已准备第{batch_num}批参数: pageId={info['pageId']}")
    
    log(f"共 {len(batch_params_list)} 个批次待处理")
    return batch_params_list


def main():
    """主函数"""
    log("\n" + "="*60)
    log("工信部新车公告数据自动爬取任务")
    log("="*60)
    
    # 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 自动发现新批次
    batch_params_list = run_auto_discovery()
    
    if not batch_params_list:
        log("没有需要处理的新批次，任务结束")
        return
    
    # 处理每个批次
    success_count = 0
    for params in batch_params_list:
        if run_single_batch(params['batch'], params):
            success_count += 1
        time.sleep(2)  # 批次间间隔
    
    log(f"\n{'='*60}")
    log(f"任务完成: {success_count}/{len(batch_params_list)} 个批次成功")
    log(f"{'='*60}")


if __name__ == '__main__':
    main()
