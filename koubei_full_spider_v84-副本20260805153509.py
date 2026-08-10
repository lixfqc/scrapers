# -*- coding: utf-8 -*-
"""
汽车之家口碑数据爬虫（完整版V8.4 - 记录与去重版）
功能：
1. 车系列表管理：查看、添加、删除车系
2. 全量爬取：爬取全部口碑数据，逐页保存，即时转移
3. 增量更新：只爬取新增口碑，节约资源
4. 批量爬取：支持全部车系批量处理
5. 反爬优化：分层延迟、失败重试、浏览器重启
6. 数据安全：逐页保存、即时转移、失败恢复
7. 分页验证：从页码验证口碑数量
8. 爬取记录：生成MD文档记录每次爬取详情
9. 失败重爬：从记录中读取失败页数，重新爬取
10. 数据去重：与data_koubei校对，避免重复入库

使用方法:
    python koubei_full_spider_v84.py              # 交互模式
    python koubei_full_spider_v84.py --chexi 阿维塔06 --id 7752  # 全量爬取
    python koubei_full_spider_v84.py --chexi 阿维塔06 --id 7752 --incremental  # 增量更新
"""

import pandas as pd
import re
import time
import random
import argparse
import json
from datetime import datetime
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import os

from chexi_manager import ChexiManager
from incremental_crawler import IncrementalCrawler


class CrawlRecordManager:
    """爬取记录管理器 - 负责生成和管理爬取记录MD文档"""
    
    RECORD_FILE = "爬取记录.md"
    
    def __init__(self):
        self.record_file = self.RECORD_FILE
    
    def _read_existing_records(self):
        """读取已有记录"""
        if not os.path.exists(self.record_file):
            return []
        
        try:
            with open(self.record_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 解析MD文档中的记录
            records = []
            # 按车系名称分割记录
            sections = re.split(r'## ', content)
            for section in sections[1:]:  # 跳过第一个空部分
                lines = section.strip().split('\n')
                if not lines:
                    continue
                
                chexi_name = lines[0].strip()
                record = {'chexi_name': chexi_name, 'entries': []}
                
                # 解析每个记录条目
                entry_text = '\n'.join(lines[1:])
                entries = re.split(r'### 记录 \d+', entry_text)
                
                for entry in entries[1:]:
                    entry_data = self._parse_entry(entry)
                    if entry_data:
                        record['entries'].append(entry_data)
                
                records.append(record)
            
            return records
        except Exception as e:
            print(f"读取记录文件失败: {e}")
            return []
    
    def _parse_entry(self, entry_text):
        """解析单个记录条目"""
        entry = {}
        
        # 提取日期
        date_match = re.search(r'爬取日期[:：]\s*(.+)', entry_text)
        if date_match:
            entry['date'] = date_match.group(1).strip()
        
        # 提取网页显示数量
        web_match = re.search(r'网页显示口碑数[:：]\s*(\d+)', entry_text)
        if web_match:
            entry['web_count'] = int(web_match.group(1))
        
        # 提取爬取数量
        crawl_match = re.search(r'本次爬取口碑数[:：]\s*(\d+)', entry_text)
        if crawl_match:
            entry['crawl_count'] = int(crawl_match.group(1))
        
        # 提取新增数量
        new_match = re.search(r'本次新增口碑数[:：]\s*(\d+)', entry_text)
        if new_match:
            entry['new_count'] = int(new_match.group(1))
        
        # 提取失败页数
        failed_match = re.search(r'失败页面[:：]\s*\[(.*?)\]', entry_text)
        if failed_match:
            failed_str = failed_match.group(1).strip()
            if failed_str:
                entry['failed_pages'] = [int(p.strip()) for p in failed_str.split(',') if p.strip().isdigit()]
            else:
                entry['failed_pages'] = []
        else:
            failed_match2 = re.search(r'失败页面[:：]\s*(.+)', entry_text)
            if failed_match2:
                entry['failed_pages'] = []
        
        # 提取完整率
        rate_match = re.search(r'数据完整率[:：]\s*([\d.]+)%', entry_text)
        if rate_match:
            entry['completion_rate'] = float(rate_match.group(1))
        
        return entry if 'date' in entry else None
    
    def add_record(self, chexi_name, web_count, crawl_count, new_count, 
                   failed_pages, completion_rate, data_quality):
        """添加新的爬取记录"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 读取已有记录
        records = self._read_existing_records()
        
        # 查找或创建车系记录
        chexi_record = None
        for record in records:
            if record['chexi_name'] == chexi_name:
                chexi_record = record
                break
        
        if chexi_record is None:
            chexi_record = {'chexi_name': chexi_name, 'entries': []}
            records.append(chexi_record)
        
        # 添加新记录
        new_entry = {
            'date': now,
            'web_count': web_count,
            'crawl_count': crawl_count,
            'new_count': new_count,
            'failed_pages': failed_pages.copy() if failed_pages else [],
            'completion_rate': completion_rate,
            'data_quality': data_quality
        }
        chexi_record['entries'].append(new_entry)
        
        # 重新生成MD文件
        self._write_records(records)
        print(f"\n爬取记录已保存到: {self.record_file}")
    
    def _write_records(self, records):
        """写入记录到MD文件"""
        with open(self.record_file, 'w', encoding='utf-8') as f:
            f.write("# 汽车之家口碑数据爬取记录\n\n")
            f.write(f"> 自动生成于: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            for record in records:
                f.write(f"## {record['chexi_name']}\n\n")
                
                for i, entry in enumerate(record['entries'], 1):
                    f.write(f"### 记录 {i}\n\n")
                    f.write(f"- **爬取日期**: {entry['date']}\n")
                    f.write(f"- **网页显示口碑数**: {entry.get('web_count', 0)} 条\n")
                    f.write(f"- **本次爬取口碑数**: {entry.get('crawl_count', 0)} 条\n")
                    f.write(f"- **本次新增口碑数**: {entry.get('new_count', 0)} 条\n")
                    
                    failed = entry.get('failed_pages', [])
                    if failed:
                        f.write(f"- **失败页面**: [{', '.join(map(str, failed))}]\n")
                    else:
                        f.write(f"- **失败页面**: 无\n")
                    
                    f.write(f"- **数据完整率**: {entry.get('completion_rate', 0):.1f}%\n")
                    f.write(f"- **数据质量**: {entry.get('data_quality', '未知')}\n")
                    f.write("\n")
                
                f.write("---\n\n")
    
    def get_failed_pages(self, chexi_name):
        """获取指定车系的失败页面列表（返回最新的未成功记录）"""
        records = self._read_existing_records()
        
        for record in records:
            if record['chexi_name'] == chexi_name:
                # 从最新的记录开始查找，返回第一个有失败页数的记录
                for entry in reversed(record['entries']):
                    failed = entry.get('failed_pages', [])
                    if failed:
                        return failed
                return []
        
        return []
    
    def update_failed_pages(self, chexi_name, pages_crawled, pages_still_failed):
        """更新失败页面记录"""
        records = self._read_existing_records()
        
        for record in records:
            if record['chexi_name'] == chexi_name:
                # 找到最新的记录并更新失败页数
                if record['entries']:
                    latest = record['entries'][-1]
                    current_failed = set(latest.get('failed_pages', []))
                    
                    # 移除已成功爬取的页数
                    current_failed -= set(pages_crawled)
                    
                    # 更新记录
                    latest['failed_pages'] = sorted(list(current_failed))
                    latest['date'] += f" (更新: 成功重爬{len(pages_crawled)}页, 仍失败{len(pages_still_failed)}页)"
                
                self._write_records(records)
                return True
        
        return False
    
    def display_records(self):
        """显示所有记录摘要"""
        records = self._read_existing_records()
        
        if not records:
            print("\n暂无爬取记录")
            return
        
        print("\n" + "=" * 80)
        print("爬取记录摘要")
        print("=" * 80)
        
        for record in records:
            print(f"\n车系: {record['chexi_name']}")
            print("-" * 60)
            
            if not record['entries']:
                print("  暂无记录")
                continue
            
            latest = record['entries'][-1]
            print(f"  最新记录日期: {latest['date']}")
            print(f"  网页显示: {latest.get('web_count', 0)} 条")
            print(f"  已爬取: {latest.get('crawl_count', 0)} 条")
            print(f"  完整率: {latest.get('completion_rate', 0):.1f}%")
            
            failed = latest.get('failed_pages', [])
            if failed:
                print(f"  失败页面: {failed}")
            else:
                print(f"  失败页面: 无")
        
        print("=" * 80)


class FullKoubeiSpider:
    """完整版口碑爬虫 - V8.4（记录与去重版）"""

    def __init__(self):
        self.db_config = {
            'user': 'postgres',
            'password': '800124',
            'host': 'localhost',
            'port': 5432,
            'dbname': 'koubei'
        }
        self.engine = None
        self.local_engine = None
        self.driver = None
        self.series_id = None
        self.base_url = None
        self.chexi_name = None
        self.web_koubei_count = 0
        self.chexi_manager = ChexiManager()
        self.incremental_crawler = None
        self.failed_pages = []  # 记录失败页面
        self.request_count = 0  # 请求计数器，用于递增延迟
        self.record_manager = CrawlRecordManager()  # 爬取记录管理器
        self.existing_koubei_ids = set()  # 数据库中已有的口碑ID集合

    def find_chrome_path(self):
        possible_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        return None

    def init_database(self):
        try:
            connection_string = f'postgresql+psycopg2://{self.db_config["user"]}:{self.db_config["password"]}@{self.db_config["host"]}:{self.db_config["port"]}/{self.db_config["dbname"]}'
            self.engine = create_engine(connection_string)
            print("数据库连接成功")
            try:
                local_cs = "postgresql+psycopg2://postgres:800124@localhost:5432/koubei"
                self.local_engine = create_engine(local_cs)
                print("本地PG连接成功")
            except Exception as local_e:
                print(f"本地PG连接失败: {local_e}")
            return True
        except Exception as e:
            print(f"数据库连接失败: {str(e)}")
            return False

    def create_koubei_table(self):
        try:
            with self.engine.connect() as conn:
                conn.execute(text("TRUNCATE TABLE koubei"))
                conn.commit()
                print("koubei表已清空")
                return True
        except Exception as e:
            if "does not exist" in str(e) or "不存在" in str(e):
                try:
                    with self.engine.connect() as conn:
                        conn.execute(text("""
                            CREATE TABLE koubei (
                                id SERIAL PRIMARY KEY,
                                chexi TEXT,
                                chekuan TEXT,
                                niankuan TEXT,
                                fabiao_time TEXT,
                                xingshi TEXT,
                                jiage TEXT,
                                goumai_time TEXT,
                                goumai_didian TEXT,
                                shengchan_dizhi TEXT,
                                koubei_id TEXT,
                                yonghu TEXT,
                                chezhu_weizhi TEXT,
                                pingfen TEXT,
                                zhaiyao TEXT,
                                paqu_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                        """))
                        conn.commit()
                        print("koubei表创建成功")
                        return True
                except Exception as e2:
                    print(f"创建表失败: {str(e2)}")
                    return False
            else:
                print(f"清空表失败: {str(e)}")
                return False

    def init_browser(self):
        try:
            chrome_options = Options()
            # 支持 headless 模式：设置环境变量 HEADLESS=1 或通过参数传入
            headless = os.environ.get('HEADLESS', '0') == '1'
            if headless:
                chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            # 反爬优化：添加随机User-Agent
            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            ]
            chrome_options.add_argument(f'--user-agent={random.choice(user_agents)}')
            # 反爬优化：禁用自动化检测
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)

            chrome_path = self.find_chrome_path()
            if chrome_path:
                chrome_options.binary_location = chrome_path

            chromedriver_path = os.path.join(os.getcwd(), "chromedriver.exe")
            if os.path.exists(chromedriver_path):
                service = Service(chromedriver_path)
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                self.driver = webdriver.Chrome(options=chrome_options)

            # 反爬优化：执行CDP命令禁用webdriver检测
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
            })

            print("浏览器启动成功（已启用反爬优化）")
            return True
        except Exception as e:
            print(f"浏览器启动失败: {str(e)}")
            return False

    def restart_browser(self):
        """重启浏览器"""
        print("\n【系统维护】重启浏览器...")
        if self.driver:
            self.driver.quit()
        time.sleep(random.uniform(10, 20))
        return self.init_browser()

    def load_existing_koubei_ids(self, chexi_name):
        """加载data_koubei表中已有的口碑ID，用于去重"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT DISTINCT koubei_id 
                        FROM data_koubei 
                        WHERE chexi = :chexi AND koubei_id IS NOT NULL AND koubei_id != ''
                    """),
                    {"chexi": chexi_name}
                )
                self.existing_koubei_ids = {row[0] for row in result}
                print(f"从data_koubei加载到 {len(self.existing_koubei_ids)} 个已有口碑ID（用于去重）")
                return True
        except Exception as e:
            print(f"加载已有口碑ID失败: {e}")
            self.existing_koubei_ids = set()
            return False

    def filter_duplicates(self, koubei_list):
        """过滤掉数据库中已存在的口碑数据"""
        if not self.existing_koubei_ids:
            return koubei_list
        
        new_list = []
        duplicates_count = 0
        
        for item in koubei_list:
            koubei_id = item.get('koubei_id', '')
            if koubei_id and koubei_id in self.existing_koubei_ids:
                duplicates_count += 1
                continue  # 跳过已存在的数据
            new_list.append(item)
        
        if duplicates_count > 0:
            print(f"  去重: 跳过 {duplicates_count} 条已存在数据")
        
        return new_list

    def get_web_koubei_count(self):
        """从网页获取口碑总数 - V8.6改进：使用'最新发表'排序"""
        try:
            url = f"{self.base_url}#2"
            self.driver.get(url)
            time.sleep(5)

            # [V8.6新增] 点击"最新发表"选项卡，让新增口碑集中在前几页
            try:
                from selenium.webdriver.common.by import By
                newest_btn = self.driver.find_element(By.XPATH, "//*[text()='最新发表']")
                self.driver.execute_script("arguments[0].click();", newest_btn)
                time.sleep(3)
                print("已切换到'最新发表'排序")
            except Exception:
                print("未找到'最新发表'按钮，使用默认排序")

            html = self.driver.page_source
            soup = BeautifulSoup(html, 'html.parser')

            # [V8.6修复] 提取网页最新口碑发表时间，供增量快速跳过使用
            self.web_newest_time = None
            date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2})')
            date_matches = date_pattern.findall(html)
            if date_matches:
                # 取最新日期（口碑按时间倒序排列，第一个日期即最新）
                for d in date_matches:
                    try:
                        parsed = datetime.strptime(d, '%Y-%m-%d')
                        if parsed.year >= 2020 and parsed.year <= 2030:
                            self.web_newest_time = d
                            print(f"网页最新口碑发表时间: {d}")
                            break
                    except:
                        continue

            count_from_text = 0
            count_from_pagination = 0

            # 策略1：查找口碑列表区域的统计信息（最准确）
            koubei_count_elems = soup.find_all(string=re.compile(r'(\d+)\s*条口碑'))
            for elem in koubei_count_elems:
                match = re.search(r'(\d+)\s*条口碑', str(elem))
                if match:
                    count = int(match.group(1))
                    if 1 <= count <= 50000:
                        count_from_text = count
                        print(f"网页显示口碑数量: {count} 条")
                        break

            # 策略2：查找"共X篇口碑"格式
            if count_from_text == 0:
                count_patterns = [
                    r'共\s*(\d+)\s*篇口碑',
                    r'(\d+)\s*条口碑',
                    r'口碑\s*[([\[]?\s*(\d+)\s*[)\]]?',
                ]

                text = soup.get_text()
                for pattern in count_patterns:
                    match = re.search(pattern, text)
                    if match:
                        count = int(match.group(1))
                        if 1 <= count <= 50000:
                            count_from_text = count
                            print(f"网页显示口碑数量: {count} 条")
                            break

            # 策略3：查找特定的class包含口碑数量
            if count_from_text == 0:
                count_divs = soup.find_all(['div', 'span', 'p'], class_=re.compile(r'count|num|total'))
                for div in count_divs:
                    text = div.get_text(strip=True)
                    match = re.search(r'(\d+)', text)
                    if match:
                        count = int(match.group(1))
                        if 1 <= count <= 50000:
                            count_from_text = count
                            print(f"网页显示口碑数量: {count} 条")
                            break

            # 策略4：从分页页码获取最大页数，推算口碑数量
            pagination_links = soup.find_all('a', class_=re.compile(r'pagination|page'))
            max_page = 0
            for link in pagination_links:
                page_text = link.get_text(strip=True)
                if page_text.isdigit():
                    page_num = int(page_text)
                    if page_num > max_page:
                        max_page = page_num

            if max_page == 0:
                page_patterns = [
                    r'<a[^>]*?>\s*(\d+)\s*</a>',
                    r'page[=/](\d+)',
                ]
                for pattern in page_patterns:
                    matches = re.findall(pattern, html)
                    for match in matches:
                        page_num = int(match)
                        if page_num > max_page and page_num < 1000:
                            max_page = page_num

            if max_page > 0:
                estimated_count = max_page * 10
                count_from_pagination = estimated_count
                print(f"分页显示最大页数: {max_page} 页，推算口碑数约: {estimated_count} 条")
                # 保存分页最大页数，供calculate_auto_pages使用
                self.pagination_max_page = max_page

            # 综合判断
            if count_from_text > 0 and count_from_pagination > 0:
                if abs(count_from_text - count_from_pagination) / count_from_text < 0.2:
                    print(f"两种方式验证一致，最终口碑数量: {count_from_text} 条")
                    return count_from_text
                else:
                    final_count = max(count_from_text, count_from_pagination)
                    print(f"两种方式差异较大，取较大值: {final_count} 条")
                    return final_count
            elif count_from_text > 0:
                return count_from_text
            elif count_from_pagination > 0:
                print(f"未能从文本获取口碑数，使用分页推算: {count_from_pagination} 条")
                return count_from_pagination
            else:
                print("未能从网页获取口碑数量，将使用默认值")
                return 0
        except Exception as e:
            print(f"获取网页口碑数量失败: {str(e)}")
            return 0

    def calculate_auto_pages(self, koubei_count):
        """根据口碑数量自动计算建议页数 - V8.5改进：使用分页最大页数+1，不再增加余量"""
        # 优先使用从网页获取的分页最大页数
        if hasattr(self, 'pagination_max_page') and self.pagination_max_page > 0:
            suggested_pages = self.pagination_max_page + 1
            print(f"分页显示最大页数: {self.pagination_max_page} 页")
            print(f"建议设置: {suggested_pages} 页（最大页数+1）")
            return suggested_pages
        
        # 备用方案：根据口碑数量计算
        if koubei_count <= 0:
            return 10

        actual_pages = (koubei_count + 9) // 10
        suggested_pages = actual_pages + 1
        print(f"口碑数量: {koubei_count} 条")
        print(f"实际需要: {actual_pages} 页")
        print(f"建议设置: {suggested_pages} 页（实际页数+1）")
        return suggested_pages

    def get_page_with_retry(self, page_num=1, skip_parse=False):
        """获取页面，带重试机制 - V8.5改进：支持快速跳转到目标页"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if page_num == 1:
                    url = f"{self.base_url}#2"
                    print(f"正在获取第 {page_num} 页...")
                    self.driver.get(url)
                    time.sleep(5)
                    return self.driver.page_source
                else:
                    from selenium.webdriver.common.by import By
                    
                    # 先检查当前是否已经在目标页
                    current_html = self.driver.page_source
                    soup = BeautifulSoup(current_html, 'html.parser')
                    
                    # 检查当前页码是否已经是目标页（通过查找active状态的页码）
                    active_page = soup.find('a', class_=re.compile(r'active|current|selected'))
                    if active_page:
                        try:
                            current_page_num = int(active_page.get_text(strip=True))
                            if current_page_num == page_num:
                                print(f"当前已在第 {page_num} 页，直接返回")
                                return current_html
                        except:
                            pass
                    
                    # 查找目标页码按钮
                    page_links = self.driver.find_elements(By.XPATH, f"//a[text()='{page_num}']")
                    if page_links:
                        print(f"正在点击第 {page_num} 页...")
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_links[0])
                        time.sleep(1)
                        self.driver.execute_script("arguments[0].click();", page_links[0])
                        time.sleep(5)
                        return self.driver.page_source
                    else:
                        # 如果找不到目标页码，尝试点击"下一页"按钮逐步跳转
                        print(f"未找到第 {page_num} 页的按钮，尝试点击下一页...")
                        next_btn = self.driver.find_elements(By.XPATH, "//a[contains(text(),'下一页') or contains(@class,'next')]")
                        if next_btn:
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn[0])
                            time.sleep(1)
                            self.driver.execute_script("arguments[0].click();", next_btn[0])
                            time.sleep(5)
                            # 返回当前页面，让调用方判断是否继续
                            return self.driver.page_source
                        else:
                            print(f"未找到第 {page_num} 页的按钮，也无法点击下一页")
                            return None
            except Exception as e:
                print(f"获取第 {page_num} 页失败（尝试 {attempt + 1}/{max_retries}）: {str(e)}")
                if attempt < max_retries - 1:
                    wait_time = 10 * (attempt + 1)
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    print(f"第 {page_num} 页重试次数用完，标记为失败")
                    return None
        return None

    def navigate_to_page(self, target_page):
        """快速跳转到目标页 - 只跳转不爬取，一页一页翻直到到达目标页"""
        if target_page <= 1:
            return True
        
        print(f"\n【快速跳转】从当前页跳转到第 {target_page} 页...")
        from selenium.webdriver.common.by import By
        
        max_navigate_attempts = target_page * 2  # 防止无限循环
        attempts = 0
        
        while attempts < max_navigate_attempts:
            attempts += 1
            
            # 获取当前页面HTML
            current_html = self.driver.page_source
            soup = BeautifulSoup(current_html, 'html.parser')
            
            # 检查当前页码
            active_page = soup.find('a', class_=re.compile(r'active|current|selected'))
            if active_page:
                try:
                    current_page_num = int(active_page.get_text(strip=True))
                    if current_page_num == target_page:
                        print(f"✓ 已到达第 {target_page} 页")
                        return True
                except:
                    pass
            
            # 尝试直接点击目标页码
            page_links = self.driver.find_elements(By.XPATH, f"//a[text()='{target_page}']")
            if page_links:
                print(f"  直接点击第 {target_page} 页...")
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_links[0])
                time.sleep(1)
                self.driver.execute_script("arguments[0].click();", page_links[0])
                time.sleep(3)
                continue
            
            # 如果找不到目标页码，点击"下一页"
            next_btn = self.driver.find_elements(By.XPATH, "//a[contains(text(),'下一页') or contains(@class,'next')]")
            if next_btn:
                print(f"  点击下一页...")
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn[0])
                time.sleep(1)
                self.driver.execute_script("arguments[0].click();", next_btn[0])
                time.sleep(3)
            else:
                print(f"  无法继续跳转，未找到下一页按钮")
                return False
        
        print(f"  跳转次数过多，可能无法到达第 {target_page} 页")
        return False

    def extract_koubei_from_li(self, li):
        try:
            full_text = li.get_text(strip=True)

            yonghu = ''
            match = re.search(r'^(.{2,20}?)关注', full_text)
            if match:
                yonghu = match.group(1).strip()

            fabiao_time = ''
            time_elem = li.find('p', class_=re.compile(r'list_timeline__'))
            if time_elem:
                time_text = time_elem.get_text(strip=True)
                match = re.search(r'(\d{4}-\d{2}-\d{2})', time_text)
                if match:
                    fabiao_time = match.group(1)

            chekuan = ''
            car_elem = li.find('div', class_=re.compile(r'list_car__'))
            if car_elem:
                car_text = car_elem.get_text(strip=True)
                car_text = re.sub(r'询底价.*$', '', car_text)
                match = re.search(r'(\d{4}款\s+.+?)(?:$|202)', car_text)
                if match:
                    chekuan = match.group(1).strip()
                else:
                    chekuan = car_text.replace(self.chexi_name, '').strip()

            key_elems = li.find_all('div', class_=re.compile(r'list_key__'))
            key_values = [elem.get_text(strip=True) for elem in key_elems]

            xingshi = ''
            jiage = ''
            goumai_time = ''
            goumai_didian = ''

            for val in key_values:
                if 'km' in val and not xingshi:
                    match = re.search(r'(\d+)km', val)
                    if match:
                        xingshi = match.group(0)
                elif '万' in val and not jiage:
                    match = re.search(r'(\d+\.?\d*)万', val)
                    if match:
                        jiage = match.group(0)
                elif re.match(r'^\d{4}-\d{2}$', val) and not goumai_time:
                    goumai_time = val
                elif val and not goumai_didian and val not in [xingshi, jiage, goumai_time]:
                    if not any(unit in val for unit in ['km', 'kWh', 'L', '万']):
                        goumai_didian = val

            pingfen = ''
            score_elem = li.find('ul', class_=re.compile(r'list_dimension_score__'))
            if score_elem:
                score_text = score_elem.get_text(strip=True)
                match = re.search(r'^(\d+(?:\.\d+)?)', score_text)
                if match:
                    pingfen = match.group(1)
            else:
                match = re.search(r'综合口碑评分\s*(\d+(?:\.\d+)?)', full_text)
                if match:
                    pingfen = match.group(1)

            koubei_id = ''
            links = li.find_all('a', href=True)
            for link in links:
                href = link.get('href', '')
                match = re.search(r'/detail/view_([a-zA-Z0-9]+)\.html', href)
                if match:
                    koubei_id = match.group(1)
                    break

            zhaiyao = ''
            feeling_elem = li.find('div', class_=re.compile(r'list_feeling__'))
            if feeling_elem:
                zhaiyao = feeling_elem.get_text(strip=True)[:500]

            niankuan = ''
            if chekuan:
                year_match = re.search(r'(\d{4})款', chekuan)
                if year_match:
                    niankuan = f"{self.chexi_name} {year_match.group(1)}款"
                else:
                    niankuan = f"{self.chexi_name} {chekuan}"

            return {
                'chexi': self.chexi_name,
                'chekuan': chekuan,
                'niankuan': niankuan,
                'fabiao_time': fabiao_time,
                'xingshi': xingshi,
                'jiage': jiage,
                'goumai_time': goumai_time,
                'goumai_didian': goumai_didian,
                'shengchan_dizhi': '',
                'koubei_id': koubei_id,
                'yonghu': yonghu,
                'chezhu_weizhi': goumai_didian,
                'pingfen': pingfen,
                'zhaiyao': zhaiyao,
            }
        except Exception as e:
            print(f"解析单项失败: {str(e)}")
            return None

    def parse_koubei_data(self, html_content):
        koubei_list = []
        if not html_content:
            return koubei_list

        soup = BeautifulSoup(html_content, 'html.parser')
        li_elements = soup.find_all('li', class_='clearfix')

        for li in li_elements:
            text = li.get_text(strip=True)
            if '发表口碑' in text and '202' in text and '款' in text:
                koubei_info = self.extract_koubei_from_li(li)
                if koubei_info and koubei_info['chekuan']:
                    koubei_list.append(koubei_info)

        return koubei_list

    def save_to_koubei_table(self, data):
        """保存数据到koubei表（逐页保存）"""
        if not data:
            return False

        try:
            df = pd.DataFrame(data)
            df.to_sql('koubei', con=self.engine, if_exists='append', index=False, chunksize=100)
            return True
        except Exception as e:
            print(f"保存到koubei表失败: {str(e)}")
            return False

    def get_koubei_count_from_db(self):
        """从数据库获取当前车系的口碑数量"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT COUNT(*) FROM koubei WHERE chexi = :chexi"),
                    {"chexi": self.chexi_name}
                )
                return result.fetchone()[0]
        except Exception as e:
            print(f"获取数据库口碑数量失败: {str(e)}")
            return 0

    def append_to_data_koubei(self):
        """将koubei表数据追加到data_koubei"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS data_koubei (
                        id SERIAL PRIMARY KEY,
                        chexi TEXT,
                        chekuan TEXT,
                        niankuan TEXT,
                        fabiao_time TEXT,
                        xingshi TEXT,
                        jiage TEXT,
                        goumai_time TEXT,
                        goumai_didian TEXT,
                        shengchan_dizhi TEXT,
                        koubei_id TEXT,
                        yonghu TEXT,
                        chezhu_weizhi TEXT,
                        pingfen TEXT,
                        zhaiyao TEXT,
                        paqu_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))

                # [V8.6修复] 追加前先按 koubei_id 去重，避免重复入库
                conn.execute(text("""
                    DELETE FROM koubei
                    WHERE koubei_id IN (
                        SELECT koubei_id FROM data_koubei
                        WHERE koubei_id IS NOT NULL AND koubei_id != ''
                    )
                """))
                conn.commit()

                conn.execute(text("""
                    INSERT INTO data_koubei 
                    (chexi, chekuan, niankuan, fabiao_time, xingshi, jiage, goumai_time, 
                     goumai_didian, shengchan_dizhi, koubei_id, yonghu, chezhu_weizhi, 
                     pingfen, zhaiyao, paqu_time)
                    SELECT chexi, chekuan, niankuan, fabiao_time, xingshi, jiage, goumai_time,
                           goumai_didian, shengchan_dizhi, koubei_id, yonghu, chezhu_weizhi,
                           pingfen, zhaiyao, paqu_time
                    FROM koubei
                """))

                conn.commit()

                count_result = conn.execute(text("SELECT COUNT(*) FROM data_koubei WHERE chexi = :chexi"), 
                                          {"chexi": self.chexi_name})
                total_in_data = count_result.fetchone()[0]

                print(f"数据已追加到data_koubei表")
                print(f"data_koubei表中 {self.chexi_name} 的总数据量: {total_in_data} 条")
            if self.local_engine:
                try:
                    with self.local_engine.connect() as lc:
                        # [V8.6修复] 本地追加前同样按 koubei_id 去重
                        lc.execute(text("""
                            DELETE FROM koubei
                            WHERE koubei_id IN (
                                SELECT koubei_id FROM data_koubei
                                WHERE koubei_id IS NOT NULL AND koubei_id != ''
                            )
                        """))
                        lc.execute(text("INSERT INTO data_koubei (chexi, chekuan, niankuan, fabiao_time, xingshi, jiage, goumai_time, goumai_didian, shengchan_dizhi, koubei_id, yonghu, chezhu_weizhi, pingfen, zhaiyao, paqu_time) SELECT chexi, chekuan, niankuan, fabiao_time, xingshi, jiage, goumai_time, goumai_didian, shengchan_dizhi, koubei_id, yonghu, chezhu_weizhi, pingfen, zhaiyao, paqu_time FROM koubei"))
                        lc.commit()
                        print("本地data_koubei追加成功")
                except Exception as local_e:
                    print(f"本地追加失败: {local_e}")
            return True

        except Exception as e:
            print(f"追加到data_koubei表失败: {str(e)}")
            return False

    def crawl_all_koubei_with_save(self, max_pages=50, incremental=False, target_pages=None):
        """逐页爬取并保存（核心改进V8.4）"""
        all_koubei = []
        consecutive_empty = 0
        total_skipped = 0
        self.failed_pages = []
        self.request_count = 0
        recovery_attempts = 0
        max_recovery_attempts = 3

        # 如果指定了目标页面（用于重爬失败页面），则只爬取这些页面
        if target_pages:
            pages_to_crawl = sorted(target_pages)
            print(f"【重爬模式】只爬取失败的页面: {pages_to_crawl}")
        else:
            pages_to_crawl = list(range(1, max_pages + 1))

        print("=" * 80)
        print(f"开始爬取 {self.chexi_name} 的口碑数据...")
        if incremental:
            print("【增量模式】只爬取新增口碑")
        if target_pages:
            print(f"【重爬模式】目标页面: {target_pages}")
        print(f"目标URL: {self.base_url}")
        print(f"最大页数: {max_pages}")
        print("=" * 80)

        for page in pages_to_crawl:
            self.request_count += 1

            # 获取页面（带重试）
            html = self.get_page_with_retry(page)

            if not html:
                consecutive_empty += 1
                self.failed_pages.append(page)
                if consecutive_empty >= 3:
                    if len(all_koubei) >= self.web_koubei_count and self.web_koubei_count > 0:
                        print(f"已连续3页获取失败，但爬取数({len(all_koubei)})已超过网页显示数({self.web_koubei_count})，正常结束")
                        break
                    
                    print("连续3页获取失败，执行反爬恢复策略...")
                    recovery_result = self._anti_crawl_recovery(page, incremental, all_koubei)
                    if recovery_result:
                        print("恢复成功，继续爬取")
                        consecutive_empty = 0
                        recovery_attempts = 0
                        continue
                    else:
                        recovery_attempts += 1
                        if recovery_attempts >= max_recovery_attempts:
                            print(f"恢复失败超过{max_recovery_attempts}次，长停止爬取")
                            break
                        else:
                            print(f"第{recovery_attempts}次恢复失败，继续下一页...")
                            consecutive_empty = 0
                            continue
                continue

            koubei_list = self.parse_koubei_data(html)

            if not koubei_list:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    if len(all_koubei) >= self.web_koubei_count and self.web_koubei_count > 0:
                        print(f"已连续3页无数据，但爬取数({len(all_koubei)})已超过网页显示数({self.web_koubei_count})，正常结束")
                        break
                    
                    print("连续3页没有数据，执行反爬恢复策略...")
                    recovery_result = self._anti_crawl_recovery(page, incremental, all_koubei)
                    if recovery_result:
                        print("恢复成功，继续爬取")
                        consecutive_empty = 0
                        recovery_attempts = 0
                        continue
                    else:
                        recovery_attempts += 1
                        if recovery_attempts >= max_recovery_attempts:
                            print(f"恢复失败超过{max_recovery_attempts}次，长停止爬取")
                            break
                        else:
                            print(f"第{recovery_attempts}次恢复失败，继续下一页...")
                            consecutive_empty = 0
                            continue
                continue

            consecutive_empty = 0
            recovery_attempts = 0

            # 【V8.6修复】增量模式下跳过 filter_duplicates，
            # 只用 IncrementalCrawler.filter_new_koubei 做双重判断（koubei_id + 时间/车主组合），
            # 确保 consecutive_existing 计数器能正常触发提前终止。
            # filter_duplicates 会提前吸走已存在数据，导致 filter_new_koubei 收到空列表，提前终止永久失效。
            if incremental and self.incremental_crawler:
                pass  # 跳过 filter_duplicates，下面交给 IncrementalCrawler 处理
            elif not target_pages:  # 全量模式：仅用 filter_duplicates 去重
                koubei_list = self.filter_duplicates(koubei_list)

            # 增量模式：过滤已存在的数据
            if incremental and self.incremental_crawler:
                new_list, skipped, should_stop = self.incremental_crawler.filter_new_koubei(koubei_list)
                total_skipped += skipped

                if should_stop:
                    if new_list:
                        self.save_to_koubei_table(new_list)
                        all_koubei.extend(new_list)
                    print(f"第 {page} 页: 获取 {len(koubei_list)} 条，新增 {len(new_list)} 条，累计新增: {len(all_koubei)} 条")
                    print(f"\n增量爬取完成，提前终止")
                    break

                if new_list:
                    self.save_to_koubei_table(new_list)
                    all_koubei.extend(new_list)
                print(f"第 {page} 页: 获取 {len(koubei_list)} 条，新增 {len(new_list)} 条，累计新增: {len(all_koubei)} 条")
            else:
                # 【关键】逐页保存到数据库
                self.save_to_koubei_table(koubei_list)
                all_koubei.extend(koubei_list)
                print(f"第 {page} 页: 获取 {len(koubei_list)} 条，累计: {len(all_koubei)} 条（已保存）")

            # 反爬优化：完全随机化延迟，8~45秒，模拟人工浏览节奏
            delay = random.uniform(8, 45)
            time.sleep(delay)

        # 重试失败的页面
        if self.failed_pages:
            self.retry_failed_pages(incremental)

        print(f"\n总计获取到 {len(all_koubei)} 条口碑数据")
        if incremental:
            print(f"跳过已存在: {total_skipped} 条")
        if self.failed_pages:
            print(f"失败页面: {self.failed_pages}")
        return all_koubei

    def _anti_crawl_recovery(self, page, incremental=False, all_koubei=None):
        """
        反爬恢复策略
        1. 长延迟后重试
        2. 失败后重启浏览器再重试
        3. 返回是否恢复成功
        """
        if all_koubei is None:
            all_koubei = []
        
        # 阶段1：长延迟后重试
        recovery_wait = random.uniform(60, 120)
        print(f"  [恢复阶段1] 等待 {recovery_wait:.1f} 秒后重试...")
        time.sleep(recovery_wait)
        
        html = self.get_page_with_retry(page)
        if html:
            koubei_list = self.parse_koubei_data(html)
            if koubei_list:
                # 保存恢复获取的数据
                if incremental and self.incremental_crawler:
                    new_list, _, _ = self.incremental_crawler.filter_new_koubei(koubei_list)
                    if new_list:
                        self.save_to_koubei_table(new_list)
                        all_koubei.extend(new_list)
                        print(f"  恢复成功，获取 {len(new_list)} 条新数据")
                else:
                    self.save_to_koubei_table(koubei_list)
                    all_koubei.extend(koubei_list)
                    print(f"  恢复成功，获取 {len(koubei_list)} 条数据")
                return True
        
        # 阶段2：重启浏览器后重试
        print("  [恢复阶段2] 长延迟重试失败，重启浏览器...")
        if not self.restart_browser():
            print("  浏览器重启失败")
            return False
        
        recovery_wait2 = random.uniform(30, 60)
        print(f"  等待 {recovery_wait2:.1f} 秒后重试...")
        time.sleep(recovery_wait2)
        
        html = self.get_page_with_retry(page)
        if html:
            koubei_list = self.parse_koubei_data(html)
            if koubei_list:
                # 保存恢复获取的数据
                if incremental and self.incremental_crawler:
                    new_list, _, _ = self.incremental_crawler.filter_new_koubei(koubei_list)
                    if new_list:
                        self.save_to_koubei_table(new_list)
                        all_koubei.extend(new_list)
                        print(f"  恢复成功，获取 {len(new_list)} 条新数据")
                else:
                    self.save_to_koubei_table(koubei_list)
                    all_koubei.extend(koubei_list)
                    print(f"  恢复成功，获取 {len(koubei_list)} 条数据")
                return True
        
        print("  [恢复失败] 所有恢复策略均失败")
        return False

    def retry_failed_pages(self, incremental=False):
        """重试失败的页面"""
        if not self.failed_pages:
            return

        print(f"\n重试 {len(self.failed_pages)} 个失败页面...")

        still_failed = []
        for page in self.failed_pages:
            # 增加延迟后重试
            time.sleep(random.uniform(15, 30))

            html = self.get_page_with_retry(page)
            if html:
                koubei_list = self.parse_koubei_data(html)
                if koubei_list:
                    if incremental and self.incremental_crawler:
                        new_list, _, _ = self.incremental_crawler.filter_new_koubei(koubei_list)
                        if new_list:
                            self.save_to_koubei_table(new_list)
                            print(f"第{page}页重试成功: {len(new_list)}条")
                        continue
                    else:
                        self.save_to_koubei_table(koubei_list)
                        print(f"第{page}页重试成功: {len(koubei_list)}条")
                        continue

            still_failed.append(page)

        self.failed_pages = still_failed

        if still_failed:
            print(f"仍有 {len(still_failed)} 页失败: {still_failed}")

    def get_data_koubei_count_by_chexi(self, chexi_name):
        """获取data_koubei表中指定车系的数量（去重后）"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT COUNT(DISTINCT koubei_id) 
                        FROM data_koubei 
                        WHERE chexi = :chexi AND koubei_id IS NOT NULL AND koubei_id != ''
                    """),
                    {"chexi": chexi_name}
                )
                return result.fetchone()[0]
        except Exception as e:
            print(f"获取data_koubei数量失败: {str(e)}")
            return 0

    def run_single_chexi_safe(self, chexi_name, series_id, max_pages=None, incremental=False, target_pages=None):
        """安全的车系爬取流程（核心改进V8.4）"""
        print("\n" + "=" * 80)
        print(f"开始处理车系: {chexi_name}")
        if incremental:
            print("【增量更新模式】")
        if target_pages:
            print(f"【失败重爬模式】目标页面: {target_pages}")
        print("=" * 80)

        self.chexi_name = chexi_name
        self.series_id = series_id
        self.base_url = f"https://k.autohome.com.cn/{series_id}"
        self.failed_pages = []

        print(f"\n车系名称: {chexi_name}")
        print(f"车系ID: {series_id}")
        print(f"口碑页面: {self.base_url}")

        # 每个车系都重启浏览器
        print("\n【系统准备】重启浏览器以清除痕迹...")
        if not self.restart_browser():
            print("浏览器重启失败，跳过该车系")
            return False

        # 获取网页口碑数量
        print("\n【步骤1】获取网页口碑数量...")
        self.web_koubei_count = self.get_web_koubei_count()

        # 【V8.4改进】加载data_koubei中已有的口碑ID，用于去重
        print("\n【步骤1-1】加载data_koubei已有口碑ID...")
        self.load_existing_koubei_ids(chexi_name)

        # 【V8.5改进】增量模式快速判断：网页显示数=已爬取数时跳过
        if incremental:
            existing_count = len(self.existing_koubei_ids)
            print(f"\n【增量快速判断】网页显示: {self.web_koubei_count} 条, 已爬取: {existing_count} 条")
            if self.web_koubei_count > 0 and existing_count >= self.web_koubei_count:
                print(f"✓ 已爬取数据({existing_count}) >= 网页显示数({self.web_koubei_count})，无需更新，跳过该车系")
                # 记录跳过信息
                self.record_manager.add_record(
                    chexi_name=chexi_name,
                    web_count=self.web_koubei_count,
                    crawl_count=0,
                    new_count=0,
                    failed_pages=[],
                    completion_rate=100.0,
                    data_quality="已是最新，跳过爬取"
                )
                return True

        # 增量模式：加载已有数据（ID + 时间+车主组合）
        if incremental:
            print("\n【步骤1-2】加载已有口碑数据...")
            self.incremental_crawler = IncrementalCrawler(self.engine, chexi_name)
            self.incremental_crawler.load_existing_data()
            
            # 【优化】快速判断：如果网页最新时间 <= 数据库最新时间，跳过爬取
            if self.web_koubei_count > 0 and hasattr(self, 'web_newest_time') and self.web_newest_time:
                if not self.incremental_crawler.check_if_needs_crawl(self.web_newest_time):
                    print("✓ 数据已是最新，跳过爬取")
                    self.record_manager.add_record(
                        chexi_name=chexi_name,
                        web_count=self.web_koubei_count,
                        crawl_count=0,
                        new_count=0,
                        failed_pages=[],
                        completion_rate=100.0,
                        data_quality="已是最新，跳过爬取"
                    )
                    return True

        # 自动计算页数
        if max_pages is None and not target_pages:
            print("\n【自动计算】根据口碑数量计算爬取页数...")
            max_pages = self.calculate_auto_pages(self.web_koubei_count)
        elif target_pages:
            max_pages = max(target_pages)
            print(f"\n使用重爬目标页数: {max_pages} 页")
        else:
            print(f"\n使用手动设置的页数: {max_pages} 页")

        # 【关键】清空koubei表（仅当前车系使用）
        self.create_koubei_table()

        # 【关键】逐页爬取并保存
        print(f"\n【步骤2】逐页爬取并保存...")
        crawled_data = self.crawl_all_koubei_with_save(max_pages, incremental, target_pages)

        # 【关键】无论是否完整，立即将koubei数据转移到data_koubei
        print("\n【步骤3】将车系数据转移到data_koubei...")
        
        # 计算转移前的数量
        count_before = self.get_data_koubei_count_by_chexi(chexi_name)
        self.append_to_data_koubei()
        count_after = self.get_data_koubei_count_by_chexi(chexi_name)
        new_added = count_after - count_before

        # 验证完整性
        actual_count = self.get_koubei_count_from_db()
        
        # 爬取完成后的总结报告
        print("\n" + "=" * 80)
        print(f"【爬取总结报告 - {chexi_name}】")
        print("=" * 80)
        print(f"  车系名称: {chexi_name}")
        print(f"  网页显示口碑数: {self.web_koubei_count} 条")
        print(f"  本次爬取口碑数: {len(crawled_data)} 条")
        print(f"  本次新增口碑数: {new_added} 条")
        print(f"  data_koubei累计: {count_after} 条")
        
        # 计算完整率
        if self.web_koubei_count > 0:
            completion_rate = (count_after / self.web_koubei_count) * 100
            print(f"  数据完整率: {completion_rate:.1f}%")
        else:
            completion_rate = 0
            print(f"  数据完整率: 无法计算（未获取到网页口碑数）")
        
        if self.failed_pages:
            print(f"  失败页面: {self.failed_pages}")
        
        # 数据质量评估
        data_quality = "未知"
        if self.web_koubei_count > 0:
            if completion_rate >= 95:
                data_quality = "优秀"
            elif completion_rate >= 80:
                data_quality = "良好"
            elif completion_rate >= 60:
                data_quality = "一般"
            else:
                data_quality = "较差，建议重新爬取"
            print(f"  数据质量: {data_quality}")
        print("=" * 80)

        # 【V8.4改进】保存爬取记录到MD文档
        self.record_manager.add_record(
            chexi_name=chexi_name,
            web_count=self.web_koubei_count,
            crawl_count=len(crawled_data),
            new_count=new_added,
            failed_pages=self.failed_pages.copy(),
            completion_rate=completion_rate,
            data_quality=data_quality
        )

        # 更新车系配置
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.chexi_manager.update_chexi_status(
            chexi_name,
            total_koubei=self.web_koubei_count,
            last_crawl=now,
            last_count=count_after
        )

        return len(self.failed_pages) == 0

    def retry_failed_pages_from_record(self, chexi_name):
        """从记录中读取失败页面，重新爬取"""
        failed_pages = self.record_manager.get_failed_pages(chexi_name)
        
        if not failed_pages:
            print(f"\n车系 '{chexi_name}' 没有失败的页面记录")
            return False
        
        print(f"\n车系 '{chexi_name}' 有 {len(failed_pages)} 个失败页面: {failed_pages}")
        confirm = input("确认重新爬取这些页面吗？(y/n): ").strip().lower()
        if confirm != 'y':
            print("已取消")
            return False
        
        # 查找车系ID
        all_chexi = self.chexi_manager.get_all_chexi()
        series_id = None
        for chexi in all_chexi:
            if chexi['name'] == chexi_name:
                series_id = chexi['series_id']
                break
        
        if not series_id:
            print(f"未找到车系 '{chexi_name}' 的ID")
            return False
        
        # 执行重爬
        print(f"\n开始重新爬取失败页面...")
        success = self.run_single_chexi_safe(
            chexi_name=chexi_name,
            series_id=series_id,
            target_pages=failed_pages,
            incremental=False
        )
        
        # 更新记录：标记已成功爬取的页面
        if success or not self.failed_pages:
            # 所有页面都成功
            self.record_manager.update_failed_pages(chexi_name, failed_pages, [])
            print(f"\n所有失败页面已重新爬取成功！")
        else:
            # 部分页面仍失败
            success_pages = [p for p in failed_pages if p not in self.failed_pages]
            still_failed = self.failed_pages
            self.record_manager.update_failed_pages(chexi_name, success_pages, still_failed)
            print(f"\n重新爬取结果:")
            print(f"  成功: {len(success_pages)} 页 - {success_pages}")
            print(f"  仍失败: {len(still_failed)} 页 - {still_failed}")
        
        return success

    def export_to_excel(self):
        """从数据库导出数据到Excel - V8.5新增"""
        try:
            print("\n" + "=" * 60)
            print("【导出数据到Excel】")
            print("=" * 60)

            # 查询数据
            print("\n正在从数据库查询数据...")
            query = """
                SELECT 
                    chexi AS 车型,
                    chekuan AS 车款,
                    niankuan AS 年款,
                    fabiao_time AS 发表时间,
                    xingshi AS 行驶里程,
                    jiage AS 购车价格,
                    goumai_time AS 购车时间,
                    goumai_didian AS 购车地点,
                    chezhu_weizhi AS 车主城市,
                    pingfen AS 评分,
                    zhaiyao AS 口碑摘要
                FROM data_koubei
                ORDER BY chexi, fabiao_time DESC
            """

            df = pd.read_sql(query, con=self.engine)

            if df.empty:
                print("数据库中没有数据，无法导出")
                return False

            print(f"查询到 {len(df)} 条数据")

            # 弹出文件保存对话框
            try:
                import tkinter as tk
                from tkinter import filedialog

                print("正在弹出保存对话框...")

                # 创建隐藏的tkinter窗口
                root = tk.Tk()
                root.withdraw()
                # 确保窗口在前台显示
                root.attributes('-topmost', True)

                # 设置默认文件名
                default_filename = f"口碑数据_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

                # 弹出保存对话框
                file_path = filedialog.asksaveasfilename(
                    defaultextension=".xlsx",
                    filetypes=[("Excel文件", "*.xlsx"), ("所有文件", "*.*")],
                    initialfile=default_filename,
                    title="选择保存位置"
                )

                # 销毁tkinter窗口
                root.destroy()

                if not file_path:
                    print("已取消保存")
                    return False

            except Exception as e:
                print(f"弹出对话框失败: {e}")
                print("使用默认保存位置")
                file_path = f"口碑数据_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

            # 保存到Excel
            print(f"\n正在保存到: {file_path}")
            df.to_excel(file_path, index=False, engine='openpyxl')

            print(f"✓ 数据导出成功！")
            print(f"  保存位置: {file_path}")
            print(f"  数据条数: {len(df)} 条")
            print(f"  包含字段: {', '.join(df.columns.tolist())}")
            return True

        except Exception as e:
            print(f"导出数据失败: {str(e)}")
            return False

    def show_menu(self):
        """显示主菜单"""
        print("\n" + "=" * 60)
        print("汽车之家口碑数据爬虫（V8.5 - 导出功能版）")
        print("=" * 60)
        print("1. 查看车系列表")
        print("2. 添加新车系")
        print("3. 删除车系")
        print("4. 全量爬取单个车系")
        print("5. 增量更新单个车系")
        print("6. 全量爬取全部车系（批量）")
        print("7. 增量更新全部车系（批量）")
        print("8. 重新爬取失败页面")
        print("9. 查看爬取记录")
        print("10. 导出数据到Excel")  # 【V8.5新增】
        print("11. 退出")
        print("=" * 60)

    def run_interactive(self):
        """交互模式运行 - V8.5改进：启动时不打开浏览器，需要时再启动"""
        print("=" * 80)
        print("汽车之家口碑数据爬虫（V8.5 - 导出功能版）")
        print("=" * 80)

        try:
            print("\n【初始化】数据库连接...")
            if not self.init_database():
                return

            # 【V8.5改进】启动时不打开浏览器，需要时再启动
            print("\n【系统提示】浏览器将在爬取时自动启动")

            while True:
                self.show_menu()
                choice = input("\n请选择操作: ").strip()

                if choice == "1":
                    self.chexi_manager.display_list()

                elif choice == "2":
                    name = input("车系名称: ").strip()
                    url = input("网页地址: ").strip()
                    if name and url:
                        self.chexi_manager.add_chexi(name, url)
                    else:
                        print("名称和地址不能为空")

                elif choice == "3":
                    self.chexi_manager.display_list()
                    try:
                        index = int(input("要删除的序号: ")) - 1
                        self.chexi_manager.remove_chexi(index)
                    except ValueError:
                        print("请输入有效的序号")

                elif choice == "4":
                    # 【V8.5改进】需要时启动浏览器
                    if not self.driver:
                        print("\n【初始化】启动浏览器...")
                        if not self.init_browser():
                            continue
                    self.chexi_manager.display_list()
                    try:
                        index = int(input("选择要爬取的车系序号: ")) - 1
                        chexi = self.chexi_manager.get_chexi_by_index(index)
                        if chexi:
                            pages_input = input("最大爬取页数（直接回车自动计算）: ").strip()
                            if pages_input.isdigit():
                                max_pages = int(pages_input)
                                print(f"使用手动设置的页数: {max_pages} 页")
                            else:
                                max_pages = None
                                print("将自动根据口碑数量计算页数")
                            self.run_single_chexi_safe(chexi["name"], chexi["series_id"], max_pages, incremental=False)
                        else:
                            print("无效序号")
                    except ValueError:
                        print("请输入有效的序号")

                elif choice == "5":
                    # 【V8.5改进】需要时启动浏览器
                    if not self.driver:
                        print("\n【初始化】启动浏览器...")
                        if not self.init_browser():
                            continue
                    self.chexi_manager.display_list()
                    try:
                        index = int(input("选择要更新的车系序号: ")) - 1
                        chexi = self.chexi_manager.get_chexi_by_index(index)
                        if chexi:
                            pages_input = input("最大爬取页数（直接回车自动计算）: ").strip()
                            if pages_input.isdigit():
                                max_pages = int(pages_input)
                                print(f"使用手动设置的页数: {max_pages} 页")
                            else:
                                max_pages = None
                                print("将自动根据口碑数量计算页数")
                            self.run_single_chexi_safe(chexi["name"], chexi["series_id"], max_pages, incremental=True)
                        else:
                            print("无效序号")
                    except ValueError:
                        print("请输入有效的序号")

                elif choice == "6":
                    # 【V8.5改进】需要时启动浏览器
                    if not self.driver:
                        print("\n【初始化】启动浏览器...")
                        if not self.init_browser():
                            continue
                    self.batch_crawl_all_chexi(incremental=False)

                elif choice == "7":
                    # 【V8.5改进】需要时启动浏览器
                    if not self.driver:
                        print("\n【初始化】启动浏览器...")
                        if not self.init_browser():
                            continue
                    self.batch_crawl_all_chexi(incremental=True)

                elif choice == "8":
                    # 【V8.5改进】需要时启动浏览器
                    if not self.driver:
                        print("\n【初始化】启动浏览器...")
                        if not self.init_browser():
                            continue
                    # 【V8.4新增】重新爬取失败页面
                    self.chexi_manager.display_list()
                    try:
                        index = int(input("选择要重爬的车系序号: ")) - 1
                        chexi = self.chexi_manager.get_chexi_by_index(index)
                        if chexi:
                            self.retry_failed_pages_from_record(chexi["name"])
                        else:
                            print("无效序号")
                    except ValueError:
                        print("请输入有效的序号")

                elif choice == "9":
                    # 【V8.4新增】查看爬取记录
                    self.record_manager.display_records()

                elif choice == "10":
                    # 【V8.5新增】导出数据到Excel
                    self.export_to_excel()

                elif choice == "11":
                    break

                else:
                    print("无效选择，请重新输入")

        except Exception as e:
            print(f"\n程序执行出错: {str(e)}")
        finally:
            self.close()
            print("\n程序结束")

    def batch_crawl_all_chexi(self, incremental=False):
        """批量爬取全部车系（安全版本）"""
        all_chexi = self.chexi_manager.get_all_chexi()
        if not all_chexi:
            print("车系列表为空，请先添加车系")
            return

        mode_str = "增量更新" if incremental else "全量爬取"
        print(f"\n即将批量{mode_str} {len(all_chexi)} 个车系")
        confirm = input("确认开始吗？(y/n): ").strip().lower()
        if confirm != 'y':
            print("已取消")
            return

        success_count = 0
        partial_count = 0

        for i, chexi in enumerate(all_chexi, 1):
            print(f"\n{'='*60}")
            print(f"【批量{mode_str}】第 {i}/{len(all_chexi)} 个车系: {chexi['name']}")
            print(f"{'='*60}")

            is_complete = self.run_single_chexi_safe(
                chexi["name"], 
                chexi["series_id"], 
                incremental=incremental
            )

            if is_complete:
                success_count += 1
            else:
                partial_count += 1

            if i < len(all_chexi):
                # 反爬优化：车系间延迟（根据成功与否调整）
                base_wait = 30 if is_complete else 60
                wait_time = random.uniform(base_wait, base_wait + 30)
                print(f"\n等待 {wait_time:.1f} 秒后处理下一个车系...")
                time.sleep(wait_time)

            # 每5个车系重启浏览器
            if i % 5 == 0 and i < len(all_chexi):
                self.restart_browser()

        print(f"\n{'='*60}")
        print(f"批量{mode_str}完成!")
        print(f"完全成功: {success_count} 个")
        print(f"部分成功: {partial_count} 个")
        print(f"{'='*60}")

    def close(self):
        if self.driver:
            self.driver.quit()
        if self.engine:
            self.engine.dispose()
        if self.local_engine:
            self.local_engine.dispose()

    def run(self, chexi_list=None, max_pages=None, incremental=False):
        """运行爬虫"""
        if not chexi_list:
            self.run_interactive()
            return

        print("=" * 80)
        print("汽车之家口碑数据爬虫（V8.4 - 记录与去重版）")
        print("=" * 80)

        try:
            print("\n【初始化】数据库连接...")
            if not self.init_database():
                return

            print("\n【初始化】启动浏览器...")
            if not self.init_browser():
                return

            success_count = 0
            partial_count = 0

            for i, (chexi_name, series_id) in enumerate(chexi_list, 1):
                print(f"\n\n处理第 {i}/{len(chexi_list)} 个车系...")
                is_complete = self.run_single_chexi_safe(chexi_name, series_id, max_pages, incremental)
                if is_complete:
                    success_count += 1
                else:
                    partial_count += 1

                if i < len(chexi_list):
                    base_wait = 30 if is_complete else 60
                    wait_time = random.uniform(base_wait, base_wait + 30)
                    print(f"\n等待 {wait_time:.1f} 秒后处理下一个车系...")
                    time.sleep(wait_time)

                if i % 5 == 0 and i < len(chexi_list):
                    self.restart_browser()

            print("\n\n" + "=" * 80)
            print("全部任务完成！")
            print("=" * 80)
            print(f"完全成功: {success_count} 个")
            print(f"部分成功: {partial_count} 个")

        except Exception as e:
            print(f"\n程序执行出错: {str(e)}")
        finally:
            self.close()
            print("\n程序结束")


def main():
    parser = argparse.ArgumentParser(description='汽车之家口碑爬虫V8.4（记录与去重版）')
    parser.add_argument('--chexi', '-c', help='车系名称')
    parser.add_argument('--id', '-i', help='车系ID')
    parser.add_argument('--pages', '-p', type=int, default=None, help='最大页数（不指定则自动计算）')
    parser.add_argument('--incremental', '-inc', action='store_true', help='增量更新模式')
    parser.add_argument('--retry', '-r', action='store_true', help='重新爬取失败页面模式')

    args = parser.parse_args()

    spider = FullKoubeiSpider()

    if args.retry and args.chexi:
        spider.init_database()
        spider.init_browser()
        spider.retry_failed_pages_from_record(args.chexi)
        spider.close()
    elif args.chexi and args.id:
        spider.run(chexi_list=[(args.chexi, args.id)], max_pages=args.pages, incremental=args.incremental)
    else:
        spider.run_interactive()


if __name__ == "__main__":
    main()
