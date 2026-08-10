# -*- coding: utf-8 -*-
"""
代理池管理
当前为单代理模式，后续可扩展为代理池轮换
"""
import random

# 代理池，可按需扩展
PROXY_POOL = [
    # 示例格式，实际使用时替换为真实代理
    # {"http": "http://user:pass@host:port", "https": "http://user:pass@host:port"},
]

def get_proxy():
    """返回随机代理，无代理时返回None"""
    if not PROXY_POOL:
        return None
    return random.choice(PROXY_POOL)
