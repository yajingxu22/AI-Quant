#!/usr/bin/env python3
"""
BYD A-Share Stock Data Saver — 保存比亚迪A股数据到本地 CSV
用法: python save_byd_data.py
"""
import json, os, sys
from pathlib import Path

# 从 Tushare MCP 配置文件读取 token
try:
    mcp_path = Path.home() / '.workbuddy' / '.mcp.json'
    with open(mcp_path) as f:
        cfg = json.load(f)
    url = cfg['mcpServers']['tushareMcp']['url']
    token = url.split('token=')[-1]

    import tushare as ts
    pro = ts.pro_api(token)
    df = pro.daily(ts_code='002594.SZ', start_date='20250703', end_date='20260703')
    if df is not None and not df.empty:
        df = df.sort_values('trade_date').reset_index(drop=True)
        out = 'data/raw/002594.SZ_20250703_20260703.csv'
        os.makedirs(os.path.dirname(out), exist_ok=True)
        df.to_csv(out, index=False, encoding='utf-8-sig')
        print(f'✅ 已保存: {out} ({len(df)} 条)')
    else:
        print('⚠️ 无数据返回')
except Exception as e:
    print(f'❌ 拉取失败: {e}')
    print('')
    print('请通过 WorkBuddy 使用 Tushare MCP 手动拉取:')
    print('  mcp__tushareMcp__daily(ts_code="002594.SZ", start_date="20250703", end_date="20260703")')
    print('然后将返回的数据保存为 data/raw/002594.SZ_20250703_20260703.csv')
