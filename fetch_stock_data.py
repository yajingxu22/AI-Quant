#!/usr/bin/env python3
"""
Stock Data Fetcher — 股票数据获取脚本
========================================
遵循 fetch_spec.yaml 定义的标准规范，从 Tushare Pro 获取股票日线数据。

用法:
    python fetch_stock_data.py                         # 读取 spec，获取所有标的
    python fetch_stock_data.py --code 600031.SH         # 只获取指定代码
    python fetch_stock_data.py --start 20250101 --end 20251231  # 自定义日期
    python fetch_stock_data.py --init                   # 首次运行：创建目录结构
"""

import os
import sys
import yaml
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ─── 路径 ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
SPEC_PATH = PROJECT_ROOT / 'fetch_spec.yaml'
DATA_DIR = PROJECT_ROOT / 'data' / 'raw'
DEFAULT_START_OFFSET = 365  # 默认过去一年


def load_spec() -> dict:
    """加载 fetch_spec.yaml 配置文件"""
    if not SPEC_PATH.exists():
        logger.error(f'找不到配置文件: {SPEC_PATH}')
        sys.exit(1)
    with open(SPEC_PATH, 'r', encoding='utf-8') as f:
        spec = yaml.safe_load(f)
    logger.info(f'✅ 已加载规范文件，共 {len(spec["stocks"])} 个标的')
    return spec


def resolve_date(date_expr: str) -> str:
    """解析日期表达式，返回 YYYYMMDD 格式字符串"""
    if date_expr == 'today':
        return datetime.now().strftime('%Y%m%d')
    elif date_expr == '1_year_ago':
        return (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
    elif date_expr == '3_year_ago':
        return (datetime.now() - timedelta(days=1095)).strftime('%Y%m%d')
    else:
        # 假定已经是 YYYYMMDD
        return date_expr


def init_dirs(spec: dict):
    """创建输出目录结构"""
    output_dir = PROJECT_ROOT / spec['global']['output']['directory']
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f'📁 输出目录: {output_dir}/')
    return output_dir


def fetch_daily_tushare(ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    通过 Tushare MCP (HTTP) 获取日线数据。
    回退方案：如果 MCP 不可用，尝试 tushare Python 包。
    """
    # 方式 1: 通过 tushare Python 包
    try:
        import tushare as ts
        token = os.getenv('TUSHARE_TOKEN')
        if not token:
            logger.warning('环境变量 TUSHARE_TOKEN 未设置，尝试从配置获取')
            # 尝试从 MCP 配置中读取
            mcp_path = Path.home() / '.workbuddy' / '.mcp.json'
            if mcp_path.exists():
                import json
                with open(mcp_path) as f:
                    mcp_cfg = json.load(f)
                url = mcp_cfg.get('mcpServers', {}).get('tushareMcp', {}).get('url', '')
                if 'token=' in url:
                    token = url.split('token=')[-1]
        if token:
            pro = ts.pro_api(token)
            df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                df = df.sort_values('trade_date').reset_index(drop=True)
                logger.info(f'  ✅ Tushare API: {ts_code} — {len(df)} 条记录')
                return df
    except ImportError:
        logger.debug('tushare 包未安装，跳过')
    except Exception as e:
        logger.warning(f'tushare API 调用失败: {e}')

    # 方式 2: 从本地缓存读取
    csv_path = DATA_DIR / f'{ts_code}_{start_date}_{end_date}.csv'
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        logger.info(f'  📂 本地缓存: {csv_path.name}')
        return df

    logger.error(f'  ❌ 无法获取 {ts_code} 的数据')
    return pd.DataFrame()


def save_data(df: pd.DataFrame, ts_code: str, start_date: str, end_date: str,
              spec: dict, output_dir: Path):
    """按规范保存数据"""
    if df.empty:
        return

    naming = spec['global']['output']['naming']
    filename = naming.format(ts_code=ts_code, start=start_date, end=end_date)
    filepath = output_dir / f'{filename}.csv'

    df.to_csv(filepath, index=False, encoding='utf-8-sig')
    logger.info(f'  💾 已保存: {filepath.name} ({len(df)} 行)')


def process_stock(stock: dict, start_date: str, end_date: str,
                  spec: dict, output_dir: Path):
    """处理单个标的的取数流程"""
    ts_code = stock['ts_code']
    name = stock['name']

    logger.info(f'\n🔍 [{name}] ({ts_code})')

    # Step 1: 获取数据
    df = fetch_daily_tushare(ts_code, start_date, end_date)
    if df.empty:
        return

    # Step 2: 派生字段
    if 'close' in df.columns and len(df) >= 5:
        df['ma5'] = df['close'].rolling(5).mean().round(2)
    if 'close' in df.columns and len(df) >= 10:
        df['ma10'] = df['close'].rolling(10).mean().round(2)
    if 'close' in df.columns and len(df) >= 20:
        df['ma20'] = df['close'].rolling(20).mean().round(2)
    if 'vol' in df.columns and len(df) >= 5:
        df['vol_ma5'] = df['vol'].rolling(5).mean().round(0)

    # Step 3: 保存
    save_data(df, ts_code, start_date, end_date, spec, output_dir)

    # 打印摘要
    print(f'  📊 期间涨幅: {(df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100:+.2f}%'
          f'  |  最高: ¥{df["high"].max():.2f}  |  最低: ¥{df["low"].min():.2f}'
          f'  |  均价: ¥{df["close"].mean():.2f}')


def main():
    parser = argparse.ArgumentParser(description='股票数据获取工具')
    parser.add_argument('--code', help='指定股票代码，如 600031.SH')
    parser.add_argument('--start', help='开始日期 YYYYMMDD')
    parser.add_argument('--end', help='结束日期 YYYYMMDD')
    parser.add_argument('--init', action='store_true', help='初始化目录结构')
    args = parser.parse_args()

    # 加载规范
    spec = load_spec()
    output_dir = init_dirs(spec)

    # 解析日期
    global_cfg = spec['global']['default_date_range']
    start_date = resolve_date(args.start or global_cfg['start'])
    end_date = resolve_date(args.end or global_cfg['end'])

    logger.info(f'📅 日期范围: {start_date} ~ {end_date}')

    if args.init:
        logger.info('✅ 目录已初始化，可开始取数')
        return

    # 筛选标的
    stocks = spec['stocks']
    if args.code:
        stocks = [s for s in stocks if s['ts_code'] == args.code]
        if not stocks:
            logger.error(f'⚠️ 规范中未找到代码 {args.code}')
            sys.exit(1)

    # 逐个获取
    for stock in stocks:
        process_stock(stock, start_date, end_date, spec, output_dir)

    logger.info('\n🎉 全部完成！')


if __name__ == '__main__':
    main()
