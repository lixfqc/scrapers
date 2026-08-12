# -*- coding: utf-8 -*-
# 配置表数据 DOM 后验修复脚本
# 针对三批已确认的污染记录，用 Playwright 打开渲染后的配置页（style_col_act 激活列+已渲染::before）
# 取字段真值，对比数据库后做精准 UPDATE。全程支持 dry-run、页面级缓存、修复日志 CSV、
# 反爬策略（延迟/批次休息/指数退避），默认只打印不写库。
#
# 设计原则（来自代码规范 20260801）：
#   1. 三段式隔离：清单层（build_repair_tasks）→ 真值提取层（DomTruthExtractor）→ DB事务层（DbUpdater）
#   2. 降级优于中断：某条失败记 WARN，连续 5 条才熔断；字段取不到真值就 SKIP，不覆盖脏值为 NULL
#   3. 所有 SQL 参数化；所有配置用 DbConfig / RepairConfig 集中，不硬编码密码
#   4. 关键逻辑（激活列定位失败降级、批次休息、CSV 日志行）加中文行内注释
#
# 使用：
#   # 1. 仅做 dry-run（只打印修复动作，不改数据库，默认）
#   python spec_dom_repair.py --dry-run
#   # 2. 只修单目城市 39 条
#   python spec_dom_repair.py --batch single_cam_city
#   # 3. 只修车型名丢字（模式 A+B 353 条）
#   python spec_dom_repair.py --batch specname_chopped
#   # 4. 只修 assist_image 50 字被截的（全表 LENGTH=49/50 的）
#   python spec_dom_repair.py --batch assist_image_trunc
#   # 5. 三批全部修（正式跑）
#   python spec_dom_repair.py --batch all --apply
#   # 6. 续跑修复（跳过 cache 里已有页面真值的 spec）
#   python spec_dom_repair.py --batch all --apply --resume
#   # 7. 自定义修复清单（手动传入 spec_id 列表 CSV：列=spec_id,字段名）
#   python spec_dom_repair.py --custom-list custom_tasks.csv --apply

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Iterable

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print('ERROR: 依赖缺失 psycopg2-binary，请先 pip install psycopg2-binary')
    raise

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print('ERROR: 依赖缺失 playwright，请先 pip install playwright && python -m playwright install')
    raise

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / '_dom_cache'           # 每个 spec 页面提取的真值 JSON 落盘
LOG_DIR = BASE_DIR / 'logs'
CACHE_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# ============== 日志（独立脚本的降级版 logger，避免对 core/logging.py 的硬依赖）==============
logger = logging.getLogger('spec_dom_repair')
logger.setLevel(logging.INFO)
_fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
_fh = logging.FileHandler(LOG_DIR / f'spec_dom_repair_{datetime.now():%Y%m%d}.log', encoding='utf-8')
_fh.setFormatter(_fmt); logger.addHandler(_fh)
_ch = logging.StreamHandler(sys.stdout); _ch.setFormatter(_fmt); logger.addHandler(_ch)


# ============== 配置（集中管理，不硬编码）==============
@dataclass
class DbConfig:
    """云端 peizhibiao 库连接配置 —— 优先读 db_config.json；缺失时回退 cloud_db.py 凭据（与 scraper_v7.py 同一套）。"""
    config_path: Path = BASE_DIR / 'db_config.json'

    def load(self) -> Dict:
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        # 回退：本机无 db_config.json，直接复用 cloud_db.py 的凭据（scraper_v7.py L17 也是同一套）
        sys.path.insert(0, str(BASE_DIR))
        from cloud_db import HOST, PORT, USER, PASS
        return {'host': HOST, 'port': PORT, 'user': USER, 'password': PASS, 'dbname': 'peizhibiao'}


@dataclass
class RepairConfig:
    """修复全局参数（来自 anti_crawl.md 反爬纪律的轻量子集，适合后验小批量跑）。"""
    # Playwright / 页面
    edge_path: str = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
    page_wait_ms: int = 900                # 滚动加载后等待 DOM 稳定
    scroll_steps: Tuple[int, ...] = (500, 1500, 3000, 5000, 7000)
    # 反爬延迟
    inter_page_delay: Tuple[float, float] = (3.5, 7.0)   # 页面间随机延迟区间（秒）
    batch_every: int = 35                                  # 每 N 页强制长休一次
    batch_break: Tuple[float, float] = (80.0, 130.0)      # 批次长休（秒，约 1.5-2 分钟）
    extra_rest_prob: float = 0.08                         # 8% 概率追加超长休息（防 QoS）
    extra_rest_span: Tuple[float, float] = (180.0, 300.0) # 超长休息（3-5 分钟）
    start_random_delay: Tuple[float, float] = (5.0, 20.0) # 启动时随机休眠
    # 熔断
    max_consecutive_fail: int = 5
    retry_times: int = 3
    retry_backoff_base: float = 1.5                       # 1.5s → 2.25s → 3.375s
    # 输出
    csv_report_path: Path = LOG_DIR / f'repair_report_{datetime.now():%Y%m%d_%H%M%S}.csv'


# ============== 字段关键词库（DOM 真值提取阶段：在 style_row 里定位某配置字段的那一行）==============
# 每个 target_field 给 3-6 个中文关键词；任一关键词在行标题（cells[0]文本）里命中就算行定位成功
FIELD_ROW_KEYWORDS: Dict[str, List[str]] = {
    'drive_section':      ['路段', '驾驶路段', '辅助驾驶路段', '导航路段'],
    'assist_image':       ['摄像头', '前摄像头', '驾驶图像', '感知方案', '图像方案', '视觉方案'],
    'lane_centering':     ['居中', '车道居中', '居中保持', '居中辅助'],
    'auto_park':          ['泊车', '自动泊车', '泊车辅助'],
    'lane_change_assist': ['变道', '换道', '变道辅助', '换道辅助'],
    'active_brake':       ['主动刹车', '紧急制动', '前向碰撞', '碰撞制动', '制动辅助'],
}

# spec_name 不走 style_row，直接读 style_table_head_spec 激活列标题（那里天然无 CSS 混淆）


# ============== 核心数据结构 ==============
@dataclass
class RepairTask:
    """单条修复任务：一个 spec 的一个字段要修。"""
    spec_id: int
    field: str                 # 'spec_name' / 'drive_section' / 'assist_image' ...
    db_val: str                # 库中当前值（对比真值用）
    batch_tag: str             # 属于哪批（用于日志）：single_cam_city / specname_chopped / assist_image_trunc / custom

    def cache_key(self) -> str:
        return f's{self.spec_id}'   # 同一 spec 多字段共享一个页面缓存


@dataclass
class RepairResult:
    task: RepairTask
    status: str                 # 'UPDATED' / 'SKIP_NO_TRUTH' / 'SKIP_MATCH' / 'FAIL' / 'DRYRUN_OK'
    old_value: str = ''
    new_value: str = ''
    note: str = ''
    page_url: str = ''
    cost_ms: int = 0


# ============== 1. 清单层：三批污染 SQL + 自定义 CSV 输入 ==============
class TaskListBuilder:
    """从云端按三种预定义批次，或从自定义 CSV 生成 RepairTask 列表。"""

    # 三批预定义 SQL（参数化：WHERE 条件固定 SELECT 字段固定）
    PRESET_SQL = {
        # A. 单目前摄 + drive_section 含"城市路段"（39 条，M1 整行串联污染）
        'single_cam_city': """
            SELECT spec_id, spec_name, drive_section
            FROM data_peizhibiao
            WHERE front_camera_type = '单目' AND drive_section LIKE %s
            ORDER BY manufacturer, series_name,
                     (regexp_replace(guide_price, '[^0-9.]', '', 'g'))::numeric ASC
        """,
        # B. spec_name 被截断：两种模式（首字丢 OR 版型缺字尾）去重合并（353条）
        'specname_chopped': """
            SELECT DISTINCT spec_id, spec_name, spec_name  -- 第三列占位，字段值即spec_name
            FROM data_peizhibiao
            WHERE front_camera_type = '单目' AND (
                (LENGTH(series_name) > 1
                    AND SUBSTRING(spec_name, 1, POSITION(' ' IN spec_name || ' ') - 1)
                        = SUBSTRING(series_name, 1, 1)
                    AND SUBSTRING(spec_name, 1, LENGTH(series_name)) <> series_name)
                OR (spec_name ~ %s AND spec_name !~ %s)
            )
        """,
        # C. assist_image 物理截断：LENGTH=49或50（varchar(50)），有很大概率末尾被数据库截断
        'assist_image_trunc': """
            SELECT spec_id, spec_name, assist_image
            FROM data_peizhibiao
            WHERE assist_image IS NOT NULL AND LENGTH(assist_image) IN (49, 50)
        """,
    }
    PRESET_PARAMS = {
        'single_cam_city': ['%城市%'],
        # 车型名截断的两个正则（见 _scan_doc_issues.py 模式 A+B）
        'specname_chopped': [
            r'[智尊享耀越领贵豪]\s*$',   # 倒数1字是版型关键词之一
            r'[版型]\s*$',               # 排除以"版/型"结尾的（正常结束）
        ],
        'assist_image_trunc': [],
    }
    PRESET_FIELD = {
        'single_cam_city':       'drive_section',
        'specname_chopped':      'spec_name',
        'assist_image_trunc':    'assist_image',
    }

    def __init__(self, db_cfg: DbConfig):
        self._db = db_cfg.load()

    def build(self, batch_name: str, custom_csv: Optional[str] = None) -> List[RepairTask]:
        """主入口：按 batch_name 路由到三批预定义或自定义 CSV。"""
        if custom_csv:
            return self._from_custom(custom_csv)
        if batch_name == 'all':
            out: List[RepairTask] = []
            for sub in ['single_cam_city', 'specname_chopped', 'assist_image_trunc']:
                out.extend(self._from_preset(sub))
            # 去重：同一 spec_id+field 只保留一条（避免重复修）
            seen = set()
            uniq = []
            for t in out:
                key = (t.spec_id, t.field)
                if key in seen: continue
                seen.add(key); uniq.append(t)
            return uniq
        return self._from_preset(batch_name)

    def _from_preset(self, name: str) -> List[RepairTask]:
        if name not in self.PRESET_SQL:
            raise ValueError(f'未知 batch：{name}，可选 {list(self.PRESET_SQL)}')
        sql = self.PRESET_SQL[name]
        params = list(self.PRESET_PARAMS[name])
        target_field = self.PRESET_FIELD[name]
        out: List[RepairTask] = []
        with psycopg2.connect(**self._db, sslmode='disable') as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql, params)
                for spec_id, _, raw_val in cur.fetchall():
                    if raw_val is None: continue   # 空值说明没污染，跳过
                    out.append(RepairTask(
                        spec_id=int(spec_id),
                        field=target_field,
                        db_val=str(raw_val).strip(),
                        batch_tag=name,
                    ))
        logger.info(f'[清单] 批次 {name!r} 共生成 {len(out)} 条 RepairTask')
        return out

    def _from_custom(self, csv_path: str) -> List[RepairTask]:
        """自定义 CSV：列顺序为 spec_id, field（第一行表头可选）。"""
        if not Path(csv_path).exists():
            raise FileNotFoundError(f'自定义清单文件不存在：{csv_path}')
        out: List[RepairTask] = []
        with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f)
            first = next(reader, None)
            if not first:
                return out
            # 识别表头：首列不是纯数字就当表头跳过；否则第一行就是数据行
            if first[0].strip().isdigit():
                rows = [first] + [r for r in reader if r and r[0].strip()]
            else:
                rows = [r for r in reader if r and r[0].strip()]
            with psycopg2.connect(**self._db, sslmode='disable') as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    for row in rows:
                        if len(row) < 2:
                            continue
                        sid, field = int(row[0]), row[1].strip()
                        # 白名单前置校验：非白名单字段直接跳过，绝不进入 SQL（防注入+防误写）
                        if field not in DbUpdater.ALLOWED_FIELDS:
                            logger.warning(f'[清单] custom 字段 {field!r} 不在白名单，跳过该任务')
                            continue
                        if field == 'spec_name':
                            cur.execute('SELECT spec_name FROM data_peizhibiao WHERE spec_id=%s', (sid,))
                        else:
                            if field not in FIELD_ROW_KEYWORDS:
                                logger.warning(f'[清单] custom 字段 {field} 不在关键词库，该字段用 style_col_act 整列text取值')
                            cur.execute(f'SELECT {field} FROM data_peizhibiao WHERE spec_id=%s', (sid,))
                        r = cur.fetchone()
                        if not r or r[0] is None: continue
                        out.append(RepairTask(spec_id=sid, field=field, db_val=str(r[0]).strip(), batch_tag='custom'))
        logger.info(f'[清单] custom {csv_path!r} 共生成 {len(out)} 条 RepairTask')
        return out


# ============== 2. Playwright DOM 真值提取层（带缓存 + 反爬延迟 + 重试）==============
class DomTruthExtractor:
    """对每个 spec 页面：滚动加载→提取该页面所有目标字段的"style_col_act激活列渲染后真值"，
    缓存到 _dom_cache/s<SPEC_ID>.json，便于 --resume 续跑与跨批复用。"""

    UA_POOL = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36 Edg/127.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0',
        'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36',
    ]

    def __init__(self, cfg: RepairConfig, resume: bool = False):
        self.cfg = cfg
        self.resume = resume
        self._processed_page_count = 0
        self._consecutive_fail = 0

    # ---------------- 对外：从一个 RepairTask 拿真值 ----------------
    def extract_for_task(self, page, task: RepairTask) -> Tuple[Optional[str], str]:
        """在已打开的 page 对象（必须已加载 spec 配置页）上提取 task.field 的真值。
        返回 (truth_or_None, note 说明)。"""
        # spec_name 用 style_table_head_spec 激活列标题（浏览器已渲染::before，天然无混淆）
        if task.field == 'spec_name':
            return self._truth_specname(page)
        # 其他字段：在 style_row 里按关键词定位行，取激活列
        return self._truth_config_field(page, task.field)

    # ---------------- 页面打开、缓存、反爬延迟 ----------------
    def open_and_cache(self, spec_id: int, pw_page) -> Dict:
        """打开一个 spec 页面，按 scroll_steps 滚动加载，缓存该 spec 所有字段真值到 JSON。
        返回缓存 dict（字段名 -> 真值或 '__标记'）。"""
        cache_file = CACHE_DIR / f's{spec_id}.json'
        # --resume：命中缓存直接返回，不再访问网页（连续修/多批同 spec 时极大节省抓取量）
        if self.resume and cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if data and isinstance(data, dict) and '__ok' in data:
                    logger.debug(f'[缓存命中] s{spec_id} 直接使用 _dom_cache')
                    return data
            except Exception as e:
                logger.warning(f'[缓存损坏] s{spec_id}: {e}，重抓')

        # 启动随机延迟（仅第 1 页）
        if self._processed_page_count == 0:
            self._random_sleep(*self.cfg.start_random_delay, '启动随机延迟')
        # 反爬：页面间延迟
        if self._processed_page_count > 0:
            self._random_sleep(*self.cfg.inter_page_delay, '页面间')
            # 批次长休（每 batch_every 页强制休息 1.5-2 分钟）
            if self._processed_page_count % self.cfg.batch_every == 0:
                self._random_sleep(*self.cfg.batch_break, '批次长休')
            # 8% 概率超长休（3-5 分钟，防 QoS 限流）
            if random.random() < self.cfg.extra_rest_prob:
                self._random_sleep(*self.cfg.extra_rest_span, '概率性超长休')

        url = f'https://www.autohome.com.cn/config/spec/{spec_id}.html'
        truth_map: Dict = {'__url': url, '__ok': False}

        # 指数退避重试
        for attempt in range(1, self.cfg.retry_times + 1):
            t0 = time.time()
            try:
                pw_page.goto(url, wait_until='domcontentloaded', timeout=45000)
                for pos in self.cfg.scroll_steps:
                    pw_page.evaluate(f'document.documentElement.scrollTop={pos}')
                    pw_page.wait_for_timeout(280)
                pw_page.evaluate('document.documentElement.scrollTop=0')
                pw_page.wait_for_timeout(self.cfg.page_wait_ms)
                # 一次性从页面拿所有高风险字段真值（一次 evaluate 减少 IPC）
                truth_map.update(self._extract_all_fields(pw_page))
                truth_map['spec_name'], note_specname = self._truth_specname(pw_page)
                truth_map['__note_specname'] = note_specname
                truth_map['__ok'] = True
                truth_map['__cost_ms'] = int((time.time() - t0) * 1000)
                self._consecutive_fail = 0
                break
            except (PWTimeout, Exception) as e:
                self._consecutive_fail += 1
                backoff = self.cfg.retry_backoff_base ** attempt
                logger.warning(f'[重试 {attempt}/{self.cfg.retry_times}] s{spec_id}: {e!r}，'
                               f'退避 {backoff:.1f}s，连续失败={self._consecutive_fail}')
                time.sleep(backoff)
                truth_map['__fatal'] = f'{type(e).__name__}: {e}'
                # 连续 5 次失败直接熔断（反爬纪律）
                if self._consecutive_fail >= self.cfg.max_consecutive_fail:
                    raise RuntimeError(
                        f'连续 {self._consecutive_fail} 个 spec 页面失败，已触发熔断。'
                        f'建议 10 分钟后重新带 --resume 续跑，避免被限流。'
                    ) from e

        # 写入缓存（不管成功与否，失败时保留 __fatal 以便复盘）
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(truth_map, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f'[缓存写入失败] s{spec_id}: {e}')

        self._processed_page_count += 1
        return truth_map

    # ---------------- 内部：单页提取所有字段（一次 evaluate 批量取）----------------
    def _extract_all_fields(self, page) -> Dict:
        """在页面上用 JS 遍历 style_row，用关键词匹配每个 FIELD_ROW_KEYWORDS 字段的那一行，
        然后精准取 style_col_act 的 text。返回 {field_name: truth_value_or_xxx标记}。"""
        # 修复(2026-08-11): 直接传 dict 对象，不要 json.dumps 成字符串。
        # 否则 Playwright 里 Object.entries(kw_map) 遍历的是字符串字符，
        # keywords 变成单字符而非数组，keywords.some 报 "not a function"。
        return page.evaluate("""(kw_map) => {
            const rows = document.querySelectorAll('.style_row, [class*=style_row]');
            const result = {};
            for (const [f, keywords] of Object.entries(kw_map)) {
                let found = '__NO_ROW__';
                for (const row of rows) {
                    const cells = Array.from(row.querySelectorAll(':scope > div, :scope > th, :scope > td'));
                    if (!cells.length) continue;
                    const title = (cells[0].innerText || '').replace(/\\s+/g, ' ').trim();
                    if (!keywords.some(k => title.includes(k))) continue;
                    // 找激活列
                    let actCell = null;
                    for (const c of cells) {
                        if (/style_col_act/.test(c.className || '')) { actCell = c; break; }
                    }
                    // 激活列类名不规范时的降级：用 style_table_head 激活列的索引（健壮性）
                    if (!actCell) {
                        const headCells = Array.from(document.querySelectorAll('[class*=style_table_head] > div, [class*=style_table_head] th, [class*=style_table_head] td'));
                        const i = headCells.findIndex(c => /style_col_act/.test(c.className || ''));
                        if (i >= 0 && cells[i]) actCell = cells[i];
                    }
                    if (!actCell) { found = '__NO_ACT_COL__'; break; }
                    const subs = Array.from(actCell.querySelectorAll('.style_col_sub'))
                        .map(s => (s.innerText || '').trim()).filter(Boolean);
                    found = subs.length ? subs.join(' ') : (actCell.innerText || '').replace(/\\s+/g, ' ').trim();
                    break;
                }
                result[f] = found || '__EMPTY_ACT_COL__';
            }
            return result;
        }""", FIELD_ROW_KEYWORDS)

    def _truth_specname(self, page) -> Tuple[Optional[str], str]:
        """从 style_table_head_spec 激活列标题取完整车型名（已渲染::before，无CSS混淆）。"""
        try:
            heads = page.query_selector_all('[class*=style_table_head_spec]')
            for h in heads:
                text = h.inner_text().replace('钉在左侧', '').replace('对比', '').strip()
                text = ' '.join(text.split())   # 去多余空白
                # 过滤掉只是"钉在左侧"的空壳 / 只有系列名不含车型年份细节的
                if len(text) >= 8 and any(tok in text for tok in ['款', '款 ', ' ']):
                    return text, 'OK: from style_table_head_spec'
            # 降级：从面包屑当前位置后半段抓（AION RT 页面 head_spec 取不到时的兜底）
            bc = page.query_selector('[class*=crumbs], nav, .tw-grow')
            if bc:
                m = bc.inner_text()
                import re as _re
                mm = _re.search(r'当前位置.*?参数配置', m, re.S)
                if mm:
                    parts = ' '.join(mm.group().split()).split(' ')
                    # 抓"参数配置"前面最后一个 >=6 字的片段
                    cands = [p for p in parts if len(p) >= 6 and '参数配置' not in p][-3:]
                    if cands: return cands[-1], 'OK: crumbs fallback'
            return None, '无法定位 spec_name（无 head_spec 且无面包屑）'
        except Exception as e:
            return None, f'_truth_specname 异常: {e}'

    def _truth_config_field(self, page, field: str) -> Tuple[Optional[str], str]:
        """走 _extract_all_fields 的缓存结果取单字段。外部一般不直接调（由 open_and_cache 一次性产出）。"""
        all_truth = self._extract_all_fields(page)
        v = all_truth.get(field, '__NO_ROW__')
        if isinstance(v, str) and v.startswith('__'):
            return None, f'字段定位失败: {v}'
        return (v.strip() if isinstance(v, str) else None), 'OK: style_col_act激活列'

    # ---------------- 工具：随机休眠 ----------------
    @staticmethod
    def _random_sleep(lo: float, hi: float, tag: str) -> None:
        sec = round(random.uniform(lo, hi), 2)
        logger.info(f'[反爬] {tag}：休眠 {sec:.1f}s')
        time.sleep(sec)


# ============== 3. DB 事务层：参数化 UPDATE + 修复前后校验 ==============
class DbUpdater:
    """参数化 SQL 更新 data_peizhibiao，支持 dry-run（默认）与真实写入。"""

    ALLOWED_FIELDS = set(['spec_name', *FIELD_ROW_KEYWORDS.keys()])

    def __init__(self, db_cfg: DbConfig, apply: bool):
        self._db = db_cfg.load()
        self.apply = apply    # True=真实写；False=dry-run

    def _option_sublist_len(self, spec_id: int, item_id: int = 9059) -> Optional[int]:
        """查 option_raw 中指定 configitem（默认 9059=drive_section）该 spec 的 sublist 段数。
        返回段数；无源数据/结构不符返回 None。用于区分"爬虫拼接已修"与"源数据本身多段"两种 SKIP。"""
        try:
            with psycopg2.connect(**self._db, sslmode='disable') as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT option_raw FROM data_peizhibiao WHERE spec_id=%s', (spec_id,))
                    r = cur.fetchone()
            if not r or not r[0] or not isinstance(r[0], dict):
                return None
            for ct in r[0].get('configtypeitems', []) or []:
                for ci in ct.get('configitems', []) or []:
                    if str(ci.get('id')) != str(item_id):
                        continue
                    for vi in ci.get('valueitems', []) or []:
                        if str(vi.get('specid')) != str(spec_id):
                            continue
                        subs = [s.get('subname', '') for s in (vi.get('sublist') or []) if s.get('subname')]
                        return len(subs) if subs else None
            return None
        except Exception:
            return None

    def update_if_different(self, task: RepairTask, new_value: str) -> RepairResult:
        """若 new_value 与 task.db_val 不同才 UPDATE；返回 RepairResult（含 DRYRUN_OK / UPDATED / SKIP_MATCH）。"""
        if task.field not in self.ALLOWED_FIELDS:
            raise ValueError(f'字段 {task.field!r} 未在白名单，拒绝更新。白名单={sorted(self.ALLOWED_FIELDS)}')
        new_value = (new_value or '').strip()
        page_url = f'https://www.autohome.com.cn/config/spec/{task.spec_id}.html'
        # 空真值 -> 跳过（避免把脏值覆盖成 NULL）
        if not new_value:
            return RepairResult(task, 'SKIP_NO_TRUTH', old_value=task.db_val, new_value='',
                                note='浏览器渲染后也取不到真值，未覆盖原值', page_url=page_url)
        # 完全一致 -> 跳过
        if new_value == task.db_val:
            note = 'DB与真值一致，无需更新'
            # drive_section 特殊核验：源数据本身是否就含多段（如"单目+城市路段"业务矛盾，DOM 也修不动）
            if task.field == 'drive_section':
                n = self._option_sublist_len(task.spec_id)
                if n is not None and n >= 2:
                    note += f'｜⚠️ option源sublist={n}段，源数据本身多段，需人工判定口径'
            return RepairResult(task, 'SKIP_MATCH', old_value=task.db_val, new_value=new_value,
                                note=note, page_url=page_url)

        sql = f'UPDATE data_peizhibiao SET {task.field} = %s WHERE spec_id = %s'
        params = [new_value, task.spec_id]
        note = f'原值 len={len(task.db_val)} → 新值 len={len(new_value)}'
        if not self.apply:
            return RepairResult(task, 'DRYRUN_OK', old_value=task.db_val, new_value=new_value,
                                note=f'[dry-run 将执行] {sql % (new_value, task.spec_id)}（未真写库）{note}',
                                page_url=page_url)
        # 实际写库：用事务 + 异常回滚（规范第9.1条：参数化，禁止字符串拼接）
        try:
            with psycopg2.connect(**self._db, sslmode='disable') as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    affected = cur.rowcount
                conn.commit()
            return RepairResult(task, 'UPDATED', old_value=task.db_val, new_value=new_value,
                                note=f'写入成功，AFFECTED={affected} {note}', page_url=page_url)
        except Exception as e:
            return RepairResult(task, 'FAIL', old_value=task.db_val, new_value=new_value,
                                note=f'写入异常: {type(e).__name__}: {e}', page_url=page_url)


# ============== 4. 编排层：把上面三层串起来，打印进度 + 输出 CSV 报告 ==============
class RepairOrchestrator:
    """Facade：对外就一个 run() 方法，隐藏内部三层细节。"""

    def __init__(self, tasks: List[RepairTask], extractor: DomTruthExtractor,
                 updater: DbUpdater, cfg: RepairConfig):
        self.tasks = tasks
        self.extractor = extractor
        self.updater = updater
        self.cfg = cfg

    def run(self) -> List[RepairResult]:
        """按 spec_id 归并减少页面打开次数（同一spec多字段修复只开一次页）。"""
        by_spec: Dict[int, List[RepairTask]] = {}
        for t in self.tasks:
            by_spec.setdefault(t.spec_id, []).append(t)

        logger.info(f'[编排] 共 {len(self.tasks)} 条 RepairTask，归并为 {len(by_spec)} 个 spec 页面。'
                    f' apply={self.updater.apply}（True=写库，False=dry-run）')

        results: List[RepairResult] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=self.cfg.edge_path, headless=True)
            ctx = browser.new_context(
                user_agent=random.choice(DomTruthExtractor.UA_POOL),
                viewport={'width': 1920, 'height': 1080},
            )
            page = ctx.new_page()
            for i, (sid, tasks_of_spec) in enumerate(sorted(by_spec.items()), 1):
                logger.info(f'[{i}/{len(by_spec)}] spec_id={sid}，待修字段：{[t.field for t in tasks_of_spec]}')
                t0 = time.time()
                try:
                    truth_map = self.extractor.open_and_cache(sid, page)
                except RuntimeError as e:  # 熔断：写报告后直接终止
                    logger.error(f'[熔断退出] {e}')
                    self._write_csv(results)
                    raise
                for task in tasks_of_spec:
                    truth, note = None, '未进入提取'
                    try:
                        if not truth_map.get('__ok'):
                            note = truth_map.get('__fatal', '__ok=0 未知原因')
                            res = RepairResult(task, 'SKIP_NO_TRUTH', task.db_val, '', note=note,
                                               page_url=truth_map.get('__url', ''))
                        else:
                            if task.field == 'spec_name':
                                truth = truth_map.get('spec_name')
                                note = truth_map.get('__note_specname', '')
                            else:
                                tv = truth_map.get(task.field, '__NO_ROW__')
                                if isinstance(tv, str) and tv.startswith('__'):
                                    truth, note = None, f'配置行定位失败标记: {tv}'
                                else:
                                    truth, note = tv, 'OK: style_col_act激活列'
                            res = self.updater.update_if_different(task, truth or '')
                            res.note = f'{note} | {res.note}' if note != 'OK' and note else res.note
                    except Exception as e:
                        res = RepairResult(task, 'FAIL', task.db_val, truth or '',
                                           note=f'编排异常: {type(e).__name__}: {e}',
                                           page_url=truth_map.get('__url', ''))
                    res.cost_ms = int((time.time() - t0) * 1000)
                    results.append(res)
                    logger.info(f'  · {task.batch_tag}/{task.field} {res.status} '
                                f'｜旧={res.old_value[:40]!r} → 新={res.new_value[:40]!r}')
            browser.close()
        self._write_csv(results)
        self._print_summary(results)
        return results

    # ---------------- CSV 报告（默认 logs/repair_report_YYYYMMDD_HHMMSS.csv）----------------
    def _write_csv(self, results: List[RepairResult]) -> None:
        try:
            with open(self.cfg.csv_report_path, 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.writer(f)
                w.writerow(['batch_tag', 'spec_id', 'field', 'status', 'old_value',
                            'new_value', 'note', 'page_url', 'cost_ms'])
                for r in results:
                    w.writerow([r.task.batch_tag, r.task.spec_id, r.task.field, r.status,
                                r.old_value, r.new_value, r.note, r.page_url, r.cost_ms])
            logger.info(f'[CSV] 修复明细已写入：{self.cfg.csv_report_path}（共 {len(results)} 行）')
        except Exception as e:
            logger.warning(f'[CSV写入失败] {e}')

    # ---------------- 总结输出 ----------------
    @staticmethod
    def _print_summary(results: List[RepairResult]) -> None:
        from collections import Counter
        c = Counter(r.status for r in results)
        total = len(results)
        logger.info('=========== 修复总结 ===========')
        for s in ['UPDATED', 'DRYRUN_OK', 'SKIP_MATCH', 'SKIP_NO_TRUTH', 'FAIL']:
            n = c.get(s, 0)
            if not n: continue
            logger.info(f'  {s:<14} {n:>5} 条（{100*n/total:>5.1f}%）')
        logger.info(f'  {"合计":<14} {total:>5} 条')
        logger.info(f'CSV 报告：{RepairConfig.csv_report_path}（请把 UPDATED 与 FAIL 行重点核对）')


# ============== 5. CLI 入口 ==============
def main() -> None:
    ap = argparse.ArgumentParser(
        description='配置表 DOM 后验修复：三批污染清单（单目城市/spec_name截断/assist_image被截）'
                    ' Playwright 取激活列真值 → 参数化 UPDATE 云端 data_peizhibiao。',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument('--batch', choices=['all', 'single_cam_city', 'specname_chopped', 'assist_image_trunc'],
                    default='all', help='修复批次：all=三批合并跑')
    ap.add_argument('--custom-list', metavar='PATH', default=None,
                    help='自定义修复清单 CSV（首两列 spec_id,field；--batch 被忽略）')
    ap.add_argument('--apply', action='store_true',
                    help='【危险】真实执行 UPDATE；不写该参数则默认 dry-run 只打印不改库')
    ap.add_argument('--resume', action='store_true',
                    help='从 _dom_cache/ 命中缓存时直接用，不再抓页（续跑/断点续修）')
    ap.add_argument('--db-config', metavar='PATH', default=str(BASE_DIR / 'db_config.json'),
                    help='云端连接配置 JSON 路径（默认 db_config.json）')
    args = ap.parse_args()

    if not args.apply:
        logger.info('【模式：dry-run】默认不写库，确认逻辑正确后请加 --apply 正式执行。')

    cfg = RepairConfig()
    db_cfg = DbConfig(config_path=Path(args.db_config))

    builder = TaskListBuilder(db_cfg)
    tasks = builder.build(args.batch if not args.custom_list else 'custom', args.custom_list)
    if not tasks:
        logger.warning('任务清单为空，退出。')
        return

    extractor = DomTruthExtractor(cfg, resume=args.resume)
    updater = DbUpdater(db_cfg, apply=args.apply)
    orch = RepairOrchestrator(tasks, extractor, updater, cfg)
    orch.run()


if __name__ == '__main__':
    main()
