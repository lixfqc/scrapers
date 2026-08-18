# -*- coding: utf-8 -*-
"""
goods_scope 判定规范（交接文档第五节）：
① 默认 '通用'（新车/二手车同税率，绝大多数）
② 源页面明确二手车专属税率栏且税率不同 -> '二手车'
③ 明确仅新车适用 -> '新车'
④ 禁止用税率倒推
⑤ 按车龄/超龄罚款阶梯、右舵惩罚、排量附加 -> tax_rule，不影响 goods_scope
返回 (goods_scope, 判定依据原文)；goods_scope != '通用' 时调用方须降置信度一档
"""
import re

# 二手车专属税率栏的关键模式（须是"关税税率栏"而非罚款/附加税描述）
USED_COLUMN_RE = re.compile(
    r'二手车[的].{0,12}税率|二手车.{0,10}关税|旧车[的].{0,12}税率|'
    r'二手车辆.{0,10}关税|used\s+(vehicles?\s+)?(duty|tariff|import\s+duty)|'
    r'second-hand\s+vehicles?.{0,15}(duty|tariff)', re.I)
# 明确仅新车适用的模式
NEW_ONLY_RE = re.compile(r'仅新车|新车适用|只对新车|new\s+vehicles?\s+only|only\s+new\s+cars', re.I)
# 超龄罚款/排量附加等 -> 提示走 tax_rule，不计入 goods_scope 判定
AGE_EXTRA_RE = re.compile(r'超龄|车龄|车龄.*罚款|overage|age\s+limit|车龄.*征收', re.I)


def judge_goods_scope(text, hs_code=None):
    """text: 税率来源描述/原文（source + note + 原文片段）
    返回 (goods_scope, evidence_原文句)
    """
    text = text or ''
    for m in NEW_ONLY_RE.finditer(text):
        return '新车', _surround(text, m.start())
    for m in USED_COLUMN_RE.finditer(text):
        return '二手车', _surround(text, m.start())
    return '通用', ''


def _surround(text, idx, pad=30):
    s = max(0, idx - pad)
    e = min(len(text), idx + pad)
    return text[s:e].strip()


def has_age_extra(text):
    """文本含超龄罚款/车龄阶梯描述 -> True（应走 tax_rule）"""
    return bool(AGE_EXTRA_RE.search(text or ''))
