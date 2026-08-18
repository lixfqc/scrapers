# -*- coding: utf-8 -*-
"""
运行NL爬虫 - 处理更多页面
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nl_crawler import BovagCrawler

# 创建爬虫实例
crawler = BovagCrawler()

# 运行爬虫，处理尽可能多的页面
# 限制在80个页面（避免过长时间运行）
print('=== 开始运行NL爬虫 ===')
crawler.crawl_all(max_pages=80, model_only=True)

# 检查入库数据
print('\n=== 检查入库数据 ===')
conn, cur = crawler.get_connection()

cur.execute("""
    SELECT 
        source_month,
        COUNT(*) as total_records,
        COUNT(DISTINCT brand_name_raw) as brand_count,
        COUNT(DISTINCT CASE WHEN model_name IS NOT NULL THEN brand_name_raw || ' ' || model_name END) as model_count
    FROM market_sales_monthly
    WHERE country_code = 'NL'
    GROUP BY source_month
    ORDER BY source_month DESC
""")

rows = cur.fetchall()
print(f'\nNL市场数据统计:')
print(f'  已有 {len(rows)} 个月份的数据')
total = 0
for row in rows:
    print(f'  {row["source_month"]}: {row["total_records"]} 条 (品牌: {row["brand_count"]}, 车型: {row["model_count"]})')
    total += row['total_records']
print(f'\n  总计: {total} 条记录')

crawler.close()
