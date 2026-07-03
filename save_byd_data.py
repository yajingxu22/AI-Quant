#!/usr/bin/env python3
"""
BYD HK Stock Data Saver — 保存比亚迪港股数据到本地 CSV
用法: python save_byd_data.py
"""
import json, os, sys
from pathlib import Path

# 方案 1: 从 Tushare MCP 配置文件读取 token，通过 tushare SDK 拉取
try:
    mcp_path = Path.home() / '.workbuddy' / '.mcp.json'
    with open(mcp_path) as f:
        cfg = json.load(f)
    url = cfg['mcpServers']['tushareMcp']['url']
    token = url.split('token=')[-1]

    import tushare as ts
    pro = ts.pro_api(token)
    df = pro.hk_daily(ts_code='01211.HK', start_date='20250703', end_date='20260703')
    if df is not None and not df.empty:
        df = df.sort_values('trade_date').reset_index(drop=True)
        out = 'data/raw/01211.HK_20250703_20260703.csv'
        os.makedirs(os.path.dirname(out), exist_ok=True)
        df.to_csv(out, index=False, encoding='utf-8-sig')
        print(f'✅ 已保存: {out} ({len(df)} 条)')
    else:
        print('⚠️ 无数据返回')
except Exception as e:
    print(f'❌ 方案 1 失败: {e}')
    print('')
    print('请通过 WorkBuddy 使用 Tushare MCP 手动拉取:')
    print('  mcp__tushareMcp__hk_daily(ts_code="01211.HK", start_date="20250703", end_date="20260703")')
    print('然后将返回的数据保存为 data/raw/01211.HK_20250703_20260703.csv')
