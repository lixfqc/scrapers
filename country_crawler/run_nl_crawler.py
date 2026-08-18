# -*- coding: utf-8 -*-
"""
运行NL爬虫 - 获取荷兰汽车销量历史数据
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nl_crawler import BovagCrawler

def main():
    crawler = BovagCrawler()
    
    try:
        # 运行爬虫，最多处理100个页面
        # model_only=True: 只保存车型级数据（更详细）
        success = crawler.crawl_all(max_pages=100, model_only=True)
        
        if success:
            print('\n' + '='*60)
            print('✅ NL爬虫运行完成！')
            
            # 验证数据
            conn, cur = crawler.get_connection()
            cur.execute("""
                SELECT source_month, COUNT(*) as cnt
                FROM market_sales_monthly
                WHERE country_code = 'NL'
                GROUP BY source_month
                ORDER BY source_month DESC
            """)
            
            rows = cur.fetchall()
            print(f'\nNL市场数据统计:')
            print(f'  月份数: {len(rows)}')
            total_records = sum(row['cnt'] for row in rows)
            print(f'  总记录数: {total_records}')
            
            if rows:
                print(f'\n各月份数据量:')
                for row in rows[:10]:  # 显示最近10个月
                    print(f'    {row["source_month"]}: {row["cnt"]} 条')
        else:
            print('\n❌ NL爬虫运行失败')
            
    except Exception as e:
        print(f'\n❌ 爬虫异常: {e}')
        import traceback
        traceback.print_exc()
    finally:
        crawler.close()

if __name__ == '__main__':
    main()
