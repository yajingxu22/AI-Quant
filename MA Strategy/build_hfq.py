#!/usr/bin/env python3
"""
用 Tushare adj_factor（复权因子）重建真正的后复权(hfq)日线数据，
原地替换 Task 1&2/data/raw 与 Task 3/data/raw 下 4 只股票的文件。

为什么不用 daily(adj='hfq')：
  实测该账户 pro.daily(adj='hfq') 只调整了 pct_chg，OHLC 仍返回未复权原始价
  （token 疑似缺 hfq 权限，adj 被静默忽略），导致除权跳空仍在。
  改用更底层的 adj_factor 接口手动计算，所有 token 基本都有该权限。

公式（后复权，锚定区间首交易日）：
  hfq_price = raw_price * adj_factor[t] / adj_factor[首日]
  hfq_pct_chg = (hfq_close / hfq_close_prev - 1) * 100
"""
import os, json, time, glob
import pandas as pd
import tushare as ts

HOME = os.path.expanduser("~")
MCP_PATH = os.path.join(HOME, ".workbuddy", ".mcp.json")
SRC_DIR = "/Users/xuyajing/Desktop/AI/Quant/Task 1&2/data/raw"
DST_DIR = "/Users/xuyajing/Desktop/AI/Quant/Task 3/data/raw"
START, END = "20250703", "20260703"   # 与原文件日期范围一致

STOCKS = [
    "600031.SH",  # 三一重工
    "600900.SH",  # 长江电力
    "688981.SH",  # 中芯国际
    "002594.SZ",  # 比亚迪
]

def get_token():
    cfg = json.load(open(MCP_PATH))
    url = cfg.get("mcpServers", {}).get("tushareMcp", {}).get("url", "")
    if "token=" in url:
        return url.split("token=")[-1]
    raise RuntimeError("未找到 TUSHARE_TOKEN")

def main():
    token = get_token()
    ts.set_token(token)
    pro = ts.pro_api()
    os.makedirs(DST_DIR, exist_ok=True)

    for i, code in enumerate(STOCKS):
        print(f"\n=== [{i+1}/{len(STOCKS)}] {code} ===")
        raw_path = os.path.join(SRC_DIR, f"{code}_{START}_{END}.csv")
        if not os.path.exists(raw_path):
            print(f"  ⚠️ 原始文件不存在: {raw_path}，跳过")
            continue
        try:
            # 1) 原始未复权日线
            raw = pd.read_csv(raw_path, encoding="utf-8-sig").sort_values("trade_date").reset_index(drop=True)
            # 2) 复权因子
            af = pro.adj_factor(ts_code=code, start_date=START, end_date=END)
            if af is None or af.empty:
                print(f"  ❌ adj_factor 为空，跳过 {code}")
                continue
            af = af.sort_values("trade_date").reset_index(drop=True)
            # 3) 合并
            df = raw.merge(af[["trade_date", "adj_factor"]], on="trade_date", how="left")
            if df["adj_factor"].isna().any():
                print(f"  ❌ 存在缺失复权因子的交易日，跳过 {code}")
                continue
            f0 = df["adj_factor"].iloc[0]   # 锚定首日因子
            ratio = df["adj_factor"] / f0
            # 4) 计算后复权 OHLC
            for col in ["open", "high", "low", "close"]:
                df[col] = (df[col] * ratio).round(4)
            df["pre_close"] = (df["pre_close"] * ratio).round(4)
            df["close_prev"] = df["close"].shift(1)
            df["pct_chg"] = ((df["close"] / df["close_prev"] - 1) * 100).round(4)
            df["pct_chg"] = df["pct_chg"].fillna(0.0)
            df["change"] = (df["close"] - df["close_prev"]).round(4)
            df["change"] = df["change"].fillna(0.0)
            df["adj"] = "hfq"
            out_cols = ["ts_code","trade_date","open","high","low","close","pre_close","change","pct_chg","vol","amount","adj"]
            out = df[out_cols].copy()
            # 5) 写回（原地替换）原文件
            out.to_csv(raw_path, index=False, encoding="utf-8-sig")
            # 6) 同步到 Task 3/data/raw
            out.to_csv(os.path.join(DST_DIR, f"{code}_{START}_{END}.csv"), index=False, encoding="utf-8-sig")
            # 7) 清理之前误标的 20250701 文件
            for stray in glob.glob(os.path.join(SRC_DIR, f"{code}_20250701_*.csv")) + glob.glob(os.path.join(DST_DIR, f"{code}_20250701_*.csv")):
                os.remove(stray)
                print(f"  🗑  删除误标文件: {os.path.basename(stray)}")
            # 8) 校验：计算最大单日跳空，应不再含除权断点
            gap = (df["close"] / df["close"].shift(1) - 1) * 100
            maxgap = gap.min()
            print(f"  ✅ 已写回 {code}_{START}_{END}.csv ({len(out)} 行) | 区间 hfq 涨跌 {(df['close'].iloc[-1]/df['close'].iloc[0]-1)*100:+.2f}%")
            print(f"     最大单日跌幅(校验,应无<-5%除权断点): {maxgap:.3f}%")
        except Exception as e:
            print(f"  ❌ 处理 {code} 失败: {e}")
        if i < len(STOCKS) - 1:
            print("  … 等待 60s 以符合 Tushare 限流")
            time.sleep(60)
    print("\n🎉 后复权重建完成。")

if __name__ == "__main__":
    main()
