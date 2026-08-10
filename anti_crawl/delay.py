# -*- coding: utf-8 -*-
"""延迟策略：页面间随机等待 + 批次长休 + 启动随机延迟"""
import time
import random

def random_sleep(min_sec=3, max_sec=8):
    """页面间随机等待"""
    time.sleep(random.uniform(min_sec, max_sec))

def batch_sleep(page_count, min_pages=30, max_pages=50, min_rest=180, max_rest=300):
    """
    批次长休：每爬取一定页数后休息一段时间
    :param page_count: 当前已爬取页数
    :param min_pages/max_pages: 长休触发页数范围
    :param min_rest/max_rest: 休息秒数范围（3-5分钟）
    """
    if random.randint(min_pages, max_pages) == page_count:
        rest = random.randint(min_rest, max_rest)
        print(f"  批次长休 {rest} 秒...")
        time.sleep(rest)

def start_delay(min_sec=5, max_sec=20):
    """启动随机延迟：避免定时任务被识别"""
    delay = random.uniform(min_sec, max_sec)
    print(f"启动延迟 {delay:.1f} 秒...")
    time.sleep(delay)

def maybe_long_rest(prob=0.1, min_sec=300, max_sec=600):
    """
    概率性追加长休：模拟人离开更久
    :param prob: 触发概率，默认10%
    :param min_sec/max_sec: 休息秒数范围（5-10分钟）
    """
    if random.random() < prob:
        rest = random.randint(min_sec, max_sec)
        print(f"  概率性长休 {rest} 秒...")
        time.sleep(rest)
