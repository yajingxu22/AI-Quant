#!/usr/bin/env python3
"""
获取 4 只股票的后复权（hfq）日线数据，替换 Task 1&2/data/raw 下的现有文件。
- token 从 ~/.workbuddy/.mcp.json 的 tushareMcp url 中提取
- 使用 Tushare daily 接口 adj='hfq'
- 每次请求间隔 60s 以符合限流
- 先写临时文件，成功后才替换原文件（失败保留原文件）
"""
import os, json, time, shutil, tempfile, sys
import pandas as pd
import tushare as ts

HOME = os.path.expanduser("~")
MCP_PATH = os.path.join(HOME, ".workbuddy", ".mcp.json")
SRC_DIR = "/Users/xuyajing/Desktop/AI/Quant/Task 1&2/data/raw"
DST_DIR = "/Users/xuyajing/Desktop/AI/Quant/Task 3/data/raw"
START, END = "20250701", "20260703"

STOCKS = [
    "600031.SH",  # 三一重工
    "600900.SH",  # 长江电力
    "688981.SH",  # 中芯国际
    "002594.SZ",  # 比亚迪
]

def get_token():
    with open(MCP_PATH) as f:
        cfg = json.load(f)
    url = cfg.get("mcpServers", {}).get("tushareMcp", {}).get("url", "")
    if "token=" in url:
        return url.split("token=")[-1]
    tok = os.getenv("TUSHARE_TOKEN")
    if not tok:
        raise RuntimeError("未在 mcp.json 或环境变量中找到 TUSHARE_TOKEN")
    return tok

def main():
    token = get_token()
    ts.set_token(token)
    pro = ts.pro_api()
    os.makedirs(DST_DIR, exist_ok=True)

    for i, code in enumerate(STOCKS):
        fname = f"{code}_{START}_{END}.csv"
        target = os.path.join(SRC_DIR, fname)
        tmp = os.path.join(tempfile.gettempdir(), f"hfq_{code}.csv")
        print(f"\n=== [{i+1}/{len(STOCKS)}] {code} ===")
        try:
            df = pro.daily(ts_code=code, start_date=START, end_date=END, adj="hfq")
            if df is None or df.empty:
                print(f"  ⚠️ 返回空数据，保留原文件: {target}")
                continue
            df = df.sort_values("trade_date").reset_index(drop=True)
            df.to_csv(tmp, index=False, encoding="utf-8-sig")
            # 校验
            assert "close" in df.columns and len(df) > 0, "数据异常"
            # 替换原文件
            shutil.move(tmp, target)
            # 同步到 Task 3/data/raw
            shutil.copy(target, os.path.join(DST_DIR, fname))
            pct = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
            print(f"  ✅ 已保存 {fname} ({len(df)} 行) | 区间涨跌 {pct:+.2f}% | 首close={df['close'].iloc[0]:.2f} 末close={df['close'].iloc[-1]:.2f}")
        except Exception as e:
            print(f"  ❌ 获取 {code} 失败: {e}（保留原文件）")
            if os.path.exists(tmp):
                os.remove(tmp)
        # 限流：请求之间间隔 60s（最后一只不睡）
        if i < len(STOCKS) - 1:
            print("  … 等待 60s 以符合 Tushare 限流")
            time.sleep(60)

    print("\n🎉 全部处理完毕。")

if __name__ == "__main__":
    main()
