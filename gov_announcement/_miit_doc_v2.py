# -*- coding: utf-8 -*-
"""
优化版DOC解析器 V2.1
解决问题：
1. 产品型号提取不准确（混入产品名称）
2. 企业名截断（缺少"有限公司"等后缀）
3. 企业统计表误识别（no_header问题）
4. 纯字母缩写型号无法识别（no_model问题）

数据格式：序号 + 商标(XX牌) + 产品名称 + 型号 + 企业名
示例：1 一汽牌 纯电动轿车 CA7009 中国第一汽车集团有限公司
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

# 常见汽车型号前缀（用于识别型号）
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
    """从DOC文件提取文本"""
    ole = olefile.OleFileIO(doc_path)
    data = ole.openstream('WordDocument').read()
    ole.close()
    text = data.decode('utf-16-le', errors='ignore')
    return text


def clean_text(text):
    """清理控制字符"""
    # 移除控制字符，保留中文、字母、数字、标点
    clean = re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]', ' ', text)
    # 合并多个空格
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()


def find_record_boundaries(clean_text):
    """
    找出所有记录的边界位置
    记录格式：序号 + 商标(XX牌) + 产品信息
    记录以数字序号开头（1-4位数字）
    
    修复：添加负向前瞻，排除企业统计表中的"牌"字（如"王牌商用车有限公司"中的"王牌"）
    真实品牌格式：XX牌 后面跟空格或非汉字字符
    企业统计表格式：数字 + 企业名（"牌"是企业名的一部分，如"王牌商用车"）
    """
    # 模式：序号 + 空格 + 包含"牌"字的商标
    # 负向前瞻 (?![\u4e00-\u9fff])：确保"牌"后面不跟汉字（排除企业名中的"牌"）
    boundary_pattern = r'(\d{1,4})\s+([\u4e00-\u9fff]{2,10}?牌)(?![\u4e00-\u9fff])'
    boundaries = []
    
    for m in re.finditer(boundary_pattern, clean_text):
        start = m.start()
        catalog_num = m.group(1)
        trademark = m.group(2)
        boundaries.append({
            'start': start,
            'catalog_num': catalog_num,
            'trademark': trademark
        })
    
    return boundaries


def extract_enterprise_name(text, debug=False):
    """
    从文本末尾提取企业名称
    企业名特征：包含"公司"、"集团"、"有限"、"股份"、"厂"等关键词
    企业名位于产品信息的最后部分，可能后跟备注（如(一)、(十一)、生产地址等）
    
    注意：企业名可能包含括号，如"赛力斯汽车(湖北)有限公司"
    
    Args:
        text: 待提取的文本
        debug: 是否启用详细调试日志
    
    Returns:
        企业名称字符串，未找到返回空字符串
    """
    def _log(msg):
        if debug:
            print(f"  [extract_enterprise_name] {msg}")
    
    _log(f"输入文本 (长度={len(text)}): '{text[:100]}...'")
    
    cleaned = text
    
    # 特殊处理：企业名称：XXX 格式（常用于新增生产企业公告）
    # 格式："企业名称：XXX" 或 "企业名称:XXX"
    special_pattern = r'企业名称[：:]\s*([^\s；;,，\n]+?(?:有限公司|股份有限公司|集团有限公司|有限责任公司|公司|集团|厂))'
    special_match = re.search(special_pattern, cleaned)
    if special_match:
        result = special_match.group(1).strip()
        _log(f"命中特殊模式 '企业名称：XXX' → 提取: '{result}'")
        return result
    else:
        _log("特殊模式 '企业名称：XXX' 未命中")
    
    # 清理文本末尾的编号备注和干扰内容
    _log("开始清理编号备注...")
    for loop_idx in range(5):
        new_cleaned = cleaned
        before_clean = new_cleaned
        
        # 清理 (中文数字) 或 (阿拉伯数字) 格式
        # 支持：(一)、(十)、(十一)、(二十)、(1)、(12) 等
        # 后面可能跟数字和逗号，如 (十一)37,
        new_cleaned = re.sub(
            r'[\(（]\s*(?:[一二三四五六七八九十百千]+|\d{1,3})\s*[)）]\s*\d*\s*[,，]?\s*$',
            '', 
            new_cleaned
        ).strip()
        
        # 清理末尾的编号+逗号（如 "123," 或 "48,三、一、"）
        new_cleaned = re.sub(
            r'\d{1,4}\s*[,，]\s*(?:[一二三四五六七八九十百千]+[、,，]\s*)*$',
            '', 
            new_cleaned
        ).strip()
        
        # 清理中文编号列表（如 "三、二、" 或 "一、二、三、"）
        # 格式：以中文数字开头，后跟顿号分隔的中文数字，可能以顿号结尾
        new_cleaned = re.sub(
            r'[一二三四五六七八九十百千]+[、，]\s*(?:[一二三四五六七八九十百千]+[、，]\s*)*$',
            '', 
            new_cleaned
        ).strip()
        
        # 清理特殊标记：ZY 等
        new_cleaned = re.sub(
            r'(?:ZY)\s*$',
            '', 
            new_cleaned
        ).strip()
        
        if new_cleaned == cleaned:
            _log(f"清理循环第{loop_idx}次：无变化，停止清理")
            break
        
        _log(f"清理循环第{loop_idx}次: '{before_clean}' → '{new_cleaned}'")
        cleaned = new_cleaned
    
    _log(f"清理后文本: '{cleaned[:100]}...'")
    
    if not cleaned:
        _log("清理后文本为空，返回空字符串")
        return ''
    
    # 企业名后缀模式（按优先级排列）
    suffixes = [
        '有限责任公司',
        '股份有限公司',
        '集团有限公司',
        '有限公司',
        '股份公司',
        '公司',
        '集团',
        '厂',
        # 英文后缀
        'Co., Ltd.',
        'Co.,Ltd.',
        'Corp.',
        'Corporation',
        'Inc.',
        'LLC',
    ]
    
    best_match = ''
    best_end = -1
    
    # 策略：在文本中搜索所有可能的企业名匹配
    _log("开始搜索企业名后缀...")
    for suffix in suffixes:
        suffix_pattern = re.escape(suffix)
        matches = list(re.finditer(suffix_pattern, cleaned))
        if matches and debug:
            _log(f"后缀 '{suffix}' 找到 {len(matches)} 处匹配")
        
        for m in matches:
            end_pos = m.end()
            start_pos = m.start()
            
            # 向前扩展：尽可能多地匹配中文字符、英文字符和括号内容
            prefix = ''
            i = start_pos - 1
            
            while i >= 0:
                char = cleaned[i]
                if ('\u4e00' <= char <= '\u9fff' or 
                    char in '（）()' or 
                    char.isalpha() or 
                    char.isdigit() or
                    char in ',-./&'):
                    prefix = char + prefix
                    i -= 1
                else:
                    break
            
            full_match = prefix + suffix
            
            chinese_in_prefix = re.sub(r'[（）()\- ,.&]', '', prefix)
            if len(chinese_in_prefix) < 2:
                _log(f"  跳过: 前缀字符数不足 (full_match='{full_match}', prefix='{prefix}')")
                continue
            
            # 检查匹配后面的内容
            after_text = cleaned[end_pos:].strip()
            
            # 情况1：后面为空
            if after_text == '':
                _log(f"  命中(情况1-后面为空): '{full_match}'")
                if end_pos > best_end:
                    best_match = full_match
                    best_end = end_pos
                continue
            
            # 情况2：后面跟括号备注（如(杭州)、(湖北)），且括号后只有备注编号或结束
            bracket_match = re.match(r'^[\(（][^\)）]+[)）]', after_text)
            if bracket_match:
                bracket_end = bracket_match.end()
                rest_after_bracket = after_text[bracket_end:].strip()
                
                # 括号后只有备注编号或为空
                if rest_after_bracket == '' or re.match(r'^[\(（]\s*(?:[一二三四五六七八九十百千]+|\d{1,3})\s*[)）]', rest_after_bracket):
                    # 格式：企业名 + (地点) + (编号备注)
                    full_with_bracket = full_match + bracket_match.group(0)
                    _log(f"  命中(情况2-括号备注): '{full_with_bracket}'")
                    if end_pos + bracket_end > best_end:
                        best_match = full_with_bracket
                        best_end = end_pos + bracket_end
                else:
                    _log(f"  跳过(情况2-括号后还有其他内容): bracket='{bracket_match.group(0)}', rest='{rest_after_bracket[:50]}'")
                continue
            
            # 情况3：后面跟编号备注
            if re.match(r'^[\(（]\s*(?:[一二三四五六七八九十百千]+|\d{1,3})\s*[)）]', after_text):
                _log(f"  命中(情况3-编号备注): '{full_match}', after='{after_text[:50]}'")
                if end_pos > best_end:
                    best_match = full_match
                    best_end = end_pos
            else:
                _log(f"  跳过: after_text='{after_text[:50]}' 不符合任何情况")
    
    _log(f"最终结果: '{best_match}' (best_end={best_end})")
    return best_match


def extract_model_and_name(text):
    """
    从产品信息段中分离型号和产品名称
    产品名称：纯中文描述（如"纯电动轿车"、"牵引汽车"）
    型号：字母+数字组合（如"CA7009"、"EQ4250"、"DFA1030、DFA1040"、"YB50QT"）
          或纯字母缩写（如"CDW"，成都王牌的企业缩写）
    
    处理逻辑：
    1. 先尝试提取标准型号（字母+数字组合）
    2. 如果没找到标准型号，检查是否为纯字母缩写型号（回退逻辑）
    3. 剩余部分为产品名称
    
    注意：支持摩托车/轻便摩托车的2位数字型号（如50QT、800DQT）
    """
    # 型号模式：支持多种格式
    # 1. 标准型号：2-4位字母 + 3-6位数字（如CA7009、EQ4250）
    # 2. 摩托车型号：2-4位字母 + 2位数字 + 可选字母（如YB50QT、CQ50QT、QH50QT）
    # 3. 扩展型号：数字后可能跟字母（如X、DQT）
    
    # 分步匹配：先尝试3-6位数字的标准型号
    standard_pattern = r'[A-Z]{1,4}\d{3,6}[A-Za-z0-9\-]*'
    # 轻便摩托车型号：2位数字
    motorcycle_pattern = r'[A-Z]{1,4}\d{2}[A-Z]{1,3}'
    # 多型号连接模式
    multi_model_pattern = r'(?:' + standard_pattern + r'|' + motorcycle_pattern + r')(?:、(?:' + standard_pattern + r'|' + motorcycle_pattern + r'))*'
    
    # 查找所有型号匹配
    model_matches = list(re.finditer(multi_model_pattern, text))
    
    if not model_matches:
        # 回退逻辑：检查是否为纯字母缩写型号（如CDW）
        # 仅当没有找到标准/摩托车型号时启用
        # 条件：文本中最后一个空格分隔的token是2-4位纯字母
        tokens = text.strip().split()
        if tokens:
            last_token = tokens[-1]
            # 检查最后一个token是否为2-4位纯大写字母
            if re.match(r'^[A-Z]{2,4}$', last_token):
                # 验证：确保这个token不是产品名的一部分
                # 产品名通常在型号前面，型号通常是最后一个词
                # 只有当文本中有中文（产品描述）时，才认为最后的纯字母是型号
                has_chinese = bool(re.search(r'[\u4e00-\u9fff]', text))
                if has_chinese:
                    # 提取纯字母型号
                    model_str = last_token
                    # 产品名称：移除型号部分后的剩余文本
                    product_name = text.replace(last_token, '').strip()
                    product_name = re.sub(r'\s+', ' ', product_name).strip()
                    return product_name, model_str
        
        # 如果没找到型号，返回空型号
        return text.strip(), ''
    
    # 提取所有型号
    models = [m.group(0) for m in model_matches]
    model_str = '、'.join(models) if len(models) > 1 else models[0]
    
    # 产品名称：移除型号部分后的剩余文本
    product_name = text
    for model in models:
        product_name = product_name.replace(model, '')
    product_name = re.sub(r'\s+', ' ', product_name).strip()
    
    return product_name, model_str


def parse_record_segment(record_text, catalog_num, trademark, seen, skipped, debug=False):
    """
    解析单个记录段
    返回：(record_dict, is_valid, extra_records) 
    - record_dict: 主记录（可能为None）
    - is_valid: 是否有效
    - extra_records: 跨记录拼接分割出的额外记录（不含主记录）
    
    Args:
        record_text: 记录原始文本
        catalog_num: 序号
        trademark: 商标
        seen: 已见记录集合（用于去重）
        skipped: 跳过计数字典
        debug: 是否启用详细调试日志
    """
    def _log(msg):
        if debug:
            print(f"  [parse_record_segment] {msg}")
    
    _log(f"开始解析: 序号={catalog_num}, 商标={trademark}")
    _log(f"  record_text (长度={len(record_text)}): '{record_text[:120]}...'")
    
    # 移除头部，获取剩余部分（产品信息 + 企业名）
    header_pattern = r'^(\d{1,4})\s+([\u4e00-\u9fff\w\s()（）]{2,20}?牌)\s+'
    header_match = re.match(header_pattern, record_text)
    if not header_match:
        _log(f"  ❌ 头部匹配失败，跳过")
        return None, False, []
    
    catalog_num = header_match.group(1)
    trademark = header_match.group(2)
    _log(f"  头部匹配成功: 序号={catalog_num}, 商标={trademark}")
    
    remaining = record_text[header_match.end():].strip()
    _log(f"  remaining (长度={len(remaining)}): '{remaining[:120]}...'")
    
    # 检测是否跨记录拼接
    # 关键判断：在剩余文本中查找多个"序号+品牌+型号"的完整记录模式
    sub_record_pattern = r'(\d{1,4})\s+([\u4e00-\u9fff\w\s()（）]{2,20}?牌)\s+.*?([A-Z]{1,4}\d{3,6}[A-Za-z0-9、\-]*)'
    sub_matches = list(re.finditer(sub_record_pattern, remaining))
    _log(f"  跨记录拼接检测: 找到 {len(sub_matches)} 个子记录模式")
    
    if len(sub_matches) >= 2:
        _log(f"  ✅ 检测到跨记录拼接，开始分割...")
        # 找到多个完整的记录模式（序号+品牌+型号），说明存在跨记录拼接
        split_positions = [m.start() for m in sub_matches]
        split_positions.append(len(remaining))
        _log(f"  分割位置: {split_positions}")
        
        all_sub_records = []
        for j in range(len(split_positions) - 1):
            sub_text = remaining[split_positions[j]:split_positions[j+1]].strip()
            _log(f"  处理子记录{j+1}: '{sub_text[:100]}...'")
            
            # 尝试解析子记录
            sub_header_match = re.match(
                r'^(\d{1,4})\s+([\u4e00-\u9fff\w\s()（）]{2,20}?牌)\s+(.*)', 
                sub_text
            )
            if sub_header_match:
                sub_catalog = sub_header_match.group(1)
                sub_trademark = sub_header_match.group(2)
                sub_remaining = sub_header_match.group(3).strip()
                _log(f"    子记录头部: 序号={sub_catalog}, 商标={sub_trademark}")
                
                # 提取企业名
                sub_enterprise = extract_enterprise_name(sub_remaining, debug=debug)
                sub_product_info = sub_remaining
                if sub_enterprise:
                    ent_idx = sub_remaining.rfind(sub_enterprise)
                    if ent_idx > 0:
                        sub_product_info = sub_remaining[:ent_idx].strip()
                    _log(f"    企业名提取: '{sub_enterprise}'")
                else:
                    _log(f"    ⚠️ 企业名为空!")
                
                # 分离产品名和型号
                sub_name, sub_model = extract_model_and_name(sub_product_info)
                _log(f"    产品名='{sub_name}', 型号='{sub_model}'")
                
                if sub_model and sub_name and len(sub_name) >= 2:
                    all_sub_records.append({
                        'catalog_number': sub_catalog,
                        'product_trademark': sub_trademark,
                        'product_name': sub_name,
                        'product_model': sub_model,
                        'enterprise_name': sub_enterprise,
                    })
                    _log(f"    ✅ 子记录有效")
                else:
                    _log(f"    ❌ 子记录无效 (model={bool(sub_model)}, name_len={len(sub_name) if sub_name else 0})")
            else:
                _log(f"    ❌ 子记录头部匹配失败")
        
        if all_sub_records:
            # 去重
            valid_records = []
            for sr in all_sub_records:
                key = f"{sr['product_trademark']}_{sr['product_model']}"
                if key not in seen:
                    seen.add(key)
                    valid_records.append(sr)
                    _log(f"  去重通过: key='{key}'")
                else:
                    _log(f"  去重跳过: key='{key}' 已存在")
            
            if valid_records:
                # 第一条作为主记录，其余作为额外记录
                main_record = valid_records[0]
                extra_records = valid_records[1:] if len(valid_records) > 1 else []
                _log(f"  返回: 主记录(序号{main_record['catalog_number']}, {main_record['product_trademark']}), 额外记录{len(extra_records)}条")
                return main_record, True, extra_records
    
    # 正常解析流程（无跨记录拼接检测到，但可能仍有多条记录混在一起）
    _log(f"  进入正常解析流程...")
    truncated = remaining
    original_length = len(remaining)
    
    # 尝试找到真正的记录边界
    # 模式1：检测 "序号 + 品牌 + 型号" 完整模式
    complete_pattern = r'\d{1,4}\s+[\u4e00-\u9fff\w\s()（）]{2,20}?牌\s+.*?[A-Z]{1,4}\d{3,6}[A-Za-z0-9、\-]*'
    complete_matches = list(re.finditer(complete_pattern, remaining))
    _log(f"  完整模式匹配数: {len(complete_matches)}")
    
    if len(complete_matches) >= 2:
        # 至少有两条完整记录
        second_start = complete_matches[1].start()
        _log(f"  检测到第2条完整记录在位置{second_start}")
        if second_start > 80:
            truncated = remaining[:second_start].strip()
            _log(f"  截断: {original_length} → {len(truncated)} 字符")
        else:
            _log(f"  截断位置{second_start}太近，不截断")
    elif len(complete_matches) == 1 and len(remaining) > 300:
        # 只有一条完整记录，但文本过长
        complete_end = complete_matches[0].end()
        after_complete = remaining[complete_end:]
        _log(f"  单条完整记录结束位置: {complete_end}, 之后长度: {len(after_complete)}")
        
        # 查找 "序号 + 品牌" 模式
        brand_only_pattern = r'\d{1,4}\s+[\u4e00-\u9fff\w\s()（）]{2,20}?牌'
        brand_matches = list(re.finditer(brand_only_pattern, after_complete))
        _log(f"  完整记录之后的品牌匹配数: {len(brand_matches)}")
        
        if brand_matches:
            first_brand_pos = complete_end + brand_matches[0].start()
            _log(f"  找到下一个品牌位置: {first_brand_pos}")
            if first_brand_pos > 80:
                truncated = remaining[:first_brand_pos].strip()
                _log(f"  截断: {original_length} → {len(truncated)} 字符")
    
    # 如果仍然过长，尝试更激进的截断
    if len(truncated) > 400:
        _log(f"  文本仍过长 ({len(truncated)}>400)，尝试激进截断")
        aggressive_pattern = r'(\d{1,4})\s+([\u4e00-\u9fff\w\s()（）]{2,20}?牌)'
        agg_matches = list(re.finditer(aggressive_pattern, truncated))
        
        if len(agg_matches) >= 2:
            second_pos = agg_matches[1].start()
            _log(f"  找到第2个品牌位置: {second_pos}")
            after_second = truncated[second_pos:second_pos+100]
            _log(f"  检查型号: '{after_second[:80]}'")
            if re.search(r'[A-Z]{1,4}\d{3,6}', after_second):
                if second_pos > 100:
                    truncated = truncated[:second_pos].strip()
                    _log(f"  ✅ 确认截断: {original_length} → {len(truncated)} 字符")
                else:
                    _log(f"  ❌ 位置{second_pos}太近，不截断")
            else:
                _log(f"  ❌ 未检测到型号，不截断")
    
    _log(f"  最终用于解析的文本 (长度={len(truncated)}): '{truncated[:120]}...'")
    
    # 提取企业名 - 先从截断后的文本提取
    enterprise_name = extract_enterprise_name(truncated, debug=debug)
    _log(f"  截断文本企业名提取结果: '{enterprise_name}'")
    
    # 如果截断后的文本提取不到企业名，尝试从完整文本回填
    if not enterprise_name and truncated != remaining:
        _log(f"  截断文本企业名为空，尝试从完整文本回填...")
        enterprise_name = extract_enterprise_name(remaining, debug=debug)
        if enterprise_name:
            _log(f"  ✅ 从完整文本回填企业名成功: '{enterprise_name}'")
        else:
            _log(f"  完整文本也未提取到企业名")
    
    product_info = truncated
    
    if enterprise_name:
        # 从截断后的文本中找到企业名的位置
        ent_idx = truncated.rfind(enterprise_name)
        if ent_idx > 0:
            product_info = truncated[:ent_idx].strip()
            _log(f"  分离企业名后产品信息 (长度={len(product_info)}): '{product_info[:100]}...'")
        else:
            # 企业名是从完整文本回填的，截断文本中找不到
            # 尝试用型号位置来分离
            _log(f"  截断文本中找不到企业名位置，使用完整文本的产品信息")
            # 从完整文本中提取企业名之前的部分作为产品信息
            full_ent_idx = remaining.rfind(enterprise_name)
            if full_ent_idx > 0:
                product_info = remaining[:full_ent_idx].strip()
                _log(f"  从完整文本分离产品信息 (长度={len(product_info)}): '{product_info[:100]}...'")
    else:
        _log(f"  ⚠️ 企业名为空!")
    
    # 分离产品名和型号
    product_name, model = extract_model_and_name(product_info)
    _log(f"  解析结果: 产品名='{product_name}', 型号='{model}'")
    
    # 验证
    if not model:
        _log(f"  ❌ 型号为空，跳过")
        return None, False, []
    
    if not enterprise_name:
        _log(f"  ⚠️ 企业名为空，计入no_enterprise")
        skipped['no_enterprise'] = skipped.get('no_enterprise', 0) + 1
    
    if not product_name or len(product_name) < 2:
        _log(f"  ❌ 产品名无效 (长度={len(product_name) if product_name else 0})，跳过")
        return None, False, []
    
    # 去重检查
    key = f"{trademark}_{model}"
    if key in seen:
        _log(f"  ❌ 重复记录 key='{key}'，跳过")
        skipped['duplicate'] = skipped.get('duplicate', 0) + 1
        return None, False, []
    seen.add(key)
    
    record = {
        'catalog_number': catalog_num,
        'product_trademark': trademark,
        'product_name': product_name,
        'product_model': model,
        'enterprise_name': enterprise_name,
    }
    
    _log(f"  ✅ 解析成功: [{catalog_num}] {trademark} | {product_name} | {model} | {enterprise_name}")
    return record, True, []


def parse_records_v2(clean_text, debug=False, debug_indices=None):
    """
    V2版解析器：基于记录边界的分段解析 + 跨记录拼接检测
    数据格式：序号 + 商标(XX牌) + 产品名称 + 型号 + 企业名
    示例：1 一汽牌 纯电动轿车 CA7009 中国第一汽车集团有限公司
          1 极狐(ARCFOX)牌 纯电动多用途乘用车 AFS6000BEV 北汽蓝谷麦格纳汽车有限公司
    
    增加：
    1. 跨记录拼接检测与分割
    2. 编号备注清理（在 extract_enterprise_name 中处理）
    3. 支持中英文混合品牌名
    4. 详细调试日志
    5. 企业统计表过滤（在 find_record_boundaries 中处理）
    6. 纯字母型号回退逻辑（在 extract_model_and_name 中处理）
    
    Args:
        clean_text: 清洁后的原始文本
        debug: 是否启用所有记录的详细日志
        debug_indices: 指定启用日志的记录索引列表（如[0, 5, 10]），仅调试这些记录
    """
    # 1. 找到所有记录的边界
    boundaries = find_record_boundaries(clean_text)
    print(f"找到 {len(boundaries)} 个记录边界")
    
    records = []
    skipped = {'no_header': 0, 'no_model': 0, 'no_enterprise': 0, 'duplicate': 0, 'split': 0}
    seen = set()
    extra_records = []  # 跨记录拼接分割出的额外记录
    
    # 2. 逐段解析每条记录
    for i, boundary in enumerate(boundaries):
        start_pos = boundary['start']
        end_pos = boundaries[i + 1]['start'] if i + 1 < len(boundaries) else len(clean_text)
        
        # 提取当前记录的完整文本
        record_text = clean_text[start_pos:end_pos].strip()
        
        # 移除开头的序号和商标（支持中英文混合品牌名）
        header_pattern = r'^(\d{1,4})\s+([\u4e00-\u9fff\w\s()（）]{2,20}?牌)\s+'
        header_match = re.match(header_pattern, record_text)
        
        if not header_match:
            skipped['no_header'] += 1
            continue
        
        catalog_num = header_match.group(1)
        trademark = header_match.group(2)
        
        # 确定当前记录是否需要调试
        record_debug = debug
        if debug_indices and i in debug_indices:
            record_debug = True
        
        # 使用通用解析函数
        result = parse_record_segment(record_text, catalog_num, trademark, seen, skipped, debug=record_debug)
        
        if result is None:
            continue
        
        # 处理返回格式：(record, is_valid, extra_split_records)
        if isinstance(result, tuple) and len(result) == 3:
            record, is_valid, split_extra = result
            if is_valid and record:
                records.append(record)
                if split_extra:
                    skipped['split'] += 1
                    extra_records.extend(split_extra)
        elif isinstance(result, tuple) and len(result) == 2:
            record, is_valid = result
            if is_valid and record:
                records.append(record)
    
    # 合并额外记录（去重）
    if extra_records:
        for er in extra_records:
            key = f"{er['product_trademark']}_{er['product_model']}"
            if key not in seen:
                seen.add(key)
                records.append(er)
    
    print(f"解析完成: 有效 {len(records)} 条, 跳过 {skipped}")
    return records


def validate_parsing(records, clean_text):
    """验证解析结果质量"""
    print(f"\n{'='*60}")
    print("解析结果质量验证")
    print(f"{'='*60}")
    
    total = len(records)
    print(f"总记录数: {total}")
    
    # 统计
    enterprise_count = {}
    ent_empty = 0
    ent_truncated = 0
    
    for r in records:
        ent = r['enterprise_name']
        if not ent:
            ent_empty += 1
        else:
            enterprise_count[ent] = enterprise_count.get(ent, 0) + 1
            # 检查是否截断
            if not any(suffix in ent for suffix in ['有限公司', '股份公司', '集团', '厂']):
                ent_truncated += 1
    
    print(f"企业名为空: {ent_empty} ({ent_empty/total*100:.1f}%)" if total > 0 else "企业名为空: 0")
    print(f"企业名可能截断: {ent_truncated}")
    print(f"涉及企业: {len(enterprise_count)} 家")
    
    # 显示样本
    print(f"\n前15条样本:")
    print(f"{'序号':<6} {'商标':<10} {'产品名称':<20} {'型号':<25} {'企业名'}")
    print("-" * 110)
    for r in records[:15]:
        print(f"{r['catalog_number']:<6} {r['product_trademark']:<10} "
              f"{r['product_name']:<20} {r['product_model']:<25} "
              f"{r['enterprise_name']}")
    
    # 企业TOP15
    print(f"\n企业TOP15:")
    for ent, cnt in sorted(enterprise_count.items(), key=lambda x: -x[1])[:15]:
        print(f"  {ent}: {cnt} 条")
    
    # 截断的企业名
    truncated = [r for r in records if r['enterprise_name'] and 
                 not any(suffix in r['enterprise_name'] 
                        for suffix in ['有限公司', '股份公司', '集团', '厂'])]
    if truncated:
        print(f"\n⚠️ 可能截断的企业名（{len(truncated)} 条）:")
        for r in truncated[:5]:
            print(f"  {r['enterprise_name']} - {r['product_trademark']}")
    
    return total


def upload_to_db(records, batch_num):
    """上传到gonggao数据库"""
    batch = f'第{batch_num}批'
    db_records = []
    
    for r in records:
        db_records.append({
            'batch': batch,
            'product_trademark': r['product_trademark'],
            'product_model': r['product_model'],
            'product_name': r['product_name'],
            'enterprise_name': r['enterprise_name'],
            'catalog_number': r['catalog_number'],
            'data_source': '工信部公告(DOC)',
        })
    
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
    except Exception as e:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def main():
    print("=== 工信部DOC解析器 V2.1（优化版）===\n")
    
    # 处理的批次（使用已下载的文件）
    batches = {
        406: 'batch406_f66eea329f224580a312ab5b26b09f75.doc',
        407: 'batch407_b43b6a0d1ffb47eba041adefa8541476.doc',
    }
    
    for batch_num, doc_file in batches.items():
        doc_path = os.path.join(DOC_DIR, doc_file)
        
        if not os.path.exists(doc_path):
            print(f"批次{batch_num}: 文件不存在 {doc_path}")
            continue
        
        print(f"\n{'='*60}")
        print(f"处理第{batch_num}批")
        print(f"{'='*60}")
        
        # 1. 提取文本
        text = extract_text_from_doc(doc_path)
        clean = clean_text(text)
        print(f"文本大小: {len(clean)} 字符")
        
        # 2. 解析记录
        records = parse_records_v2(clean)
        
        # 3. 验证质量
        validate_parsing(records, clean)
        
        if records:
            # 4. 保存解析结果
            output_path = os.path.join(OUTPUT_DIR, f'batch{batch_num}_v2_parsed.json')
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
            print(f"\n解析结果已保存: {output_path}")
            
            # 5. 上传数据库
            print(f"\n上传数据库...")
            uploaded = upload_to_db(records, batch_num)
            print(f"✓ 成功上传 {uploaded} 条")
            
            # 6. 验证
            conn = psycopg2.connect(**DB_CONFIG)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM vehicle_product_publicity WHERE batch = %s", (f'第{batch_num}批',))
            count = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            print(f"数据库验证: 第{batch_num}批共 {count} 条")
        
        import time
        time.sleep(1)
    
    # 最终验证
    print(f"\n{'='*60}")
    print("最终数据库验证")
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT batch, COUNT(*) FROM vehicle_product_publicity 
        WHERE batch ~ '^第[0-9]+批$'
        GROUP BY batch 
        ORDER BY CAST(REPLACE(REPLACE(batch, '第', ''), '批', '') AS INTEGER) DESC
    """)
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]} 条")
    cursor.close()
    conn.close()


if __name__ == '__main__':
    main()
