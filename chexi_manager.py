# -*- coding: utf-8 -*-
"""
车系列表管理模块
功能：
1. 维护车系列表（JSON配置文件）
2. 添加/删除/查看车系
3. 从URL自动提取series_id
"""

import json
import os
import re
from datetime import datetime


class ChexiManager:
    """车系列表管理器"""

    CONFIG_FILE = "chexi_config.json"

    def __init__(self):
        self.config = self.load_config()

    def load_config(self):
        """加载配置文件"""
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载配置文件失败: {e}，创建新配置")
                return self.create_default_config()
        else:
            return self.create_default_config()

    def create_default_config(self):
        """创建默认配置"""
        return {
            "version": "1.0",
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "chexi_list": [
                {
                    "name": "阿维塔06",
                    "series_id": "7752",
                    "url": "https://k.autohome.com.cn/7752",
                    "status": "active",
                    "added_date": "2026-05-17",
                    "total_koubei": 253,
                    "last_crawl": "2026-05-17 10:00:00",
                    "last_count": 253
                },
                {
                    "name": "阿维塔07",
                    "series_id": "7652",
                    "url": "https://k.autohome.com.cn/7652",
                    "status": "active",
                    "added_date": "2026-05-17",
                    "total_koubei": 0,
                    "last_crawl": None,
                    "last_count": 0
                }
            ]
        }

    def save_config(self):
        """保存配置文件"""
        self.config["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存配置文件失败: {e}")
            return False

    def extract_series_id_from_url(self, url):
        """从URL提取series_id"""
        # 匹配 https://k.autohome.com.cn/xxxx 格式
        match = re.search(r'k\.autohome\.com\.cn/(\d+)', url)
        if match:
            return match.group(1)
        return None

    def add_chexi(self, name, url):
        """添加新车系"""
        # 检查是否已存在
        for chexi in self.config["chexi_list"]:
            if chexi["name"] == name or chexi["series_id"] == self.extract_series_id_from_url(url):
                print(f"车系 '{name}' 已存在")
                return False

        # 提取series_id
        series_id = self.extract_series_id_from_url(url)
        if not series_id:
            print(f"无法从URL提取series_id: {url}")
            return False

        # 添加新车系
        new_chexi = {
            "name": name,
            "series_id": series_id,
            "url": url.split('#')[0],  # 去掉#后面的参数
            "status": "active",
            "added_date": datetime.now().strftime("%Y-%m-%d"),
            "total_koubei": 0,
            "last_crawl": None,
            "last_count": 0
        }

        self.config["chexi_list"].append(new_chexi)
        self.save_config()
        print(f"车系 '{name}' 添加成功 (ID: {series_id})")
        return True

    def remove_chexi(self, index):
        """删除车系"""
        if 0 <= index < len(self.config["chexi_list"]):
            removed = self.config["chexi_list"].pop(index)
            self.save_config()
            print(f"车系 '{removed['name']}' 已删除")
            return True
        else:
            print("序号无效")
            return False

    def update_chexi_status(self, name, total_koubei=None, last_crawl=None, last_count=None):
        """更新车系状态"""
        for chexi in self.config["chexi_list"]:
            if chexi["name"] == name:
                if total_koubei is not None:
                    chexi["total_koubei"] = total_koubei
                if last_crawl is not None:
                    chexi["last_crawl"] = last_crawl
                if last_count is not None:
                    chexi["last_count"] = last_count
                self.save_config()
                return True
        return False

    def display_list(self):
        """显示车系列表"""
        print("\n" + "=" * 80)
        print(f"当前车系列表（共{len(self.config['chexi_list'])}个）")
        print("=" * 80)

        if not self.config["chexi_list"]:
            print("暂无车系")
            return

        # 表头
        print(f"{'序号':<6}{'车系名称':<12}{'车系ID':<10}{'状态':<8}{'口碑总数':<10}{'上次爬取':<20}")
        print("-" * 80)

        # 数据行
        for i, chexi in enumerate(self.config["chexi_list"], 1):
            status = "已爬取" if chexi["last_crawl"] else "未爬取"
            total = str(chexi["total_koubei"]) if chexi["total_koubei"] > 0 else "-"
            last = chexi["last_crawl"] if chexi["last_crawl"] else "-"
            print(f"{i:<6}{chexi['name']:<12}{chexi['series_id']:<10}{status:<8}{total:<10}{last:<20}")

        print("=" * 80)

    def get_chexi_by_index(self, index):
        """通过索引获取车系信息"""
        if 0 <= index < len(self.config["chexi_list"]):
            return self.config["chexi_list"][index]
        return None

    def get_all_chexi(self):
        """获取所有车系"""
        return self.config["chexi_list"]


def test():
    """测试功能"""
    manager = ChexiManager()

    while True:
        print("\n" + "=" * 40)
        print("车系列表管理")
        print("=" * 40)
        print("1. 查看车系列表")
        print("2. 添加新车系")
        print("3. 删除车系")
        print("4. 退出")

        choice = input("\n请选择: ").strip()

        if choice == "1":
            manager.display_list()

        elif choice == "2":
            name = input("车系名称: ").strip()
            url = input("网页地址: ").strip()
            if name and url:
                manager.add_chexi(name, url)
            else:
                print("名称和地址不能为空")

        elif choice == "3":
            manager.display_list()
            try:
                index = int(input("要删除的序号: ")) - 1
                manager.remove_chexi(index)
            except ValueError:
                print("请输入有效的序号")

        elif choice == "4":
            break

        else:
            print("无效选择")


if __name__ == "__main__":
    test()
