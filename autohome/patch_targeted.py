# -*- coding: utf-8 -*-
"""
定向重跑脚本 — 仅处理 voice_control / adas_system / lidar_brand
用法: python patch_targeted.py [--debug N]
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import psycopg2
from psycopg2.extras import RealDictCursor
from itertools import groupby
from operator import itemgetter

# 复用 patch_browser 中的类
from patch_browser import DB, BrowserPatcher, PatchScheduler, log, ANTI_CRAWL

TARGET_FIELDS = ['voice_control', 'adas_system', 'lidar_brand']

class TargetedDB(DB):
    """只获取目标字段的任务"""
    def get_pending_tasks(self, limit=None):
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        placeholders = ', '.join(['%s'] * len(TARGET_FIELDS))
        sql = f"""
            SELECT id, spec_id, field_name, current_value
            FROM patch_tasks
            WHERE status = 'pending'
            AND field_name IN ({placeholders})
            ORDER BY spec_id, id
        """
        params = TARGET_FIELDS
        if limit:
            sql += ' LIMIT %s'
            params.append(limit)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()

        tasks = []
        for spec_id, group in groupby(rows, key=itemgetter('spec_id')):
            group_list = list(group)
            tasks.append({
                'spec_id': spec_id,
                'fields': [r['field_name'] for r in group_list],
                'task_ids': [r['id'] for r in group_list],
            })
        return tasks

def main():
    import argparse
    parser = argparse.ArgumentParser(description='定向重跑关键3字段')
    parser.add_argument('--debug', type=int, metavar='N', help='调试模式，只跑 N 条')
    parser.add_argument('--no-headless', action='store_true', help='显示浏览器窗口')
    args = parser.parse_args()

    log.info('启动定向补采脚本 — 仅处理 voice_control / adas_system / lidar_brand')
    log.info(f'模式: {"debug" if args.debug else "full"}')

    db = TargetedDB()
    browser = BrowserPatcher(headless=not args.no_headless)
    scheduler = PatchScheduler(db, browser, debug=args.debug)

    try:
        scheduler.run()
    except KeyboardInterrupt:
        log.info('用户中断')
    except Exception as e:
        log.error(f'运行失败: {e}')
    finally:
        db.close()

if __name__ == '__main__':
    main()
