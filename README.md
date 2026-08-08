# Scrapers - 爬虫代码共享仓库

A/B 电脑共用的爬虫代码仓库。A 电脑（ZCode）负责数据分析，B 电脑（TRAE）负责爬虫开发与维护。

## 目录结构

```
scrapers/
├── anti_crawl/          # 反爬基础模块
│   ├── ua_pool.py       # User-Agent 池
│   ├── delay.py         # 随机延迟
│   ├── retry.py         # 重试策略
│   └── proxy.py         # 代理池
├── autohome/            # 汽车之家配置表补采
│   ├── patch_browser.py     # Playwright 浏览器渲染补采（核心）
│   ├── patch_targeted.py    # 定向字段补采
│   └── patch_remaining.py   # 剩余任务处理
├── market_data/         # 国别市场信息
│   ├── kba_crawler.py       # 德国 KBA 销量
│   ├── smmt_crawler.py      # 意大利 SMMT 销量
│   ├── unrae_crawler.py    # UNRAE 各国车型
│   └── unrae_history_crawler.py  # UNRAE 历史数据
├── gov_announcement/    # 政府公告
│   └── miit_scraper_automation.py  # 工信部公告
├── config/              # 配置模板
│   └── .env.example
└── README.md
```

## 使用规范

### 环境要求
- Python 3.10+
- 依赖见各爬虫文件头部的 import
- Playwright 补采需安装 `playwright` + `playwright install chromium`

### 数据资产
- 所有爬虫数据存入阿里云 RDS PostgreSQL
- 数据库连接配置见 `config/.env.example`
- 能力资产文档见 [traeworkmemory](https://github.com/lixfqc/traeworkmemory) 仓库

### 协作纪律
1. **任务开始**：`git pull` + 读协同日志（见 traeworkmemory/COLLABORATION_LOG.md）
2. **开发中**：代码提交 + 注释清晰
3. **任务结束**：推送代码 + 追加协同日志记录

### 待办
- [ ] anti_crawl 模块提取为独立包
- [ ] 各爬虫统一异常处理
- [ ] 日志规范化
- [ ] 配置外置化（当前硬编码在文件内）

## 更新日志

| 日期 | 改动 | 作者 |
|------|------|------|
| 2026-08-08 | 仓库初始化：从 B 电脑 D:\爬虫 提取生产代码 14 个文件 3,693 行 | B电脑/TRAE |
