# -*- coding: utf-8 -*-
"""
统一反爬工具箱
各爬虫直接 import 使用，避免重复实现
"""
from .ua_pool import get_random_ua
from .delay import random_sleep, batch_sleep
from .retry import retry_request, CircuitBreaker
from .proxy import get_proxy
