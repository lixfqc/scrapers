# -*- coding: utf-8 -*-
"""
优化版DOC解析器 V2
解决问题：
1. 产品型号提取不准确（混入产品名称）
2. 企业名截断（缺少"有限公司"等后缀）

数据格式：序号 + 商标(XX牌) + 产品名称 + 型号 + 企业名
示例：1 一汽牌 纯电动轿车 CA7009 中国第一汽车集团有限公司

更新日志：
- v2.1 (2026-08-10): 支持2位数字摩托车型号、中文编号列表清理、企业名回填逻辑
"""
import olefile
import re
import json
import os
import psycopg2

# 配置
DOC_DIR = r"D:\数据\公告\doc附件"
OUTPUT_DIR = r"D:\数据\公告\doc附件"
DB_CONFIG = {
    "host": "pgm-bp1sf8zujdx18698io.pg.rds.aliyuncs.com",
    "port": 5432,
    "user": "Levin001",
    "password": "Li800124",
    "dbname": "gonggao"
}

# 常见汽车型号前缀
MODEL_PREFIXES = [
    'CA', 'EQ', 'DFA', 'DFD', 'DFH', 'B', 'BJ', 'C', 'HFC', 'HFF',
    'SHH', 'SHZ', 'ZJL', 'JL', 'GAC', 'SGM', 'LFM', 'LFW', 'ZAM',
    'LZ', 'YNJ', 'SX', 'ZZ', 'ZZY', 'CSR', 'JAC', 'LJ', 'ZOTYE',
    'ZX', 'HQ', 'HMG', 'ZGH', 'FZ', 'FD', 'FJ', 'XG', 'JH', 'JKM',
    'JSV', 'JTD', 'JNE', 'BBD', 'BDK', 'BJG', 'BYD', 'BYL', 'CNJ',
    'DYK', 'FDK', 'FTS', 'FTT', 'FWS', 'GAC', 'GWM', 'GZ', 'HF',
    'HMC', 'HME', 'HQE', 'HUTCH', 'HY', 'JAC', 'JBE', 'JHM', 'JINBEI',
    'JMC', 'JMZ', 'JNJ', 'JYZ', 'KYL', 'LDK', 'LDS', 'LEASM', 'LIUGONG',
    'LNT', 'LONGWAY', 'LOTH', 'LPG', 'LTC', 'LTZ', 'LYK', 'MACC',
    'MAXUS', 'MBD', 'MCV', 'MDA', 'MTC', 'MTM', 'NBN', 'NFC', 'NKG',
    'NLM', 'NWD', 'PAILE', 'PERSCH', 'PFT', 'QG', 'QJM', 'QL',
    'REELY', 'RIM', 'ROEWE', 'SAICM', 'SAICMAXUS', 'SANY', 'SENY',
    'SEVEN', 'SHAC', 'SHF', 'SHL', 'SHM', 'SHOW', 'SHZ', 'SITRAK',
    'SKIY', 'SLE', 'SMART', 'SNP', 'SPRINTR', 'STE', 'SUE', 'SWS',
    'TAM', 'TIA', 'TITAN', 'TS', 'TSL', 'TYS', 'VMC', 'WATANABE',
    'WEICHAI', 'WFC', 'WIHON', 'WINALL', 'WULONG', 'WUZHONG',
    'XCMG', 'XFT', 'XINFEI', 'XLB', 'XPNG', 'XSG', 'XSGM', 'YAC',
    'YANGHE', 'YEMA', 'YIBEN', 'YUEJIN', 'YUNNEI', 'ZBT', 'ZC',
    'ZCG', 'ZDK', 'ZGT', 'ZH', 'ZHIDEE', 'ZHKC', 'ZNC', 'ZNZ',
    'ZPY', 'ZXT', 'ZX', 'ZYK', 'ZZZ'
]


def extract_text_from_doc(doc_path):
    ole = olefile.OleFileIO(doc_path)
    data = ole.openstream('WordDocument').read()
    ole.close()
    text = data.decode('utf-16-le', errors='ignore')
    return text


def clean_text(text):
    clean = re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]', ' ', text)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()


def find_record_boundaries(clean_text):
    boundary_pattern = r'(\d{1,4})\s+([\u4e00-\u9fff]{2,10}?牌)'
    boundaries = []
    for m in re.finditer(boundary_pattern, clean_text):
        boundaries.append({
            'start': m.start(),
            'catalog_num': m.group(1),
            'trademark': m.group(2)
        })
    return boundaries


def extract_enterprise_name(text, debug=False):
    def _log(msg):
        if debug:
            print(f"  [extract_enterprise_name] {msg}")
    
    _log(f"输入文本 (长度={len(text)}): '{text[:100]}...'")
    cleaned = text
    
    # 特殊处理：企业名称：XXX 格式
    special_pattern = r'企业名称[：:]\s*([^\s；;,，\n]+?(?:有限公司|股份有限公司|集团有限公司|有限责任公司|公司|集团|厂))'
    special_match = re.search(special_pattern, cleaned)
    if special_match:
        result = special_match.group(1).strip()
        _log(f"命中特殊模式 → 提取: '{result}'")
        return result
    
    # 清理编号备注
    for loop_idx in range(5):
        new_cleaned = cleaned
        
        # 清理 (中文数字) 或 (阿拉伯数字) 格式
        new_cleaned = re.sub(
            r'[\(（]\s*(?:[一二三四五六七八九十百千]+|\d{1,3})\s*[)）]\s*\d*\s*[,，]?\s*$',
            '', new_cleaned
        ).strip()
        
        # 清理末尾的编号+逗号
        new_cleaned = re.sub(
            r'\d{1,4}\s*[,，]\s*(?:[一二三四五六七八九十百千]+[、,，]\s*)*$',
            '', new_cleaned
        ).strip()
        
        # 清理中文编号列表（如 "三、二、"）
        new_cleaned = re.sub(
            r'[一二三四五六七八九十百千]+[、，]\s*(?:[一二三四五六七八九十百千]+[、，]\s*)*$',
            '', new_cleaned
        ).strip()
        
        # 清理特殊标记
        new_cleaned = re.sub(r'(?:ZY)\s*$', '', new_cleaned).strip()
        
        if new_cleaned == cleaned:
            break
        cleaned = new_cleaned
    
    if not cleaned:
        return ''
    
    # 企业名后缀模式
    suffixes = ['有限责任公司', '股份有限公司', '集团有限公司', '有限公司', '股份公司', '公司', '集团', '厂', 'Co., Ltd.', 'Corp.', 'Inc.', 'LLC']
    
    best_match = ''
    best_end = -1
    
    for suffix in suffixes:
        suffix_pattern = re.escape(suffix)
        matches = list(re.finditer(suffix_pattern, cleaned))
        
        for m in matches:
            end_pos = m.end()
            start_pos = m.start()
            
            # 向前扩展
            prefix = ''
            i = start_pos - 1
            while i >= 0:
                char = cleaned[i]
                if '\u4e00' <= char <= '\u9fff' or char in '（）()' or char.isalpha() or char.isdigit() or char in ',-./&':
                    prefix = char + prefix
                    i -= 1
                else:
                    break
            
            full_match = prefix + suffix
            chinese_in_prefix = re.sub(r'[（）()\- ,.&]', '', prefix)
            if len(chinese_in_prefix) < 2:
                continue
            
            after_text = cleaned[end_pos:].strip()
            
            if after_text == '':
                if end_pos > best_end:
                    best_match = full_match
                    best_end = end_pos
                continue
            
            bracket_match = re.match(r'^[\(（][^\)）]+[)）]', after_text)
            if bracket_match:
                bracket_end = bracket_match.end()
                rest_after_bracket = after_text[bracket_end:].strip()
                if rest_after_bracket == '' or re.match(r'^[\(（]\s*(?:[一二三四五六七八九十百千]+|\d{1,3})\s*[)）]', rest_after_bracket):
                    if end_pos + bracket_end > best_end:
                        best_match = full_match + bracket_match.group(0)
                        best_end = end_pos + bracket_end
                continue
            
            if re.match(r'^[\(（]\s*(?:[一二三四五六七八九十百千]+|\d{1,3})\s*[)）]', after_text):
                if end_pos > best_end:
                    best_match = full_match
                    best_end = end_pos
    
    return best_match


def extract_model_and_name(text):
    # 标准型号：2-4位字母 + 3-6位数字
    standard_pattern = r'[A-Z]{1,4}\d{3,6}[A-Za-z0-9\-]*'
    # 轻便摩托车型号：2位数字
    motorcycle_pattern = r'[A-Z]{1,4}\d{2}[A-Z]{1,3}'
    # 多型号连接模式
    multi_model_pattern = r'(?:' + standard_pattern + r'|' + motorcycle_pattern + r')(?:、(?:' + standard_pattern + r'|' + motorcycle_pattern + r'))*'
    
    model_matches = list(re.finditer(multi_model_pattern, text))
    
    if not model_matches:
        return text.strip(), ''
    
    models = [m.group(0) for m in model_matches]
    model_str = '、'.join(models) if len(models) > 1 else models[0]
    
    product_name = text
    for model in models:
        product_name = product_name.replace(model, '')
    product_name = re.sub(r'\s+', ' ', product_name).strip()
    
    return product_name, model_str


def parse_record_segment(record_text, catalog_num, trademark, seen, skipped, debug=False):
    def _log(msg):
        if debug:
            print(f"  [parse_record_segment] {msg}")
    
    header_pattern = r'^(\d{1,4})\s+([\u4e00-\u9fff\w\s()（）]{2,20}?牌)\s+'
    header_match = re.match(header_pattern, record_text)
    if not header_match:
        return None, False, []
    
    catalog_num = header_match.group(1)
    trademark = header_match.group(2)
    remaining = record_text[header_match.end():].strip()
    
    # 检测跨记录拼接
    sub_record_pattern = r'(\d{1,4})\s+([\u4e00-\u9fff\w\s()（）]{2,20}?牌)\s+.*?([A-Z]{1,4}\d{3,6}[A-Za-z0-9、\-]*)'
    sub_matches = list(re.finditer(sub_record_pattern, remaining))
    
    if len(sub_matches) >= 2:
        split_positions = [m.start() for m in sub_matches]
        split_positions.append(len(remaining))
        
        all_sub_records = []
        for j in range(len(split_positions) - 1):
            sub_text = remaining[split_positions[j]:split_positions[j+1]].strip()
            sub_header_match = re.match(r'^(\d{1,4})\s+([\u4e00-\u9fff\w\s()（）]{2,20}?牌)\s+(.*)', sub_text)
            if sub_header_match:
                sub_catalog = sub_header_match.group(1)
                sub_trademark = sub_header_match.group(2)
                sub_remaining = sub_header_match.group(3).strip()
                
                sub_enterprise = extract_enterprise_name(sub_remaining, debug=debug)
                sub_product_info = sub_remaining
                if sub_enterprise:
                    ent_idx = sub_remaining.rfind(sub_enterprise)
                    if ent_idx > 0:
                        sub_product_info = sub_remaining[:ent_idx].strip()
                
                sub_name, sub_model = extract_model_and_name(sub_product_info)
                if sub_model and sub_name and len(sub_name) >= 2:
                    all_sub_records.append({
                        'catalog_number': sub_catalog,
                        'product_trademark': sub_trademark,
                        'product_name': sub_name,
                        'product_model': sub_model,
                        'enterprise_name': sub_enterprise,
                    })
        
        if all_sub_records:
            valid_records = []
            for sr in all_sub_records:
                key = f"{sr['product_trademark']}_{sr['product_model']}"
                if key not in seen:
                    seen.add(key)
                    valid_records.append(sr)
            if valid_records:
                return valid_records[0], True, valid_records[1:] if len(valid_records) > 1 else []
    
    # 正常解析
    truncated = remaining
    complete_pattern = r'\d{1,4}\s+[\u4e00-\u9fff\w\s()（）]{2,20}?牌\s+.*?[A-Z]{1,4}\d{3,6}[A-Za-z0-9、\-]*'
    complete_matches = list(re.finditer(complete_pattern, remaining))
    
    if len(complete_matches) >= 2:
        second_start = complete_matches[1].start()
        if second_start > 80:
            truncated = remaining[:second_start].strip()
    elif len(complete_matches) == 1 and len(remaining) > 300:
        complete_end = complete_matches[0].end()
        after_complete = remaining[complete_end:]
        brand_only_pattern = r'\d{1,4}\s+[\u4e00-\u9fff\w\s()（）]{2,20}?牌'
        brand_matches = list(re.finditer(brand_only_pattern, after_complete))
        if brand_matches:
            first_brand_pos = complete_end + brand_matches[0].start()
            if first_brand_pos > 80:
                truncated = remaining[:first_brand_pos].strip()
    
    # 提取企业名并回填
    enterprise_name = extract_enterprise_name(truncated, debug=debug)
    if not enterprise_name and truncated != remaining:
        enterprise_name = extract_enterprise_name(remaining, debug=debug)
    
    product_info = truncated
    if enterprise_name:
        ent_idx = truncated.rfind(enterprise_name)
        if ent_idx > 0:
            product_info = truncated[:ent_idx].strip()
        else:
            full_ent_idx = remaining.rfind(enterprise_name)
            if full_ent_idx > 0:
                product_info = remaining[:full_ent_idx].strip()
    
    product_name, model = extract_model_and_name(product_info)
    
    if not model:
        return None, False, []
    if not enterprise_name:
        skipped['no_enterprise'] = skipped.get('no_enterprise', 0) + 1
    if not product_name or len(product_name) < 2:
        return None, False, []
    
    key = f"{trademark}_{model}"
    if key in seen:
        skipped['duplicate'] = skipped.get('duplicate', 0) + 1
        return None, False, []
    seen.add(key)
    
    return {
        'catalog_number': catalog_num,
        'product_trademark': trademark,
        'product_name': product_name,
        'product_model': model,
        'enterprise_name': enterprise_name,
    }, True, []


def parse_records_v2(clean_text, debug=False, debug_indices=None):
    boundaries = find_record_boundaries(clean_text)
    records = []
    skipped = {'no_header': 0, 'no_model': 0, 'no_enterprise': 0, 'duplicate': 0, 'split': 0}
    seen = set()
    
    for i, boundary in enumerate(boundaries):
        start_pos = boundary['start']
        end_pos = boundaries[i + 1]['start'] if i + 1 < len(boundaries) else len(clean_text)
        record_text = clean_text[start_pos:end_pos].strip()
        
        header_pattern = r'^(\d{1,4})\s+([\u4e00-\u9fff\w\s()（）]{2,20}?牌)\s+'
        header_match = re.match(header_pattern, record_text)
        if not header_match:
            skipped['no_header'] += 1
            continue
        
        catalog_num = header_match.group(1)
        trademark = header_match.group(2)
        record_debug = debug or (debug_indices and i in debug_indices)
        
        result = parse_record_segment(record_text, catalog_num, trademark, seen, skipped, debug=record_debug)
        if result is None:
            continue
        
        if isinstance(result, tuple) and len(result) == 3:
            record, is_valid, extra = result
            if is_valid and record:
                records.append(record)
                if extra:
                    records.extend(extra)
        elif isinstance(result, tuple) and len(result) == 2:
            record, is_valid = result
            if is_valid and record:
                records.append(record)
    
    return records


def upload_to_db(records, batch_num):
    batch = f'第{batch_num}批'
    db_records = [{
        'batch': batch,
        'product_trademark': r['product_trademark'],
        'product_model': r['product_model'],
        'product_name': r['product_name'],
        'enterprise_name': r['enterprise_name'],
        'catalog_number': r['catalog_number'],
        'data_source': '工信部公告(DOC)',
    } for r in records]
    
    if not db_records:
        return 0
    
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM vehicle_product_publicity WHERE batch = %s", (batch,))
        from psycopg2.extras import execute_batch
        columns = list(db_records[0].keys())
        columns_str = ', '.join(columns)
        placeholders = ', '.join(['%s'] * len(columns))
        sql = f"INSERT INTO vehicle_product_publicity ({columns_str}) VALUES ({placeholders})"
        values = [tuple(r.get(col) for col in columns) for r in db_records]
        execute_batch(cursor, sql, values, page_size=1000)
        conn.commit()
        return len(values)
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    print("=== 工信部DOC解析器 V2 ===")
    for batch_num, doc_file in {406: 'batch406_f66eea329f224580a312ab5b26b09f75.doc', 407: 'batch407_b43b6a0d1ffb47eba041adefa8541476.doc'}.items():
        doc_path = os.path.join(DOC_DIR, doc_file)
        if os.path.exists(doc_path):
            text = extract_text_from_doc(doc_path)
            clean = clean_text(text)
            records = parse_records_v2(clean)
            if records:
                upload_to_db(records, batch_num)
                print(f"第{batch_num}批: {len(records)} 条")
