# -*- coding: utf-8 -*-
"""
月度增量调度脚本 monthly_update.py
每月运行一次：探测各国最新可用月份，与库中 MAX(source_month) 对比，增量爬取新数据。

用法:
    python monthly_update.py                # 全量扫描14源
    python monthly_update.py --country SE   # 只跑瑞典
    python monthly_update.py --dry-run      # 只打印计划不执行

设计:
    - 每源独立 try/except，失败不影响其他源
    - 复用各爬虫 save_sales upsert（幂等，重复安全）
    - 结果写 crawl_run_log + 更新 market_source_registry
"""
import sys
import os
import io
import argparse
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from base_crawler import DB_CONFIG, BaseCrawler
import psycopg2
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------
# 各源增量处理器：统一函数签名 handler(conn, dry_run) -> dict
# 返回 {'status': 'ok'|'skip'|'error', 'records': n, 'msg': str, 'month': date}
# ---------------------------------------------------------------

def handle_at(conn, dry_run):
    from at_crawler import AustriaCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'OGD CSV incremental (dry-run)'}
    c = AustriaCrawler()
    result = c.crawl_incremental()
    n = result if isinstance(result, int) else (result.get('records', 0) if isinstance(result, dict) else 0)
    return {'status': 'ok', 'records': n, 'msg': 'OGD CSV incremental (>= max month)'}

def handle_ch(conn, dry_run):
    from ch_crawler import SwitzerlandCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'auto.swiss incremental (dry-run)'}
    c = SwitzerlandCrawler()
    result = c.crawl_incremental()
    n = 0
    if isinstance(result, dict):
        for year, res in result.items():
            if isinstance(res, dict):
                n += res.get('saved', 0)
    return {'status': 'ok', 'records': n, 'msg': 'auto.swiss incremental (>= max month)'}

def handle_se(conn, dry_run):
    from se_crawler import SwedenCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'mobilitysweden incremental (dry-run)'}
    max_month = _get_max_month(conn, 'SE')
    nxt = _next_month(max_month)
    if nxt is None:
        return {'status': 'skip', 'records': 0, 'msg': 'no DB data, run full first'}
    c = SwedenCrawler()
    res = c.crawl_month(nxt[0], nxt[1])
    n = res.get('records', 0) if isinstance(res, dict) else 0
    return {'status': 'ok', 'records': n, 'msg': f'SE {nxt[0]}-{nxt[1]:02d}'}

def handle_fi(conn, dry_run):
    from fi_crawler import FinlandCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'aut.fi incremental (dry-run)'}
    max_month = _get_max_month(conn, 'FI')
    nxt = _next_month(max_month)
    if nxt is None:
        return {'status': 'skip', 'records': 0, 'msg': 'no DB data, run full first'}
    c = FinlandCrawler()
    res = c.crawl_month(nxt[0], nxt[1])
    n = res.get('records', 0) if isinstance(res, dict) else 0
    return {'status': 'ok', 'records': n, 'msg': f'FI {nxt[0]}-{nxt[1]:02d}'}

def handle_kr(conn, dry_run):
    from kama_crawler import KamaCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'KAMA incremental (dry-run)'}
    max_month = _get_max_month(conn, 'KR')
    c = KamaCrawler()
    latest = c.latest_available_month()
    if latest is None:
        return {'status': 'skip', 'records': 0, 'msg': 'no new month discovered (list page empty)'}
    latest_date = date(latest[0], latest[1], 1)
    if max_month is not None and latest_date <= max_month:
        return {'status': 'skip', 'records': 0, 'msg': f'KR latest={latest[0]}-{latest[1]:02d} <= DB max {max_month}, no new data'}
    res = c.crawl_month(latest[0], latest[1])
    n = res.get('records', 0) if isinstance(res, dict) else 0
    return {'status': 'ok', 'records': n, 'msg': f'KR {latest[0]}-{latest[1]:02d} incremental'}

def handle_de(conn, dry_run):
    from kba_crawler import KBACrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'KBA incremental (dry-run)'}
    max_month = _get_max_month(conn, 'DE')
    c = KBACrawler()
    latest = c.latest_available_month()
    if latest is None:
        return {'status': 'skip', 'records': 0, 'msg': 'KBA latest month probe failed'}
    latest_date = date(latest[0], latest[1], 1)
    if max_month is not None and latest_date <= max_month:
        return {'status': 'skip', 'records': 0, 'msg': f'DE latest={latest[0]}-{latest[1]:02d} <= DB max {max_month}, no new data'}
    result = c.crawl_latest()
    n = result.get('records', 0) if isinstance(result, dict) else 0
    return {'status': 'ok', 'records': n, 'msg': f'DE {latest[0]}-{latest[1]:02d} incremental'}

def handle_gb(conn, dry_run):
    from smmt_crawler import SMMTCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'SMMT incremental (dry-run)'}
    max_month = _get_max_month(conn, 'GB')
    c = SMMTCrawler()
    latest = c.latest_available_month()
    if latest is None:
        return {'status': 'skip', 'records': 0, 'msg': 'SMMT latest month probe failed'}
    latest_date = date(latest.year, latest.month, 1)
    if max_month is not None and latest_date <= max_month:
        return {'status': 'skip', 'records': 0, 'msg': f'GB latest={latest} <= DB max {max_month}, no new data'}
    ok, model_saved = c.crawl_latest(include_model=False)
    return {'status': 'ok', 'records': model_saved, 'msg': f'GB {latest} incremental'}

def handle_nl(conn, dry_run):
    from nl_crawler import BovagCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'BOVAG incremental (dry-run)'}
    c = BovagCrawler()
    n = c.crawl_incremental(max_pages=50, model_only=True)
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'BOVAG sitemap incremental (new months only)'}

def handle_it(conn, dry_run):
    from unrae_crawler import UNRAECrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'UNRAE incremental (dry-run)'}
    max_month = _get_max_month(conn, 'IT')
    nxt = _next_month(max_month)
    if nxt is None:
        return {'status': 'skip', 'records': 0, 'msg': 'no DB data, run full first'}
    c = UNRAECrawler()
    res = c.crawl_range(nxt[0], nxt[1], nxt[0], nxt[1], parse_types=['brand', 'model', 'energy'], force=False)
    n = res.get('records', 0) if isinstance(res, dict) else 0
    return {'status': 'ok', 'records': n, 'msg': f'UNRAE {nxt[0]}-{nxt[1]:02d}'}

# FR/ES/BE：逐月探测（从库中MAX月+1起，连续失败2个月停止）
def handle_monthly_probe(conn, dry_run, country, crawler_cls, max_probe=3):
    max_month = _get_max_month(conn, country)
    nxt = _next_month(max_month)
    if nxt is None:
        return {'status': 'skip', 'records': 0, 'msg': 'no DB data, run full first'}
    c = crawler_cls()
    total = 0
    y, m = nxt
    consecutive_fail = 0
    last_ok = None
    for _ in range(max_probe):
        try:
            res = c.crawl_month(y, m)
        except Exception as e:
            return {'status': 'error', 'records': total, 'msg': f'{y}-{m:02d} error: {e}'}
        n = res.get('records', 0) if isinstance(res, dict) else 0
        if n > 0:
            total += n
            last_ok = (y, m)
            consecutive_fail = 0
        else:
            consecutive_fail += 1
            if consecutive_fail >= 2:
                break
        y, m = _advance(y, m)
    return {'status': 'ok', 'records': total, 'msg': f'{country} up to {last_ok}'}

def handle_fr(conn, dry_run):
    from pfa_crawler import PfaCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'PFA/CCFA incremental (dry-run)'}
    return handle_monthly_probe(conn, dry_run, 'FR', PfaCrawler)

def handle_es(conn, dry_run):
    from anfac_crawler import AnfacCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'ANFAC incremental (dry-run)'}
    return handle_monthly_probe(conn, dry_run, 'ES', AnfacCrawler)

def handle_be(conn, dry_run):
    from febiac_crawler import FebiacCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'Febiac incremental (dry-run)'}
    return handle_monthly_probe(conn, dry_run, 'BE', FebiacCrawler)

# JP：JADA 按年下载整年Excel，探测最新月后爬当年 brand+fuel（save_sales幂等，历史月自动跳过）
def handle_jp(conn, dry_run):
    from jada_crawler import JadaCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'JADA incremental (dry-run)'}
    max_month = _get_max_month(conn, 'JP')
    c = JadaCrawler()
    latest = c.latest_available_month()
    if latest is None:
        return {'status': 'skip', 'records': 0, 'msg': 'JADA latest month probe failed'}
    latest_date = date(latest[0], latest[1], 1)
    if max_month is not None and latest_date <= max_month:
        return {'status': 'skip', 'records': 0, 'msg': f'JP latest={latest[0]}-{latest[1]:02d} <= DB max {max_month}, no new data'}
    n = c.crawl_year(latest[0], 'brand')
    n += c.crawl_year(latest[0], 'fuel')
    return {'status': 'ok', 'records': n, 'msg': f'JP {latest[0]}-{latest[1]:02d} brand+fuel incremental'}

def handle_dk(conn, dry_run):
    from dk_crawler import DenmarkCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'mobility.dk incremental (dry-run)'}
    max_month = _get_max_month(conn, 'DK')
    c = DenmarkCrawler()
    latest = c.latest_available_month()
    if latest is None:
        return {'status': 'skip', 'records': 0, 'msg': 'DK latest month probe failed'}
    latest_date = date(latest[0], latest[1], 1)
    if max_month is not None and latest_date <= max_month:
        return {'status': 'skip', 'records': 0, 'msg': f'DK latest={latest[0]}-{latest[1]:02d} <= DB max {max_month}, no new data'}
    res = c.crawl_month(latest[0], latest[1])
    n = res.get('records', 0) if isinstance(res, dict) else 0
    return {'status': 'ok', 'records': n, 'msg': f'DK {latest[0]}-{latest[1]:02d} incremental'}

def handle_pt(conn, dry_run):
    from pt_crawler import PtCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'ACAP incremental (dry-run)'}
    c = PtCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'ACAP rolling xlsx incremental (new month only)'}

def handle_ie(conn, dry_run):
    from ie_crawler import IeCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'CSO TEM28 incremental (dry-run)'}
    c = IeCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'CSO TEM28 CSV incremental (>= max month)'}

def handle_pl(conn, dry_run):
    from pl_crawler import PolandCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'PZPM incremental (dry-run)'}
    c = PolandCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'PZPM monthly xlsx incremental (>= max month)'}

def handle_cz(conn, dry_run):
    from cz_crawler import CzechCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'SDA-CIA incremental (dry-run)'}
    c = CzechCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'SDA-CIA monthly xlsx incremental (>= max month)'}

def handle_gr(conn, dry_run):
    from gr_crawler import GrCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'SEAA incremental (dry-run)'}
    c = GrCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'SEAA comp.xlsx incremental (>= max month)'}

def handle_sk(conn, dry_run):
    from sk_crawler import SkCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'ZAP SR incremental (dry-run)'}
    c = SkCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'ZAP SR PDF incremental (>= max month)'}

def handle_us(conn, dry_run):
    from us_crawler import UsCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'goodcarbadcar incremental (dry-run)'}
    c = UsCrawler()
    n = c.crawl_all()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'goodcarbadcar.net brand pages incremental (idempotent)'}

def handle_au(conn, dry_run):
    from au_crawler import AuCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'CarExpert VFACTS incremental (dry-run)'}
    c = AuCrawler()
    n = c.crawl_all(max_pages=20)
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'CarExpert VFACTS articles incremental (idempotent)'}

def handle_br(conn, dry_run):
    from br_crawler import BrCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'Fenabrave PDF incremental (dry-run)'}
    c = BrCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'Fenabrave PDF incremental (>= max month)'}

def handle_ua(conn, dry_run):
    from ua_crawler import UkraineCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'autocentre.ua TOP-10 incremental (dry-run)'}
    c = UkraineCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'autocentre.ua TOP-10 incremental (idempotent)'}

def handle_tr(conn, dry_run):
    from tr_crawler import TrCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'ODMD XLSX monthly incremental (dry-run)'}
    c = TrCrawler()
    max_month = _get_max_month(conn, 'TR')
    latest = c.latest_available_month()
    if latest is None:
        return {'status': 'skip', 'records': 0, 'msg': 'ODMD latest month probe failed'}
    latest_da = date(latest[0], latest[1], 1)
    if max_month and latest_da <= max_month:
        return {'status': 'skip', 'records': 0, 'msg': f'TR latest={latest[0]}-{latest[1]:02d} <= DB max {max_month}'}
    n = c.crawl_month(latest[0], latest[1])
    return {'status': 'ok', 'records': n.get('records', 0), 'msg': 'ODMD XLSX monthly incremental'}

def handle_ru(conn, dry_run):
    from ru_crawler import RuCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'AEB PDF monthly incremental (dry-run)'}
    c = RuCrawler()
    max_month = _get_max_month(conn, 'RU')
    latest = c.latest_available_month()
    if latest is None:
        return {'status': 'skip', 'records': 0, 'msg': 'AEB latest month probe failed'}
    latest_da = date(latest[0], latest[1], 1)
    if max_month and latest_da <= max_month:
        return {'status': 'skip', 'records': 0, 'msg': f'RU latest={latest[0]}-{latest[1]:02d} <= DB max {max_month}'}
    n = c.crawl_month(latest[0], latest[1])
    return {'status': 'ok', 'records': n.get('records', 0), 'msg': 'AEB PDF monthly incremental (2024+ total only)'}

def handle_ro(conn, dry_run):
    from ro_crawler import RoCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'APIA PDF TOP5-10 incremental (dry-run)'}
    c = RoCrawler()
    max_month = _get_max_month(conn, 'RO')
    latest = c.latest_available_month()
    if latest is None:
        return {'status': 'skip', 'records': 0, 'msg': 'APIA latest month probe failed'}
    latest_da = date(latest[0], latest[1], 1)
    if max_month and latest_da <= max_month:
        return {'status': 'skip', 'records': 0, 'msg': f'RO latest={latest[0]}-{latest[1]:02d} <= DB max {max_month}'}
    n = c.crawl_month(latest[0], latest[1])
    return {'status': 'ok', 'records': n.get('records', 0), 'msg': 'APIA PDF TOP5-10 monthly incremental'}

def handle_my(conn, dry_run):
    from my_crawler import MyCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'Paultan maker+model incremental (dry-run)'}
    c = MyCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'Paultan (data.gov.my JPJ) maker+model incremental (idempotent)'}

def handle_th(conn, dry_run):
    from th_crawler import ThCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'autolife Thailand incremental (dry-run)'}
    c = ThCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'autolife Thailand brand/EV incremental (idempotent)'}

def handle_vn(conn, dry_run):
    from vn_crawler import VnCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'VAMA monthly incremental (dry-run)'}
    c = VnCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'VAMA monthly member sales incremental (idempotent)'}

def handle_ar(conn, dry_run):
    from ar_crawler import ArCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'ACARA TOP40 incremental (dry-run)'}
    c = ArCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'ACARA (motormagazine) TOP40 brand incremental (idempotent)'}

def handle_cl(conn, dry_run):
    from cl_crawler import ClCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'ANAC brand monthly incremental (dry-run)'}
    c = ClCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'ANAC brand monthly incremental (idempotent)'}

def handle_za(conn, dry_run):
    from za_crawler import ZaCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'NAAMSA Flash incremental (dry-run)'}
    c = ZaCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'NAAMSA Flash brand monthly incremental (idempotent)'}

def handle_nz(conn, dry_run):
    from nz_crawler import NzCrawler
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'NZTA MVR incremental (dry-run)'}
    c = NzCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n if n else 0, 'msg': 'NZTA MVR snapshot incremental (idempotent, snapshot-version dependent)'}

def handle_ons(conn, dry_run):
    import ons_energy_crawler as ons
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'GB ons energy incremental (dry-run)'}
    max_month = _get_max_month(conn, 'GB')
    latest = ons.latest_available_month()
    if latest is None:
        return {'status': 'skip', 'records': 0, 'msg': 'ONS latest month probe failed'}
    latest_date = date(latest[0], latest[1], 1)
    if max_month is not None and latest_date <= max_month:
        return {'status': 'skip', 'records': 0, 'msg': f'GB ons latest={latest[0]}-{latest[1]:02d} <= DB max {max_month}, no new data'}
    content = ons.download_ons_excel()
    records = ons.parse_energy_data(content, start_year=2024)
    n = 0
    if records:
        n = ons.save_to_database(records)
    return {'status': 'ok', 'records': n, 'msg': f'GB ons {latest[0]}-{latest[1]:02d} incremental'}


# ---------------------------------------------------------------
# 新增维度: 全球进出口(UN Comtrade) / 日本二手车出口(e-Stat) / 德国产量(VDA)
# ---------------------------------------------------------------

def handle_comtrade(conn, dry_run):
    """UN Comtrade 8703 乘用车进出口(49国×import/export), 写入 market_vehicle_trade_monthly"""
    import comtrade_crawler as ct
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'UN Comtrade 8703 incremental (dry-run, would query 49 countries)'}
    c = ct.ComtradeCrawler()
    res = c.crawl_incremental(back_months=6)
    return {'status': 'ok', 'records': res, 'msg': 'UN Comtrade 8703 incremental'}


def handle_jp_used(conn, dry_run):
    """日本 e-Stat 中古乘用车出口(HS8703 9位), 写入 market_vehicle_trade_monthly"""
    import japan_used_export_crawler as jue
    c = jue.JapanUsedExportCrawler()
    if dry_run:
        ids = c.discover_csv_ids(None, None)
        return {'status': 'ok', 'records': 0, 'msg': f'JP used export (dry-run, found {len(ids)} statInfIds)'}
    res = c.crawl_latest()
    return {'status': 'ok', 'records': res.get('records', 0), 'msg': 'JP e-Stat used car export incremental'}


def handle_vda(conn, dry_run):
    """德国 VDA Pkw 月度产量, 写入 market_production_monthly"""
    import vda_crawler as vda
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'DE VDA production incremental (dry-run)'}
    c = vda.VdaCrawler()
    res = c.crawl_incremental()
    return {'status': 'ok', 'records': res, 'msg': 'DE VDA production incremental'}


def handle_de_used(conn, dry_run):
    """德国 KBA FZ9 二手车所有权转移, 写入 market_used_vehicle_monthly"""
    import kba_used_crawler as ku
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'DE KBA used car transfers incremental (dry-run)'}
    c = ku.KbaUsedCrawler()
    res = c.crawl_incremental()
    return {'status': 'ok', 'records': res, 'msg': 'DE KBA FZ9 used car transfers incremental'}


def handle_gb_used(conn, dry_run):
    """英国 SMMT 二手车交易(DVLA), 写入 market_used_vehicle_monthly"""
    import smmt_used_crawler as su
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'GB SMMT used car transactions incremental (dry-run)'}
    c = su.SmmtUsedCrawler()
    res = c.crawl_incremental()
    return {'status': 'ok', 'records': res, 'msg': 'GB SMMT used car transactions incremental'}


def handle_jp_used_domestic(conn, dry_run):
    """日本 JADA 中古车登録台数, 写入 market_used_vehicle_monthly"""
    import jada_used_crawler as ju
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'JP JADA used car registrations incremental (dry-run)'}
    c = ju.JadaUsedCrawler()
    res = c.crawl_incremental()
    return {'status': 'ok', 'records': res, 'msg': 'JP JADA used car registrations incremental'}


def handle_cn_used(conn, dry_run):
    """中国 CADA 二手车月度交易量, 写入 market_used_vehicle_monthly"""
    import cada_used_crawler as cu
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'CN CADA used car transactions incremental (dry-run)'}
    c = cu.CadaUsedCrawler()
    res = c.crawl_incremental()
    return {'status': 'ok', 'records': res, 'msg': 'CN CADA used car transactions incremental'}


def handle_acea(conn, dry_run):
    """ACEA 欧洲月度新车注册 (国家×动力类型), 写入 market_sales_monthly"""
    import acea_crawler as ac
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'ACEA European monthly registrations (dry-run)'}
    c = ac.AceaCrawler()
    res = c.crawl_incremental()
    return {'status': 'ok', 'records': res, 'msg': 'ACEA European monthly registrations'}


def handle_hu(conn, dry_run):
    """匈牙利 KSH 季度/年度品牌级首次登记 (含二手车口径), 写入 market_sales_monthly"""
    import hu_crawler as hc
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'HU KSH quarterly/annual brand registrations (dry-run)'}
    c = hc.HuCrawler()
    res = c.crawl_incremental()
    return {'status': 'ok', 'records': res, 'msg': 'HU KSH quarterly/annual brand registrations'}


def handle_kz(conn, dry_run):
    """哈萨克斯坦 KAO 月度品牌级销量, 写入 market_sales_monthly"""
    import kz_crawler as kc
    if dry_run:
        return {'status': 'ok', 'records': 0, 'msg': 'KZ KAO monthly brand sales (dry-run)'}
    c = kc.KzCrawler()
    n = c.crawl_incremental()
    return {'status': 'ok', 'records': n, 'msg': 'KZ KAO monthly brand sales'}


# ---------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------

def _get_max_month(conn, country):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT MAX(source_month) AS m FROM market_sales_monthly WHERE country_code=%s", (country,))
    r = cur.fetchone()
    cur.close()
    return r['m'] if r and r['m'] else None

def _next_month(d):
    if d is None:
        return None
    y, m = d.year, d.month
    if m == 12:
        return (y + 1, 1)
    return (y, m + 1)

def _advance(y, m):
    if m == 12:
        return (y + 1, 1)
    return (y, m + 1)


# 源注册表：country -> (handler, source_name)
SOURCES = [
    ('AT', 'statistik_austria', handle_at),
    ('DE', 'KBA', handle_de),
    ('GB', 'SMMT', handle_gb),
    ('GB', 'ons', handle_ons),
    ('--', 'comtrade', handle_comtrade),
    ('JP', 'japan_used_export', handle_jp_used),
    ('DE', 'vda_production', handle_vda),
    ('IT', 'UNRAE', handle_it),
    ('FR', 'PFA', handle_fr),
    ('ES', 'ANFAC', handle_es),
    ('JP', 'JADA', handle_jp),
    ('BE', 'FEBIAC', handle_be),
    ('KR', 'KAMA', handle_kr),
    ('NL', 'BOVAG', handle_nl),
    ('CH', 'auto-schweiz', handle_ch),
    ('SE', 'mobilitysweden', handle_se),
    ('FI', 'aut', handle_fi),
    ('DK', 'mobilitydenmark', handle_dk),
    ('PT', 'acap', handle_pt),
    ('IE', 'ie_cso_tem28', handle_ie),
    ('PL', 'pzpm', handle_pl),
    ('CZ', 'SDA_CIA', handle_cz),
    ('GR', 'seaa', handle_gr),
    ('SK', 'sk_zapsr_monthly_registrations', handle_sk),
    ('US', 'goodcarbadcar_us', handle_us),
    ('AU', 'carexpert_vfacts', handle_au),
    ('BR', 'fenabrave_emplacamentos', handle_br),
    ('UA', 'autocentre_ua', handle_ua),
    ('TR', 'odmd_tr_retail_sales', handle_tr),
    ('RU', 'aeb', handle_ru),
    ('RO', 'apia', handle_ro),
    ('MY', 'paultan_org_car_sales_data_maker', handle_my),
    ('TH', 'autolifethailand_tv', handle_th),
    ('VN', 'vama_monthly_sales', handle_vn),
    ('AR', 'ar_acara_informe_de_mercado', handle_ar),
    ('CL', 'cl_anac_brand_monthly', handle_cl),
    ('ZA', 'naamsa_monthly_new_vehicle_sales', handle_za),
    ('NZ', 'nzta_mvr_monthly_snapshot', handle_nz),
    ('DE', 'kba_de_used_car_transfers_monthly', handle_de_used),
    ('GB', 'smmt_gb_used_car_transactions_monthly', handle_gb_used),
    ('JP', 'jada_jp_used_car_registrations_monthly', handle_jp_used_domestic),
    ('CN', 'cada_cn_used_car_transactions_monthly', handle_cn_used),
    ('EU', 'acea', handle_acea),
    ('HU', 'ksh_stadat_sza', handle_hu),
    ('KZ', 'kz_kao_monthly_brand', handle_kz),
]


def log_run(conn, country, source_name, status, records, msg, dry_run):
    if dry_run:
        return
    cur = conn.cursor()
    now = datetime.now()
    try:
        cur.execute("""
            INSERT INTO crawl_run_log
                (module, source_name, country_code, started_at, ended_at,
                 total_urls, crawled_urls, new_items, updated_items, skipped_items, failed_urls,
                 status, error_summary, total_pages, records_found, records_saved)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (f'{source_name}_crawler', source_name, country, now, now,
              1, 1, records, 0, 0, 0, status, msg, 1, records, records))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f'  [warn] log_run failed: {e}')


def update_registry(conn, country, source_name, status, dry_run):
    if dry_run:
        return
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE market_source_registry
            SET last_crawl_time = %s,
                last_available_month = (
                    SELECT MAX(source_month) FROM market_sales_monthly WHERE country_code = %s
                )
            WHERE country_code = %s AND UPPER(source_name) = UPPER(%s)
        """, (datetime.now(), country, country, source_name))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f'  [warn] update_registry failed: {e}')


def main():
    parser = argparse.ArgumentParser(description='月度增量调度')
    parser.add_argument('--country', help='只跑指定国家代码')
    parser.add_argument('--dry-run', action='store_true', help='只打印计划不执行')
    args = parser.parse_args()

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    print(f'=== 月度增量扫描 {datetime.now():%Y-%m-%d %H:%M:%S} ===')

    results = {}
    for country, source_name, handler in SOURCES:
        if args.country and country.upper() != args.country.upper():
            continue
        print(f'\n--- {country} {source_name} ---')
        try:
            result = handler(conn, args.dry_run)
            results[(country, source_name)] = result
            print(f'  {result["status"]}: {result["msg"]} (records={result["records"]})')
            log_run(conn, country, source_name, result['status'], result['records'], result['msg'], args.dry_run)
            update_registry(conn, country, source_name, result['status'], args.dry_run)
        except Exception as e:
            import traceback
            print(f'  ERROR: {e}')
            traceback.print_exc()
            results[(country, source_name)] = {'status': 'error', 'records': 0, 'msg': str(e)}
            log_run(conn, country, source_name, 'error', 0, str(e), args.dry_run)

    conn.close()
    print('\n=== 汇总 ===')
    ok = sum(1 for v in results.values() if v['status'] == 'ok')
    skip = sum(1 for v in results.values() if v['status'] == 'skip')
    err = sum(1 for v in results.values() if v['status'] == 'error')
    total_records = sum(v['records'] for v in results.values())
    print(f'ok={ok} skip={skip} error={err} total_records={total_records}')


if __name__ == '__main__':
    main()
