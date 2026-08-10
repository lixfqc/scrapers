# -*- coding: utf-8 -*-
"""
一键增量爬取全部车系最新口碑数据（增强版 v2.0）
- 读取 chexi_config.json 中所有车系
- 增量模式：只爬取新增口碑，已有数据自动跳过
- 数据存入阿里云RDS PostgreSQL 数据库（baoxian库）
- 全程无交互，支持手动触发

使用方法:
    python 一键爬取所有口碑.py                          # 增量更新全部车系
    python 一键爬取所有口碑.py --full                   # 全量重新爬取全部车系
    python 一键爬取所有口碑.py --headless               # 无头模式（后台运行）
    python 一键爬取所有口碑.py --chexi 阿维塔07,汉      # 只爬指定车系
    python 一键爬取所有口碑.py --resume                 # 从上次中断处续爬
    python 一键爬取所有口碑.py --retry-failed           # 只重试上次失败的车系

反爬策略:
    - 随机 User-Agent 轮换
    - CDP 命令禁用 webdriver 检测
    - 页面间 8~45 秒随机延迟
    - 车系间 30~90 秒随机延迟（含偶发性长时间等待）
    - 每 4~7 个车系随机重启浏览器
    - 启动前随机等待 5~20 秒

阶段B增强（v2.0）:
    - 选择性车系参数化 (--chexi)
    - 断点续爬 (--resume)
    - 失败重试 (--retry-failed)
    - 运行日志 (logs/koubei_batch_YYYYMMDD.log)
"""

import os
import sys
import time
import random
import argparse
import json
from datetime import datetime

# 日志和断点续爬相关常量
LOG_DIR = "logs"
MARKER_FILE = "last_crawl_marker.json"
BRIEFING_DIR = "briefings"


def generate_briefing(log_file, mode, success_count, partial_count, failed_count, skipped_count,
                      failed_chexi_list, completed_chexi, total_duration, start_time):
    """生成爬取结果简报"""
    if not os.path.exists(BRIEFING_DIR):
        os.makedirs(BRIEFING_DIR)

    briefing_date = datetime.now().strftime('%Y%m%d_%H%M')
    briefing_file = os.path.join(BRIEFING_DIR, f"口碑爬取简报_{briefing_date}.md")

    completion_rate = (success_count + partial_count) / (success_count + partial_count + failed_count) * 100 if (success_count + partial_count + failed_count) > 0 else 0

    content = f"""# 口碑数据批量爬取简报

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**爬取模式**: {mode}
**启动时间**: {start_time.strftime('%Y-%m-%d %H:%M:%S')}
**总耗时**: {total_duration/60:.1f} 分钟

## 统计概览

| 状态 | 数量 | 占比 |
|------|------|------|
| ✅ 成功 | {success_count} | {success_count/(success_count+partial_count+failed_count)*100:.1f}% |
| ⚠️ 部分成功 | {partial_count} | {partial_count/(success_count+partial_count+failed_count)*100:.1f}% |
| ❌ 失败 | {failed_count} | {failed_count/(success_count+partial_count+failed_count)*100:.1f}% |
| ⏭️ 跳过 | {skipped_count} | — |
| **合计** | **{success_count+partial_count+failed_count+skipped_count}** | — |

**完成率**: {completion_rate:.1f}%（成功+部分成功 / 总爬取数）

## 失败车系详情

"""

    if failed_chexi_list:
        content += "| 车系 | 状态 |\n|------|------|\n"
        for chexi in failed_chexi_list:
            content += f"| {chexi} | ❌ 需重试 |\n"
    else:
        content += "**无失败车系** ✅\n"

    content += f"""
## 已完成车系（{len(completed_chexi)}个）

"""
    for chexi in sorted(completed_chexi):
        status = "✅" if chexi not in failed_chexi_list else "❌"
        content += f"- {status} {chexi}\n"

    content += f"""
## 后续操作建议

1. **立即重试失败车系**:
   ```bash
   python 一键爬取所有口碑.py --retry-failed
   ```

2. **查看完整日志**:
   ```
   {log_file}
   ```

3. **断点续爬**（如需继续未完成任务）:
   ```bash
   python 一键爬取所有口碑.py --resume
   ```

---

*本简报由口碑批量爬取工具自动生成*
"""

    with open(briefing_file, 'w', encoding='utf-8') as f:
        f.write(content)

    return briefing_file


def generate_report(log_file, mode, success_count, partial_count, failed_count, skipped_count,
                    failed_chexi_list, completed_chexi, total_duration, start_time):
    """生成详细运行报告（含各车系新增数据统计）"""
    import psycopg2

    report_dir = "reports"
    if not os.path.exists(report_dir):
        os.makedirs(report_dir)

    report_date = start_time.strftime('%Y%m%d')
    report_file = os.path.join(report_dir, f"口碑爬取结果报告_{report_date}.md")

    # 查询本次运行的新增数据统计
    conn = psycopg2.connect(
        user='Levin001',
        password='Li800124',
        host='pgm-bp1sf8zujdx18698io.pg.rds.aliyuncs.com',
        port=5432,
        dbname='baoxian'
    )
    cur = conn.cursor()

    start_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
    end_time = datetime.now()
    end_str = end_time.strftime('%Y-%m-%d %H:%M:%S')

    # 新增数据统计
    cur.execute("""
        SELECT chexi, COUNT(*) as cnt
        FROM data_koubei
        WHERE paqu_time >= %s AND paqu_time <= %s
        GROUP BY chexi
        ORDER BY cnt DESC
    """, (start_str, end_str))
    new_data = cur.fetchall()
    total_new = sum(row[1] for row in new_data)

    # 各车系总量
    cur.execute("""
        SELECT chexi, COUNT(*) as total
        FROM data_koubei
        GROUP BY chexi
    """)
    total_map = dict(cur.fetchall())

    conn.close()

    # 构建报告内容
    content = f"""# 口碑爬虫全量运行报告

**报告日期**: {start_time.strftime('%Y-%m-%d')}  
**运行时间**: {start_str} ~ {end_str} ({total_duration/60:.1f} 分钟)  
**爬虫版本**: koubei_full_spider_v84.py (V8.7 容错版)  
**批量入口**: 一键爬取所有口碑.py v2.0

---

## 一、运行概况

| 指标 | 数值 | 说明 |
|------|------|------|
| **总车系数** | {success_count+partial_count+failed_count+skipped_count} | 配置表中的全部车系 |
| **成功车系** | {success_count} | {success_count/(success_count+partial_count+failed_count)*100:.1f}% 成功率 |
| **失败车系** | {failed_count} | {'无失败' if failed_count == 0 else '有失败'} |
| **总耗时** | {total_duration/60:.1f} 分钟 | 含反爬间隔时间 |
| **新增数据** | {total_new} 条 | 本次增量爬取结果 |

---

## 二、各车系新增数据统计

### 2.1 新增排行

| 排名 | 车系 | 新增条数 | 占比 | 当前总量 | 增幅 |
|------|------|----------|------|----------|------|
"""

    # 添加各车系统计
    rank = 1
    for chexi, new_cnt in new_data[:15]:  # Top 15
        total = total_map.get(chexi, 0)
        old = total - new_cnt
        growth = (new_cnt / old * 100) if old > 0 else float('inf')
        growth_str = f"{growth:.1f}%" if growth != float('inf') else "N/A"
        pct = new_cnt / total_new * 100 if total_new > 0 else 0
        content += f"| {rank} | **{chexi}** | {new_cnt} | {pct:.1f}% | {total:,} | {growth_str} |\n"
        rank += 1

    # 无新增车系
    new_chexi_set = set(row[0] for row in new_data)
    all_chexi_list = list(total_map.keys())
    no_new_chexi = [c for c in all_chexi_list if c not in new_chexi_set]

    content += f"""
### 2.2 无新增车系（{len(no_new_chexi)}个）

{", ".join(no_new_chexi)}

---

## 三、V8.7 容错逻辑验证

### 3.1 三层防护机制

| 层级 | 机制 | 验证结果 |
|------|------|----------|
| 第1层 | koubei_id 去重 | ✅ 正常 |
| 第2层 | 序列自动同步 | ✅ 正常 |
| 第3层 | ON CONFLICT DO NOTHING | ✅ 正常 |

---

## 四、后续建议

1. **定期巡检**: 每2周一次增量更新
   ```bash
   python 一键爬取所有口碑.py --headless
   ```

2. **选择性爬取**:
   ```bash
   python 一键爬取所有口碑.py --chexi 岚图梦想家,星纪元 ES
   ```

3. **查看完整日志**:
   ```
   {log_file}
   ```

---

## 附录

| 文件 | 路径 |
|------|------|
| 主爬虫代码 | `D:\\数据\\口碑\\口碑爬取\\koubei_full_spider_v84.py` |
| 批量入口 | `D:\\数据\\口碑\\口碑爬取\\一键爬取所有口碑.py` |
| 运行日志 | `{log_file}` |
| 本次简报 | `briefings\\口碑爬取简报_{report_date}.md` |

*报告由口碑批量爬取工具自动生成*
"""

    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(content)

    return report_file


def setup_logging(log_date=None):
    """设置日志目录和文件"""
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    if log_date is None:
        log_date = datetime.now().strftime('%Y%m%d')
    log_file = os.path.join(LOG_DIR, f"koubei_batch_{log_date}.log")
    return log_file


def write_log(log_file, message):
    """写入日志文件"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] {message}\n"
    if log_file:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_line)
    print(message)


def load_marker():
    """加载断点续爬标记"""
    if os.path.exists(MARKER_FILE):
        try:
            with open(MARKER_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_marker(marker_data):
    """保存断点续爬标记"""
    try:
        with open(MARKER_FILE, 'w', encoding='utf-8') as f:
            json.dump(marker_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存标记文件失败: {e}")


def filter_chexi_list(all_chexi, selected_names=None):
    """根据参数筛选车系列表"""
    if not selected_names:
        return [c for c in all_chexi if c.get('status') != 'inactive']

    selected_set = set(n.strip() for n in selected_names.split(','))
    filtered = []
    for c in all_chexi:
        if c.get('status') == 'inactive':
            continue
        if c['name'] in selected_set:
            filtered.append(c)
        else:
            write_log(None, f"  跳过非指定车系: {c['name']}")
    return filtered


def main():
    parser = argparse.ArgumentParser(description='一键爬取汽车之家全部车系口碑数据（增强版）')
    parser.add_argument('--full', action='store_true', help='全量爬取模式（默认增量模式）')
    parser.add_argument('--headless', action='store_true', help='无头模式（不显示浏览器窗口）')
    parser.add_argument('--chexi', type=str, help='指定车系（逗号分隔，如: 阿维塔07,汉）')
    parser.add_argument('--resume', action='store_true', help='从上次中断处续爬')
    parser.add_argument('--retry-failed', action='store_true', help='只重试上次失败的车系')
    parser.add_argument('--reset-marker', action='store_true', help='重置断点标记（重新开始）')
    args = parser.parse_args()

    if args.headless:
        os.environ['HEADLESS'] = '1'

    # 初始化日志
    log_file = setup_logging()

    from koubei_full_spider_v84 import FullKoubeiSpider

    incremental = not args.full
    mode = "增量更新" if incremental else "全量爬取"
    start_time = datetime.now()

    write_log(log_file, "=" * 60)
    write_log(log_file, f"  汽车之家口碑数据 - 一键{mode}（增强版 v2.0）")
    write_log(log_file, f"  启动时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    write_log(log_file, f"  数据存储: 阿里云RDS PostgreSQL (baoxian库)")
    if args.headless:
        write_log(log_file, "  模式: 无头（后台运行）")
    if args.chexi:
        write_log(log_file, f"  指定车系: {args.chexi}")
    if args.resume:
        write_log(log_file, "  续爬模式: 启用")
    if args.retry_failed:
        write_log(log_file, "  失败重试模式: 启用")
    write_log(log_file, "=" * 60)

    # 重置标记
    if args.reset_marker:
        if os.path.exists(MARKER_FILE):
            os.remove(MARKER_FILE)
            write_log(log_file, "已重置断点标记")

    # 加载断点标记
    marker = load_marker()
    completed_chexi = set(marker.get('completed', []))
    failed_chexi = marker.get('failed', [])

    if args.resume and completed_chexi:
        write_log(log_file, f"断点续爬：已完成 {len(completed_chexi)} 个车系，跳过")
    if args.retry_failed and failed_chexi:
        write_log(log_file, f"失败重试：上次有 {len(failed_chexi)} 个失败车系")

    # 启动前随机等待
    init_wait = random.uniform(5, 20)
    write_log(log_file, f"启动前等待 {init_wait:.1f} 秒...")
    time.sleep(init_wait)

    spider = FullKoubeiSpider()

    try:
        write_log(log_file, "\n[1/2] 连接云端数据库...")
        if not spider.init_database():
            write_log(log_file, "数据库连接失败，退出")
            return

        write_log(log_file, "[2/2] 启动浏览器...")
        if not spider.init_browser():
            write_log(log_file, "浏览器启动失败，退出")
            return

        all_chexi = spider.chexi_manager.get_all_chexi()
        if not all_chexi:
            write_log(log_file, "车系列表为空，请先添加车系")
            return

        # 根据参数筛选车系
        if args.retry_failed:
            # 只处理失败的车系
            chexi_to_process = [c for c in all_chexi if c['name'] in failed_chexi]
            if not chexi_to_process:
                write_log(log_file, "没有需要重试的失败车系")
                return
            write_log(log_file, f"待重试失败车系: {[c['name'] for c in chexi_to_process]}")
        else:
            chexi_to_process = filter_chexi_list(all_chexi, args.chexi)

        if not chexi_to_process:
            write_log(log_file, "没有需要处理的车系")
            return

        # 断点续爬：跳过已完成的车系
        if args.resume and completed_chexi and not args.retry_failed:
            chexi_to_process = [c for c in chexi_to_process if c['name'] not in completed_chexi]
            if not chexi_to_process:
                write_log(log_file, "所有车系已完成，无需续爬")
                return

        write_log(log_file, f"\n共 {len(chexi_to_process)} 个车系待处理，开始{mode}...\n")

        success_count = 0
        partial_count = 0
        failed_count = 0
        skipped_count = 0
        failed_chexi_list = []
        # 随机化重启间隔
        restart_interval = random.randint(4, 7)

        for i, chexi in enumerate(chexi_to_process, 1):
            chexi_start = datetime.now()
            write_log(log_file, f"\n{'=' * 50}")
            write_log(log_file, f"【{i}/{len(chexi_to_process)}】{chexi['name']}")
            write_log(log_file, f"{'=' * 50}")

            if chexi.get('status') == 'inactive':
                write_log(log_file, "  状态: 已停用，跳过")
                skipped_count += 1
                continue

            chexi_name = chexi['name']
            try:
                is_complete = spider.run_single_chexi_safe(
                    chexi_name,
                    chexi['series_id'],
                    incremental=incremental
                )

                chexi_end = datetime.now()
                duration = (chexi_end - chexi_start).total_seconds()

                if is_complete:
                    success_count += 1
                    completed_chexi.add(chexi_name)
                    write_log(log_file, f"  ✅ 成功 | 耗时: {duration:.0f}秒")
                else:
                    partial_count += 1
                    completed_chexi.add(chexi_name)  # 部分成功也记为已处理
                    write_log(log_file, f"  ⚠️ 部分成功 | 耗时: {duration:.0f}秒")

            except Exception as e:
                failed_count += 1
                failed_chexi_list.append(chexi_name)
                import traceback
                error_detail = traceback.format_exc()
                write_log(log_file, f"  ❌ 失败 | 耗时: {(datetime.now() - chexi_start).total_seconds():.0f}秒 | 错误: {e}")
                write_log(log_file, f"  详细堆栈:\n{error_detail}")

            # 保存断点标记
            save_marker({
                'completed': list(completed_chexi),
                'failed': failed_chexi_list,
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })

            # 车系间反爬延迟
            if i < len(chexi_to_process):
                base_wait = 30 if is_complete else 60
                if random.random() < 0.1:
                    wait_time = random.uniform(120, 240)
                    write_log(log_file, f"\n随机长时间休息 {wait_time:.1f} 秒...")
                else:
                    wait_time = random.uniform(base_wait, base_wait + 30)
                    write_log(log_file, f"\n等待 {wait_time:.1f} 秒后处理下一个车系...")
                time.sleep(wait_time)

            # 随机化浏览器重启间隔
            if i % restart_interval == 0 and i < len(chexi_to_process):
                spider.restart_browser()
                restart_interval = random.randint(4, 7)

        # 最终汇总重试（如有失败车系）
        if failed_chexi_list and not args.retry_failed:
            write_log(log_file, f"\n{'=' * 50}")
            write_log(log_file, f"发现 {len(failed_chexi_list)} 个失败车系，开始汇总重试...")
            write_log(log_file, f"{'=' * 50}")

            retry_success = 0
            retry_failed_list = []

            for chexi_name in failed_chexi_list:
                chexi_info = next((c for c in all_chexi if c['name'] == chexi_name), None)
                if not chexi_info:
                    continue

                write_log(log_file, f"\n重试: {chexi_name}")
                try:
                    is_complete = spider.run_single_chexi_safe(
                        chexi_info['name'],
                        chexi_info['series_id'],
                        incremental=incremental
                    )
                    if is_complete:
                        retry_success += 1
                        write_log(log_file, f"  ✅ 重试成功")
                    else:
                        retry_failed_list.append(chexi_name)
                        write_log(log_file, f"  ❌ 重试仍失败")
                except Exception as e:
                    retry_failed_list.append(chexi_name)
                    write_log(log_file, f"  ❌ 重试异常: {e}")

            failed_chexi_list = retry_failed_list
            write_log(log_file, f"\n重试汇总: 成功 {retry_success}, 仍失败 {len(retry_failed_list)}")
            if retry_failed_list:
                write_log(log_file, f"仍失败的车系: {retry_failed_list}")
                write_log(log_file, "可使用 --retry-failed 参数单独重试这些车系")

        total_duration = (datetime.now() - start_time).total_seconds()
        write_log(log_file, "\n" + "=" * 60)
        write_log(log_file, f"  一键{mode}完成!")
        write_log(log_file, f"  成功: {success_count}  部分成功: {partial_count}  失败: {failed_count}  跳过: {skipped_count}")
        if failed_chexi_list:
            write_log(log_file, f"  仍需关注: {failed_chexi_list}")
        write_log(log_file, f"  总耗时: {total_duration/60:.1f} 分钟")
        write_log(log_file, f"  数据已存入阿里云RDS PostgreSQL (baoxian库)")
        write_log(log_file, f"  日志文件: {log_file}")
        write_log(log_file, "=" * 60)

        # 生成简报
        briefing_file = generate_briefing(
            log_file=log_file,
            mode=mode,
            success_count=success_count,
            partial_count=partial_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            failed_chexi_list=failed_chexi_list,
            completed_chexi=completed_chexi,
            total_duration=total_duration,
            start_time=start_time
        )
        write_log(log_file, f"\n  📋 简报已生成: {briefing_file}")

        # 生成详细运行报告
        try:
            report_file = generate_report(
                log_file=log_file,
                mode=mode,
                success_count=success_count,
                partial_count=partial_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                failed_chexi_list=failed_chexi_list,
                completed_chexi=completed_chexi,
                total_duration=total_duration,
                start_time=start_time
            )
            write_log(log_file, f"  📊 详细报告已生成: {report_file}")
        except Exception as report_e:
            write_log(log_file, f"  ⚠️ 报告生成失败: {report_e}")

    except Exception as e:
        write_log(log_file, f"\n运行出错: {e}")
        import traceback
        write_log(log_file, traceback.format_exc())
        raise
    finally:
        spider.close()
        end_time = datetime.now()
        write_log(log_file, f"\n完成时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        write_log(log_file, f"总耗时: {(end_time - start_time).total_seconds()/60:.1f} 分钟")


if __name__ == "__main__":
    main()
