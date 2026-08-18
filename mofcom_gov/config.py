# -*- coding: utf-8 -*-
"""mofcom_gov 商务部驻外经商处子站爬虫 - 全局配置"""
import os

# ============================================
# 数据库连接（云端 car_ershou 生产库）
# 口令不落代码：优先同目录 .env（KEY=VALUE，已 gitignore），其次环境变量
# ============================================
_DOTENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')


def _load_dotenv():
    if not os.path.exists(_DOTENV_PATH):
        return {}
    env = {}
    with open(_DOTENV_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            env[k.strip()] = v.strip()
    return env


_dotenv = _load_dotenv()


def _cfg(key, default=None):
    return _dotenv.get(key) or os.environ.get(key) or default


DB_CONFIG = {
    'host': _cfg('ERSHOU_DB_HOST', 'pgm-bp1sf8zujdx18698io.pg.rds.aliyuncs.com'),
    'port': int(_cfg('ERSHOU_DB_PORT', '5432')),
    'user': _cfg('ERSHOU_DB_USER', 'Levin001'),
    'password': _cfg('ERSHOU_DB_PASSWORD'),
    'dbname': _cfg('ERSHOU_DB_NAME', 'car_ershou'),
}

if not DB_CONFIG['password']:
    raise RuntimeError(
        '缺少数据库口令：请在 mofcom_gov/.env 配置 ERSHOU_DB_PASSWORD '
        '（参考 config/.env.example），或设置环境变量 ERSHOU_DB_PASSWORD')

# ============================================
# 反爬策略（LIGHT 档：商务部站点）
# ============================================
LIGHT = {
    'delay_min': 3,
    'delay_max': 8,
    'max_retries': 3,
    'failure_threshold': 10,
    'batch_size': 30,
    'batch_rest_min': 180,
    'batch_rest_max': 300,
}

# ============================================
# mofcom 站点标识
# webId: 全站唯一；ColId: 栏目唯一（从栏目页 meta 提取）
# ============================================
SITES = {
    # iso_alpha2(小写) -> {webId, columns: {栏目名: ColId}}
    'et': {  # 埃塞俄比亚
        'webId': 'dcf7d269d49e40878aa9e79980e07d00',
        'columns': {
            'jmxw': 'F6QQxyqqzOt5FAUJCsBJe',   # 经贸新闻
            'scdy': None,                        # 市场调研（ColId 动态获取）
            'zytz': None,                        # 重要通知
            'swhd': None,                        # 商务活动
        },
    },
    'gh': {  # 加纳
        'webId': '2c3c0ef4194c45e39d59d8e99c886e05',
        'columns': {
            'jmxw': '5uNqnLgarfMCccWlaRi2y',   # 经贸新闻
            'jstx': None,                        # 经商提示
        },
    },
    'tz': {  # 坦桑尼亚
        'webId': '230a525b41e84d4daba3de3749170789',
        'columns': {
            'jmxw': 'gwyCLzshWGQgMX3EZ1PgY',   # 经贸新闻
        },
    },
}

TPL_SET_ID = 'K9pTERPQyLAIsOP8DyBRs'

API_LIST = 'http://{site}.mofcom.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit'

SITE_HOME = 'http://{site}.mofcom.gov.cn'

# ============================================
# 关键词过滤（政策链路 T1）
# ============================================
POLICY_KEYWORDS = [
    '二手车', 'used vehicle', 'used car', '车龄', '进口禁令', '进口限制',
    '关税', '进口税', 'vehicle', '汽车', '机动车', 'right-hand', '右舵',
    '认证', 'PVoC', 'CoC', 'SONCAP', '排放', 'emission', '欧几里得',
    '欧标', '左舵', 'over age', 'age limit',
]

# 详情页正文必须含的关键词（避免标题命中但正文无关）
POLICY_BODY_KEYWORDS = ['车', 'car', 'vehicle', '关税', '进口', 'tax', 'import']
