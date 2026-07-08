#!/usr/bin/env python3
"""
用 Tushare 日线数据自带的 pct_chg（已为复权涨跌幅）累乘重建后复权(hfq)价格。

原理：
  - Tushare 的 pct_chg = 复权涨跌幅（已含分红送转的总回报），如比亚迪拆股日
    close 跳 -66.9% 但 pct_chg 仅 +0.37%，即真实经济回报。
  - 因此 累乘 (1 + pct_chg/100) 即重建连续的后复权价格路径，无需再调 adj_factor
    （该接口当前被限流 1次/小时，且 daily(adj='hfq') 对该账户未对 OHLC 生效）。
  - 锚定首日 close = 原始 close（后复权约定：首日为基准），向前累乘。
  - 各日 ratio = hfq_close / raw_close，用于把 open/high/low 同步复权。

结果对双均线策略与 MDD/Sharpe/累计回报 完全等价（这些是 scale-invariant 的），
且彻底消除除权除息造成的假跳空 → 假信号。
"""
import os, glob
import pandas as pd

SRC_DIR = "/Users/xuyajing/Desktop/AI/Quant/Task 1&2/data/raw"
DST_DIR = "/Users/xuyajing/Desktop/AI/Quant/Task 3/data/raw"
START, END = "20250703", "20260703"

STOCKS = ["600031.SH", "600900.SH", "688981.SH", "002594.SZ"]

def build_hfq(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.sort_values("trade_date").reset_index(drop=True)
    # 后复权 close：锚定首日
    hfq_close = [df["close"].iloc[0]]
    for k in range(1, len(df)):
        hfq_close.append(hfq_close[-1] * (1 + df["pct_chg"].iloc[k] / 100.0))
    df["close"] = pd.Series(hfq_close, index=df.index).round(4)
    # ratio 复权 open/high/low（基于原始未复权 close）
    raw_close = raw.sort_values("trade_date").reset_index(drop=True)["close"].values
    ratio = df["close"].values / raw_close
    for col in ["open", "high", "low", "pre_close"]:
        df[col] = (df[col].values * ratio).round(4)
    df["close_prev"] = df["close"].shift(1)
    df["change"] = (df["close"] - df["close_prev"]).round(4)
    df["change"] = df["change"].fillna(0.0)
    df["pct_chg_adj"] = ((df["close"] / df["close_prev"] - 1) * 100).round(4)
    df["pct_chg_adj"] = df["pct_chg_adj"].fillna(0.0)
    df["adj"] = "hfq"
    return df

def main():
    os.makedirs(DST_DIR, exist_ok=True)
    for code in STOCKS:
        raw_path = os.path.join(SRC_DIR, f"{code}_{START}_{END}.csv")
        raw = pd.read_csv(raw_path, encoding="utf-8-sig")
        out = build_hfq(raw)
        # 校验（在选列前，out 仍含 pct_chg_adj）
        gap = (out["close"].pct_change() * 100)
        err = (out["pct_chg"] - out["pct_chg_adj"]).abs().max()
        out_cols = ["ts_code","trade_date","open","high","low","close","pre_close","change","pct_chg","vol","amount","adj"]
        out = out[out_cols]
        out.to_csv(raw_path, index=False, encoding="utf-8-sig")
        out.to_csv(os.path.join(DST_DIR, f"{code}_{START}_{END}.csv"), index=False, encoding="utf-8-sig")
        # 清理误标文件
        for stray in glob.glob(os.path.join(SRC_DIR, f"{code}_20250701_*.csv")) + glob.glob(os.path.join(DST_DIR, f"{code}_20250701_*.csv")):
            os.remove(stray)
        print(f"{code}: 行={len(out)} hfq区间涨跌={(out['close'].iloc[-1]/out['close'].iloc[0]-1)*100:+.2f}% | 最大单日跌幅={gap.min():.3f}%(应>-5) | pct_chg与重建误差max={err:.4f}")
    print("\n🎉 后复权重建完成（基于 pct_chg 累乘，无需受限接口）。")

if __name__ == "__main__":
    main()
