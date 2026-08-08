# -*- coding: utf-8 -*-
"""
重试与熔断：指数退避重试 + 连续失败熔断
"""
import time
import random

class CircuitBreaker:
    """连续失败熔断器"""
    def __init__(self, threshold=5):
        self.threshold = threshold
        self.failures = 0

    def record_failure(self):
        self.failures += 1
        if self.failures >= self.threshold:
            raise RuntimeError(f"连续失败 {self.failures} 次，触发熔断，停止本轮")

    def record_success(self):
        self.failures = 0

def retry_request(func, *args, max_retries=3, **kwargs):
    """
    指数退避重试：等待 1s → 2s → 4s
    使用示例：
        result = retry_request(requests.get, url, timeout=10)
    """
    for attempt in range(max_retries):
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt  # 1, 2, 4
            jitter = random.uniform(0, 1)
            print(f"  请求失败，{wait+jitter:.1f}s 后重试 ({attempt+1}/{max_retries}): {e}")
            time.sleep(wait + jitter)
