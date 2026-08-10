# -*- coding: utf-8 -*-
"""
一键增量爬取全部车系最新口碑数据
- 读取 chexi_config.json 中所有车系
- 增量模式：只爬取新增口碑，已有数据自动跳过
- 数据存入本地 PostgreSQL 数据库
- 全程无交互，支持手动触发

使用方法:
    python 一键爬取所有口碑.py              # 增量更新全部车系
    python 一键爬取所有口碑.py --full       # 全量重新爬取全部车系
    python 一键爬取所有口碑.py --headless   # 无头模式（后台运行）

反爬策略:
    - 随机 User-Agent 轮换
    - CDP 命令禁用 webdriver 检测
    - 页面间 8~45 秒随机延迟
    - 车系间 30~90 秒随机延迟（含偶发性长时间等待）
    - 每 4~7 个车系随机重启浏览器
    - 启动前随机等待 5~20 秒
"""

import os
import time
import random
import argparse
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description='一键爬取汽车之家全部车系口碑数据')
    parser.add_argument('--full', action='store_true', help='全量爬取模式（默认增量模式）')
    parser.add_argument('--headless', action='store_true', help='无头模式（不显示浏览器窗口）')
    args = parser.parse_args()

    if args.headless:
        os.environ['HEADLESS'] = '1'

    from koubei_full_spider_v84 import FullKoubeiSpider

    incremental = not args.full
    mode = "增量更新" if incremental else "全量爬取"
    print("=" * 60)
    print(f"  汽车之家口碑数据 - 一键{mode}")
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  数据存储: 本地 PostgreSQL (localhost:5432/koubei)")
    if args.headless:
        print("  模式: 无头（后台运行）")
    print("=" * 60)

    # 启动前随机等待，避免定时任务形成固定模式
    init_wait = random.uniform(5, 20)
    print(f"\n启动前等待 {init_wait:.1f} 秒...")
    time.sleep(init_wait)

    spider = FullKoubeiSpider()

    try:
        print("\n[1/2] 连接本地数据库...")
        if not spider.init_database():
            print("数据库连接失败，退出")
            return

        print("[2/2] 启动浏览器...")
        if not spider.init_browser():
            print("浏览器启动失败，退出")
            return

        all_chexi = spider.chexi_manager.get_all_chexi()
        if not all_chexi:
            print("车系列表为空，请先添加车系")
            return

        print(f"\n共 {len(all_chexi)} 个车系待处理，开始{mode}...\n")

        success_count = 0
        partial_count = 0
        skipped_count = 0
        # 随机化重启间隔：每 4~7 个车系重启一次
        restart_interval = random.randint(4, 7)

        for i, chexi in enumerate(all_chexi, 1):
            print(f"\n{'=' * 50}")
            print(f"【{i}/{len(all_chexi)}】{chexi['name']}")
            print(f"{'=' * 50}")

            if chexi.get('status') == 'inactive':
                print("  状态: 已停用，跳过")
                skipped_count += 1
                continue

            is_complete = spider.run_single_chexi_safe(
                chexi["name"],
                chexi["series_id"],
                incremental=incremental
            )

            if is_complete:
                success_count += 1
            else:
                partial_count += 1

            # 车系间反爬延迟
            if i < len(all_chexi):
                # 部分成功时等待更久，降低触发风控的概率
                base_wait = 30 if is_complete else 60
                # 10% 概率触发长时间休息（模拟人离开电脑）
                if random.random() < 0.1:
                    wait_time = random.uniform(120, 240)
                    print(f"\n随机长时间休息 {wait_time:.1f} 秒...")
                else:
                    wait_time = random.uniform(base_wait, base_wait + 30)
                    print(f"\n等待 {wait_time:.1f} 秒后处理下一个车系...")
                time.sleep(wait_time)

            # 随机化浏览器重启间隔
            if i % restart_interval == 0 and i < len(all_chexi):
                spider.restart_browser()
                restart_interval = random.randint(4, 7)  # 下个区间随机

        print("\n" + "=" * 60)
        print(f"  一键{mode}完成!")
        print(f"  成功: {success_count}  部分成功: {partial_count}  跳过: {skipped_count}")
        print(f"  数据已存入本地 PostgreSQL (localhost:5432/koubei)")
        print("=" * 60)

    except Exception as e:
        print(f"\n运行出错: {e}")
        raise
    finally:
        spider.close()
        print(f"\n完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
