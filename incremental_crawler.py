# -*- coding: utf-8 -*-
"""
增量爬取模块 - 优化版
功能：
1. 从data_koubei表读取已有口碑ID和(时间+车主)组合
2. 爬取时过滤已存在的数据（支持多种去重方式）
3. 提前终止优化
4. 快速跳过判断：根据上次爬取时间决定是否需要爬取
"""

import pandas as pd
from sqlalchemy import text
from datetime import datetime


class IncrementalCrawler:
    """增量爬取器 - 支持多种去重方式"""

    def __init__(self, engine, chexi_name):
        self.engine = engine
        self.chexi_name = chexi_name
        self.existing_ids = set()  # 已有的koubei_id集合
        self.existing_combinations = set()  # (发表时间, 用户昵称)组合
        self.consecutive_existing_limit = 10  # 连续10条已存在则停止
        self.last_crawl_time = None  # 上次爬取时间
        self.newest_fabiao_time = None  # 数据库中最新的发表时间

    def load_existing_data(self):
        """从data_koubei加载已有数据：ID + (时间+车主)组合"""
        try:
            with self.engine.connect() as conn:
                # 加载koubei_id
                result = conn.execute(
                    text("SELECT koubei_id FROM data_koubei WHERE chexi = :chexi AND koubei_id IS NOT NULL AND koubei_id != ''"),
                    {"chexi": self.chexi_name}
                )
                self.existing_ids = {row[0] for row in result}
                
                # 加载(发表时间, 用户昵称)组合
                result = conn.execute(
                    text("SELECT fabiao_time, yonghu FROM data_koubei WHERE chexi = :chexi AND fabiao_time IS NOT NULL AND fabiao_time != ''"),
                    {"chexi": self.chexi_name}
                )
                self.existing_combinations = {(row[0], row[1]) for row in result if row[0] and row[1]}
                
                # 获取最新的发表时间（用于快速判断是否有新增数据）
                result = conn.execute(
                    text("SELECT MAX(fabiao_time) FROM data_koubei WHERE chexi = :chexi AND fabiao_time IS NOT NULL AND fabiao_time != ''"),
                    {"chexi": self.chexi_name}
                )
                row = result.fetchone()
                self.newest_fabiao_time = row[0] if row[0] else None
                
                print(f"从data_koubei加载到 {len(self.existing_ids)} 个已有口碑ID")
                print(f"加载到 {len(self.existing_combinations)} 个(时间+车主)组合")
                if self.newest_fabiao_time:
                    print(f"最新发表时间: {self.newest_fabiao_time}")
                return True
        except Exception as e:
            print(f"加载已有数据失败: {e}")
            self.existing_ids = set()
            self.existing_combinations = set()
            return False

    def check_if_needs_crawl(self, web_newest_time=None):
        """
        快速判断是否需要爬取
        如果网页上最新的口碑发表时间 <= 数据库中最新的发表时间，说明没有新增数据
        """
        if not self.newest_fabiao_time:
            return True  # 数据库为空，需要爬取
            
        if not web_newest_time:
            return True  # 无法获取网页时间，继续爬取
            
        try:
            db_time = datetime.strptime(self.newest_fabiao_time, '%Y-%m-%d')
            web_time = datetime.strptime(web_newest_time, '%Y-%m-%d')
            
            if web_time <= db_time:
                print(f"快速跳过：网页最新时间({web_newest_time}) <= 数据库最新时间({self.newest_fabiao_time})")
                return False
            else:
                print(f"需要爬取：网页最新时间({web_newest_time}) > 数据库最新时间({self.newest_fabiao_time})")
                return True
        except:
            return True

    def filter_new_koubei(self, koubei_list):
        """
        过滤出新增的口碑（优先使用koubei_id，其次使用(时间+车主)组合）
        返回: (新增列表, 已存在数量, 是否提前终止)
        """
        new_list = []
        consecutive_existing = 0
        should_stop = False

        for item in koubei_list:
            koubei_id = item.get('koubei_id', '')
            fabiao_time = item.get('fabiao_time', '')
            yonghu = item.get('yonghu', '')
            
            is_existing = False
            
            # 优先使用koubei_id判断（最准确）
            if koubei_id and koubei_id in self.existing_ids:
                is_existing = True
            # 备用方案：使用(时间+车主)组合判断
            elif fabiao_time and yonghu and (fabiao_time, yonghu) in self.existing_combinations:
                is_existing = True

            if is_existing:
                consecutive_existing += 1
                if consecutive_existing >= self.consecutive_existing_limit:
                    print(f"连续遇到 {consecutive_existing} 条已存在口碑，提前终止")
                    should_stop = True
                    break
            else:
                new_list.append(item)
                consecutive_existing = 0
                
                # 将新数据的标识加入集合（内存中，下次判断更快）
                if koubei_id:
                    self.existing_ids.add(koubei_id)
                if fabiao_time and yonghu:
                    self.existing_combinations.add((fabiao_time, yonghu))

        return new_list, consecutive_existing, should_stop

    def get_stats(self):
        """获取统计信息"""
        return {
            "existing_count": len(self.existing_ids),
            "combination_count": len(self.existing_combinations),
            "newest_fabiao_time": self.newest_fabiao_time,
            "chexi_name": self.chexi_name
        }


def test_incremental():
    """测试增量爬取逻辑"""
    from sqlalchemy import create_engine

    db_config = {
        'user': 'postgres',
        'password': '800124',
        'host': 'localhost',
        'port': 5432,
        'dbname': 'koubei'
    }

    connection_string = f'postgresql+psycopg2://{db_config["user"]}:{db_config["password"]}@{db_config["host"]}:{db_config["port"]}/{db_config["dbname"]}'
    engine = create_engine(connection_string)

    crawler = IncrementalCrawler(engine, "唐新能源")
    crawler.load_existing_data()
    print(f"\n统计: {crawler.get_stats()}")

    test_data = [
        {"koubei_id": "existing_id_1", "yonghu": "老用户A", "fabiao_time": "2026-06-01"},
        {"koubei_id": "", "yonghu": "老用户B", "fabiao_time": "2026-06-02"},  # 没有ID，但时间+车主匹配
        {"koubei_id": "new_id_123", "yonghu": "新用户1", "fabiao_time": "2026-06-18"},
        {"koubei_id": "new_id_456", "yonghu": "新用户2", "fabiao_time": "2026-06-18"},
    ]

    new_list, existing_count, should_stop = crawler.filter_new_koubei(test_data)
    print(f"\n测试结果:")
    print(f"输入: {len(test_data)} 条")
    print(f"新增: {len(new_list)} 条")
    print(f"已存在: {existing_count} 条")
    print(f"是否终止: {should_stop}")

    for item in new_list:
        print(f"  新增: {item['yonghu']} ({item['fabiao_time']})")


if __name__ == "__main__":
    test_incremental()