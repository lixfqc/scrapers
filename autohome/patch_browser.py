# -*- coding: utf-8 -*-
"""
配置表 CSS 混淆字段补采脚本 v1
- 使用 Playwright 浏览器渲染汽车之家配置页
- 提取 6 个字段的真实值：voice_control, lidar_brand, adas_system, drive_section, hd_map, assist_image
- 对比数据库当前值，不同则修复
- 支持断点续采、反爬策略

用法:
  python patch_browser.py                    # 全量运行
  python patch_browser.py --debug 5          # 调试模式，只跑5条
  python patch_browser.py --dry-run          # 只查不写，看哪些任务会被执行
"""
import sys, os, re, time, random, logging, json, argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import groupby
from operator import itemgetter

import psycopg2
from psycopg2.extras import RealDictCursor
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ==================== 配置 ====================
DB_CONFIG = dict(
    host='pgm-bp1sf8zujdx18698io.pg.rds.aliyuncs.com',
    port=5432,
    user='Levin001',
    password='Li800124',
    dbname='peizhibiao',
)

BASE_URL = 'https://www.autohome.com.cn/config/spec/{spec_id}.html'

# 6 个待补采字段
TARGET_FIELDS = ['voice_control', 'lidar_brand', 'adas_system', 'drive_section', 'hd_map', 'assist_image']

# 页面标签 → 字段名 映射（按方案第四章 4.1）
LABEL_MAP = {
    '辅助驾驶系统': 'adas_system',
    '辅助驾驶路段': 'drive_section',
    '语音识别控制系统': 'voice_control',
    '语音控制': 'voice_control',  # 备选标签
    '激光雷达品牌': 'lidar_brand',
    '激光雷达品牌（选填）': 'lidar_brand',
    '地图品牌': 'hd_map',
    '驾驶辅助影像': 'assist_image',
    '辅助驾驶影像': 'assist_image',
}

# UA 池（复用 scraper_v7）
UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
]

# 反爬延迟配置（单位：秒）
ANTI_CRAWL = {
    'startup_delay': (10, 20),          # 启动随机延迟
    'page_delay': (3, 8),               # 页面间延迟
    'batch_rest': (120, 240),           # 每30-50页休息2-4分钟
    'batch_size': (30, 50),             # 批次大小范围
    'error_backoff': [1, 2, 4],         # 指数退避
    'max_consecutive_errors': 5,        # 连续失败熔断
    'page_timeout': 30000,              # 页面超时30秒
}

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    handlers=[
        logging.FileHandler('patch_browser.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger('patch_browser')

# ==================== 数据库层 ====================
class DB:
    """数据库操作封装"""
    def __init__(self):
        self.conn = psycopg2.connect(**DB_CONFIG)
        self.conn.autocommit = False

    def get_pending_tasks(self, limit=None):
        """获取待处理任务，按 spec_id 分组"""
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        sql = """
            SELECT id, spec_id, field_name, current_value
            FROM patch_tasks
            WHERE status = 'pending'
            ORDER BY spec_id, id
        """
        if limit:
            sql += f' LIMIT {limit}'
        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()

        # 按 spec_id 分组
        tasks = []
        for spec_id, group in groupby(rows, key=itemgetter('spec_id')):
            group_list = list(group)
            tasks.append({
                'spec_id': spec_id,
                'fields': [r['field_name'] for r in group_list],
                'task_ids': [r['id'] for r in group_list],
            })
        return tasks

    def get_current_values(self, spec_id, fields):
        """从 data_peizhibiao 读取当前值"""
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        placeholders = ', '.join(['%s'] * len(fields))
        sql = f'SELECT {placeholders} FROM data_peizhibiao WHERE spec_id = %s'
        cur.execute(sql, fields + [spec_id])
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else {}

    def update_peizhibiao(self, spec_id, field, new_value):
        """更新 data_peizhibiao（自动截断超长值）"""
        # 字段长度限制（与数据库 schema 一致）
        field_limits = {
            'drive_section': 100,
            'voice_control': 50,
            'hd_map': 50,
            'assist_image': 50,
            'adas_system': 200,
            'lidar_brand': 200,
        }
        limit = field_limits.get(field)
        if limit and len(new_value) > limit:
            new_value = new_value[:limit - 3] + '...'
            log.warning(f'值截断: {field} 超过 {limit} 字符')
        
        cur = self.conn.cursor()
        cur.execute(
            f'UPDATE data_peizhibiao SET "{field}" = %s, updated_at = %s WHERE spec_id = %s',
            (new_value, datetime.now(), spec_id)
        )
        self.conn.commit()
        cur.close()

    def insert_repair_log(self, spec_id, field, old_value, new_value, method='browser_patch', confidence='high'):
        """插入修复日志"""
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO repair_log (spec_id, field_name, old_value, new_value, repair_method, confidence)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (spec_id, field, old_value, new_value, method, confidence))
        self.conn.commit()
        cur.close()

    def mark_task_done(self, task_ids):
        """标记任务完成"""
        cur = self.conn.cursor()
        cur.execute(
            'UPDATE patch_tasks SET status = %s, patched_at = %s WHERE id = ANY(%s)',
            ('done', datetime.now(), task_ids)
        )
        self.conn.commit()
        cur.close()

    def mark_task_failed(self, task_ids, error_msg=''):
        """标记任务失败"""
        cur = self.conn.cursor()
        cur.execute(
            'UPDATE patch_tasks SET status = %s, error_msg = %s, retry_count = retry_count + 1 WHERE id = ANY(%s)',
            ('failed', error_msg, task_ids)
        )
        self.conn.commit()
        cur.close()

    def get_stats(self):
        """获取统计"""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT status, COUNT(*) FROM patch_tasks GROUP BY status
        """)
        stats = {r[0]: r[1] for r in cur.fetchall()}
        cur.close()
        return stats

    def close(self):
        self.conn.close()


# ==================== 浏览器层 ====================
class BrowserPatcher:
    """Playwright 浏览器补采器"""

    def __init__(self, headless=True):
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.error_count = 0
        self.page_count = 0

    def start(self):
        """启动浏览器（优先用系统已安装的 Chrome）"""
        self.playwright = sync_playwright().start()
        chrome_path = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            executable_path=chrome_path,
            args=['--disable-blink-features=AutomationControlled'],
        )
        self.context = self.browser.new_context(
            user_agent=random.choice(UA_POOL),
            viewport={'width': 1920, 'height': 1080},
            locale='zh-CN',
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(ANTI_CRAWL['page_timeout'])

    def stop(self):
        """关闭浏览器"""
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass

    def rotate_ua(self):
        """轮换 UA"""
        if self.context:
            self.context.set_extra_http_headers({'User-Agent': random.choice(UA_POOL)})

    def sleep(self, delay_range):
        """随机延迟"""
        low, high = delay_range
        sec = random.uniform(low, high)
        log.info(f'  随机延迟 {sec:.1f}s')
        time.sleep(sec)

    def should_rest(self):
        """判断是否需要批次休息"""
        if self.page_count > 0 and self.page_count % random.randint(*ANTI_CRAWL['batch_size']) == 0:
            self.sleep(ANTI_CRAWL['batch_rest'])
            self.page_count = 0  # 重置计数

    def extract_fields(self, spec_id):
        """
        打开配置页，提取 6 个字段的真实值
        返回 dict: {field_name: real_value}
        """
        url = BASE_URL.format(spec_id=spec_id)
        fields = {}

        try:
            self.page.goto(url, wait_until='networkidle')
            self.page_count += 1

            # 检查是否被反爬（验证码页）
            if '验证码' in self.page.title() or 'captcha' in self.page.content().lower():
                raise Exception('疑似触发验证码，需人工处理')

            # 使用 JavaScript 直接获取渲染后的纯文本
            # 核心策略: 优先提取 style_col_sub__1tg7Z 子元素（最干净），无 sub 元素时回退到解析列文本
            js_code = """
                (labels) => {
                    const results = {};
                    const rows = document.querySelectorAll('.style_row__XPu4s');
                    
                    for (const row of rows) {
                        const cols = row.querySelectorAll('.style_col__xFg86');
                        if (cols.length < 2) continue;
                        
                        const labelEl = cols[0];
                        const label = labelEl ? labelEl.innerText.trim() : '';
                        
                        if (!labels.includes(label)) continue;
                        
                        const valueParts = [];
                        const seen = new Set();
                        
                        for (let i = 1; i < cols.length; i++) {
                            const col = cols[i];
                            if (!col) continue;
                            
                            const subs = col.querySelectorAll('.style_col_sub__1tg7Z');
                            if (subs.length > 0) {
                                // 优先用 sub 元素的 innerText（干净，无 CSS 噪声）
                                for (const sub of subs) {
                                    const t = sub.innerText.trim();
                                    if (t && t !== '-' && !seen.has(t)) {
                                        seen.add(t);
                                        valueParts.push(t);
                                    }
                                }
                            } else {
                                // 回退: 用 col.innerText 按换行/分隔符拆分
                                const raw = col.innerText.trim();
                                if (raw && raw !== '-') {
                                    raw.split(/[\\n，,、]/).forEach(t => {
                                        t = t.trim();
                                        if (t && t !== '-' && !seen.has(t)) {
                                            seen.add(t);
                                            valueParts.push(t);
                                        }
                                    });
                                }
                            }
                        }
                        
                        if (valueParts.length > 0) {
                            results[label] = valueParts.join('，');
                        }
                    }
                    
                    return results;
                }
            """
            
            results = self.page.evaluate(js_code, list(LABEL_MAP.keys()))
            
            for label, field in LABEL_MAP.items():
                if label in results:
                    raw = results[label]
                    fields[field] = self._clean_value(raw, field)
                elif field not in fields:
                    fields[field] = None

            return fields

        except PlaywrightTimeout:
            raise Exception('页面加载超时')
        except Exception as e:
            raise Exception(f'提取失败: {e}')

    def _join_value(self, parts, field):
        """合并多列/子项值为最终存储格式"""
        if not parts:
            return None

        # 去重保序
        seen = set()
        unique = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                unique.append(p)

        value = ' '.join(unique) if field == 'drive_section' else '，'.join(unique)

        # 清理噪声
        return self._clean_value(value, field)

    def _clean_value(self, value, field):
        """清理提取到的值 — 分字段精细化处理 + 清洗后去重"""
        if not value:
            return None

        cleaned = value

        # === 分字段清洗 ===
        if field == 'lidar_brand':
            # 去除品牌名后的中文噪声 (如 "HUAWEI华为" → "HUAWEI", "HUAWEI华" → "HUAWEI")
            cleaned = re.sub(r'华$', '', cleaned)
            cleaned = re.sub(r'(HUAWEI)[\u4e00-\u9fff]+', r'\1', cleaned)
            cleaned = re.sub(r'[\s，,]+', '', cleaned).strip()

        elif field == 'adas_system':
            # 去除版本描述后缀
            cleaned = re.sub(r'[，,]?\s*(视觉版|激光版)\s*[，,]?', '，', cleaned)
            cleaned = re.sub(r'[，,]+$', '', cleaned)
            # 统一分隔符
            cleaned = re.sub(r'[,，、;；]+', '，', cleaned)
            cleaned = re.sub(r'^[，,、]+', '', cleaned)
            cleaned = re.sub(r'[，,、]+$', '', cleaned)

        elif field == 'voice_control':
            cleaned = re.sub(r'[,，、;；]+', '，', cleaned)
            cleaned = re.sub(r'^[，,、]+', '', cleaned)
            cleaned = re.sub(r'[，,、]+$', '', cleaned)

        elif field == 'drive_section':
            cleaned = re.sub(r'[●○]', '', cleaned)
            cleaned = re.sub(r'[\s,，、]+', ' ', cleaned).strip()
            cleaned = re.sub(r'\s*(标配|选配)$', '', cleaned).strip()

        elif field == 'hd_map':
            cleaned = re.sub(r'[,，、;；]+', '，', cleaned)
            cleaned = re.sub(r'^[，,、]+', '', cleaned)
            cleaned = re.sub(r'[，,、]+$', '', cleaned)

        elif field == 'assist_image':
            cleaned = re.sub(r'[,，、;；]+', '，', cleaned)
            cleaned = re.sub(r'^[，,、]+', '', cleaned)
            cleaned = re.sub(r'[，,、]+$', '', cleaned)

        # 通用: 去除多余空白
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        # === 清洗后去重 (分隔符归一化后可能产生重复) ===
        if cleaned and field != 'drive_section':
            items = [x.strip() for x in cleaned.split('，') if x.strip()]
            seen = set()
            unique = []
            for item in items:
                if item not in seen:
                    seen.add(item)
                    unique.append(item)
            cleaned = '，'.join(unique)
        elif cleaned and field == 'drive_section':
            items = [x.strip() for x in cleaned.split(' ') if x.strip()]
            seen = set()
            unique = []
            for item in items:
                if item not in seen:
                    seen.add(item)
                    unique.append(item)
            cleaned = ' '.join(unique)

        # 空值判定
        if not cleaned or cleaned in ('暂无', '-', '--', '—'):
            return None

        return cleaned


# ==================== 调度层 ====================
class PatchScheduler:
    """补采调度器"""

    def __init__(self, db, browser, debug=False, dry_run=False):
        self.db = db
        self.browser = browser
        self.debug = debug
        self.dry_run = dry_run
        self.stats = {
            'total': 0,
            'success': 0,
            'no_change': 0,
            'failed': 0,
            'skipped': 0,
            'new_names': [],  # 新发现的名称库条目
        }

    def run(self):
        """执行补采"""
        # 启动浏览器
        self.browser.start()

        try:
            # 获取任务
            tasks = self.db.get_pending_tasks()
            self.stats['total'] = sum(len(t['fields']) for t in tasks)
            log.info(f'待补采任务: {len(tasks)} 个 spec_id, {self.stats["total"]} 个字段')

            if not tasks:
                log.info('没有待处理的任务')
                return

            if self.dry_run:
                log.info('[dry-run] 只显示任务，不执行')
                for t in tasks[:5]:
                    log.info(f'  spec_id={t["spec_id"]}, fields={t["fields"]}')
                return

            # 启动延迟
            self.browser.sleep(ANTI_CRAWL['startup_delay'])

            # 逐批次执行
            for i, task in enumerate(tasks):
                if self.debug and i >= 5:
                    log.info(f'[debug] 已跑5条，停止')
                    break

                self._process_task(task)
                self.browser.should_rest()

                # 随机页面延迟
                self.browser.sleep(ANTI_CRAWL['page_delay'])

        finally:
            self.browser.stop()
            self._print_summary()

    def _process_task(self, task):
        """处理单个 spec_id 的任务"""
        spec_id = task['spec_id']
        fields = task['fields']
        task_ids = task['task_ids']

        log.info(f'处理 spec_id={spec_id}, 字段: {fields}')

        try:
            # 读取当前值
            current_values = self.db.get_current_values(spec_id, TARGET_FIELDS)

            # 提取真实值
            real_values = self.browser.extract_fields(spec_id)

            # 对比并修复
            changed = False
            for field in fields:
                current = current_values.get(field)
                real = real_values.get(field)

                if real is None:
                    # 页面无此字段，保持空值
                    self.db.mark_task_done(task_ids)
                    self.stats['no_change'] += 1
                    log.info(f'  {field}: 页面无此配置，保持空值')
                    continue

                if current == real:
                    # 值相同，无需修复
                    self.db.mark_task_done(task_ids)
                    self.stats['no_change'] += 1
                    log.info(f'  {field}: 值一致 ({real[:30] if real else "None"})')
                    continue

                # 值不同，修复
                if not self.debug:
                    self.db.update_peizhibiao(spec_id, field, real)
                    self.db.insert_repair_log(spec_id, field, current, real)
                self.db.mark_task_done(task_ids)
                self.stats['success'] += 1
                changed = True
                log.info(f'  {field}: 修复 [{current[:30] if current else "None"}] → [{real[:30]}]')

            # 检查 adas_system 新名称
            if 'adas_system' in fields and real_values.get('adas_system'):
                self._check_new_name(spec_id, real_values['adas_system'])

            self.browser.error_count = 0  # 成功则重置

        except Exception as e:
            error_msg = str(e)
            log.warning(f'spec_id={spec_id} 失败: {error_msg}')
            self.db.mark_task_failed(task_ids, error_msg)
            self.stats['failed'] += 1
            self.browser.error_count += 1

            # 熔断检查
            if self.browser.error_count >= ANTI_CRAWL['max_consecutive_errors']:
                log.error(f'连续失败 {self.browser.error_count} 次，自动退出')
                raise Exception('熔断：连续失败过多')

            # 指数退避
            backoff = ANTI_CRAWL['error_backoff'][min(self.browser.error_count - 1, len(ANTI_CRAWL['error_backoff']) - 1)]
            log.info(f'  指数退避 {backoff}s')
            time.sleep(backoff)

    def _check_new_name(self, spec_id, name):
        """检查是否是新名称，提示加入名称库"""
        if not name:
            return
        # 简单去重检查（实际应查 bright_brand_ref 表，这里先记录）
        if name not in self.stats['new_names']:
            self.stats['new_names'].append(name)
            log.info(f'  ⚠️ 新名称: {name}，请确认后加入 bright_brand_ref')

    def _print_summary(self):
        """打印汇总报告"""
        log.info('=' * 60)
        log.info('补采汇总')
        log.info('=' * 60)
        log.info(f'总任务: {self.stats["total"]}')
        log.info(f'修复: {self.stats["success"]}')
        log.info(f'无变化: {self.stats["no_change"]}')
        log.info(f'失败: {self.stats["failed"]}')
        if self.stats['new_names']:
            log.info(f'新名称: {len(self.stats["new_names"])} 个')
            for name in self.stats['new_names']:
                log.info(f'  - {name}')
        log.info('=' * 60)


# ==================== 主入口 ====================
def main():
    parser = argparse.ArgumentParser(description='配置表 CSS 混淆字段补采')
    parser.add_argument('--debug', type=int, metavar='N', help='调试模式，只跑 N 条')
    parser.add_argument('--dry-run', action='store_true', help='只显示任务，不执行')
    parser.add_argument('--no-headless', action='store_true', help='显示浏览器窗口')
    args = parser.parse_args()

    log.info('启动补采脚本')
    log.info(f'模式: {"debug" if args.debug else "full"}{" (dry-run)" if args.dry_run else ""}')

    db = DB()
    browser = BrowserPatcher(headless=not args.no_headless)
    scheduler = PatchScheduler(db, browser, debug=args.debug, dry_run=args.dry_run)

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
