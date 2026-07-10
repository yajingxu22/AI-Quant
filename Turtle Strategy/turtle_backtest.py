#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
海龟策略回测 (Turtle Trading Strategy Backtest)
================================================
- 后复权重建: 用 Tushare 日线自带的 pct_chg(复权涨跌幅) 累乘重建连续后复权价,
  消除除权除息造成的假跳空 (如比亚迪 2025-07-29 close 337->111.42 但 pct_chg 仅 +0.37%)
- 信号: Donchian 通道突破 (System1: 20日买/10日卖; System2: 55日买/20日卖)
- 头寸: ATR(N, Wilder 平滑) 定单位 Unit = 净值×risk_per_unit / N
- 加仓: 金字塔, 每涨 add_step×N 加 1 单位, 单系统最多 max_units
- 止损: 每单位 stop_mult×N;  离场: 反向跌破通道下轨
- 双系统并行合并; 事件驱动, 杜绝前视 (t-1 信号, t 日开盘成交)
"""
import os
import glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

RAW_DIR = "/Users/xuyajing/Desktop/AI/Quant/data/raw"
OUT_DIR = "/Users/xuyajing/Desktop/AI/Quant/Turtle Strategy"
FIG_DIR = os.path.join(OUT_DIR, "figs")
os.makedirs(FIG_DIR, exist_ok=True)

STOCKS = {
    "002594.SZ": "比亚迪",
    "600031.SH": "三一重工",
    "600900.SH": "长江电力",
    "688981.SH": "中芯国际",
}

DEFAULTS = dict(
    s1_entry=20, s1_exit=10,
    s2_entry=55, s2_exit=20,
    atr_period=20,
    risk_per_unit=0.01,
    add_step=0.5,
    max_units=4,
    stop_mult=2.0,
    commission=0.0003,
    initial_capital=1.0,
    annualization=252,
    rf_annual=0.0,
    combine_mode="both",   # both / sys1_only / sys2_only
    use_hfq=True,
    fill_mode="open",       # open(次日开盘) / close
)

# ---------------------------------------------------------------- 后复权
def rebuild_hfq(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("trade_date").reset_index(drop=True)
    raw_close = df["close"].astype(float).values
    hfq = [raw_close[0]]
    for k in range(1, len(df)):
        hfq.append(hfq[-1] * (1.0 + df["pct_chg"].iloc[k] / 100.0))
    hfq = np.array(hfq)
    ratio = hfq / raw_close
    out = df.copy()
    out["close"] = hfq
    for c in ["open", "high", "low", "pre_close"]:
        out[c] = out[c].values * ratio
    return out

def load_stock(code: str, use_hfq: bool) -> pd.DataFrame:
    path = glob.glob(os.path.join(RAW_DIR, f"{code}_*.csv"))[0]
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d")
    df = df.sort_values("trade_date").reset_index(drop=True)
    if use_hfq:
        df = rebuild_hfq(df)
    for c in ["open", "high", "low", "close", "pre_close"]:
        df[c] = df[c].astype(float)
    return df

# ---------------------------------------------------------------- 指标
def wilder_atr(high, low, close, period):
    high = np.asarray(high, float); low = np.asarray(low, float); close = np.asarray(close, float)
    prev = np.roll(close, 1); prev[0] = close[0]
    tr = np.maximum.reduce([high - low, np.abs(high - prev), np.abs(low - prev)])
    atr = np.full(len(tr), np.nan)
    if len(tr) >= period:
        atr[period - 1] = tr[:period].mean()
    for i in range(period, len(tr)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr

def donchian(high, low, entry_p, exit_p):
    """返回 shifted(1) 的上下轨: 第 t 日通道用 t-1 及之前窗口, 信号无前视"""
    upper = high.rolling(entry_p).max().shift(1)
    lower = low.rolling(exit_p).min().shift(1)
    return upper.values, lower.values

# ---------------------------------------------------------------- 回测
def backtest(df: pd.DataFrame, p: dict):
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    open_ = df["open"].values
    dates = df["trade_date"].values
    n = len(close)

    # ATR + 通道
    N = wilder_atr(high, low, close, p["atr_period"])
    N_prev = np.roll(N, 1); N_prev[0] = np.nan  # 第 t 日使用 N[t-1]

    sys_cfg = [("s1", p["s1_entry"], p["s1_exit"]), ("s2", p["s2_entry"], p["s2_exit"])]
    if p["combine_mode"] == "sys1_only":
        sys_cfg = [sys_cfg[0]]
    elif p["combine_mode"] == "sys2_only":
        sys_cfg = [sys_cfg[1]]

    ch = {}
    sig_up, sig_dn = {}, {}
    for name, ep, xp in sys_cfg:
        u, lo = donchian(df["high"], df["low"], ep, xp)
        ch[name] = (u, lo)
        sig_up[name] = close > u
        sig_dn[name] = close < lo

    start = max(p["atr_period"], p["s1_entry"], p["s2_entry"],
                p["s2_entry"] if p["combine_mode"] != "sys1_only" else p["s1_entry"])

    cash = p["initial_capital"]
    systems = {name: {"units": [], "last_add": None} for name, _, _ in sys_cfg}
    equity = np.full(n, np.nan)
    units_count = np.zeros(n)
    buy_dates, buy_prices, sell_dates, sell_prices = [], [], [], []

    # 回合统计 (每系统)
    R = {name: dict(open=False, pnl=0.0, sidx=None, count=0, wins=0,
                    pf_win=0.0, pf_loss=0.0, hold_sum=0, hold_cnt=0)
         for name, _, _ in sys_cfg}

    commission = p["commission"]
    rpu = p["risk_per_unit"]
    eq_prev = p["initial_capital"]

    def size(eq, Nv):
        return (eq * rpu) / Nv

    for t in range(n):
        if t >= start:
            for name, ep, xp in sys_cfg:
                sys = systems[name]
                Nt = N_prev[t]
                if Nt is None or np.isnan(Nt) or Nt <= 0:
                    continue
                up = sig_up[name][t - 1] if t - 1 >= 0 else False
                dn = sig_dn[name][t - 1] if t - 1 >= 0 else False
                level = (sys["last_add"] + p["add_step"] * Nt) if sys["last_add"] is not None else None
                add = (len(sys["units"]) > 0 and level is not None and (close[t - 1] >= level)
                       and len(sys["units"]) < p["max_units"]) if t - 1 >= 0 else False

                # 1) 止损 (盘中触及即按止损价成交)
                keep = []
                for (sh, ep_, sp_) in sys["units"]:
                    if low[t] <= sp_:
                        px = sp_
                        cash += px * sh
                        cash -= commission * px * sh
                        R[name]["pnl"] += (px - ep_) * sh
                        sell_dates.append(dates[t]); sell_prices.append(px)
                    else:
                        keep.append((sh, ep_, sp_))
                sys["units"] = keep

                # 2) 通道离场 (次日开盘清仓)
                if len(sys["units"]) > 0 and dn:
                    px = open_[t] if p["fill_mode"] == "open" else close[t]
                    for (sh, ep_, sp_) in sys["units"]:
                        cash += px * sh
                        cash -= commission * px * sh
                        R[name]["pnl"] += (px - ep_) * sh
                        sell_dates.append(dates[t]); sell_prices.append(px)
                    sys["units"] = []
                    sys["last_add"] = None
                    r = R[name]
                    if r["open"]:
                        r["open"] = False
                        r["count"] += 1
                        if r["pnl"] > 0:
                            r["wins"] += 1
                            r["pf_win"] += r["pnl"]
                        else:
                            r["pf_loss"] += (-r["pnl"])
                        r["hold_sum"] += (t - r["sidx"])
                        r["hold_cnt"] += 1
                        r["pnl"] = 0.0
                        r["sidx"] = None

                # 3) 初始入场 (空仓 + 突破)
                if len(sys["units"]) == 0 and up:
                    px = open_[t] if p["fill_mode"] == "open" else close[t]
                    sh = size(eq_prev, Nt)
                    cash -= px * sh + commission * px * sh
                    sp = px - p["stop_mult"] * Nt
                    sys["units"].append((sh, px, sp))
                    sys["last_add"] = px
                    buy_dates.append(dates[t]); buy_prices.append(px)
                    r = R[name]
                    if not r["open"]:
                        r["open"] = True
                        r["pnl"] = 0.0
                        r["sidx"] = t

                # 4) 金字塔加仓
                elif add:
                    px = max(open_[t], level) if p["fill_mode"] == "open" else level
                    sh = size(eq_prev, Nt)
                    cash -= px * sh + commission * px * sh
                    sp = px - p["stop_mult"] * Nt
                    sys["units"].append((sh, px, sp))
                    sys["last_add"] = px
                    buy_dates.append(dates[t]); buy_prices.append(px)

            # 当日权益 (收盘市值)
            pos_val = sum(sh for name, _, _ in sys_cfg for (sh, _, _) in systems[name]["units"]) * close[t]
            equity[t] = cash + pos_val
            units_count[t] = sum(len(systems[name]["units"]) for name, _, _ in sys_cfg)
            eq_prev = equity[t]
        else:
            equity[t] = p["initial_capital"]

    # 回测期末若仍有未平仓回合, 按末日收盘了结计入统计
    for name, _, _ in sys_cfg:
        r = R[name]
        if r["open"]:
            r["open"] = False
            r["count"] += 1
            if r["pnl"] > 0:
                r["wins"] += 1
                r["pf_win"] += r["pnl"]
            else:
                r["pf_loss"] += (-r["pnl"])
            r["hold_sum"] += (n - 1 - r["sidx"])
            r["hold_cnt"] += 1

    # ---------------- 指标 ----------------
    eq_valid = equity[start:]
    eq_valid = eq_valid[~np.isnan(eq_valid)]
    daily_ret = eq_valid[1:] / eq_valid[:-1] - 1.0
    A = p["annualization"]
    rf_d = p["rf_annual"] / A
    CR = eq_valid[-1] / p["initial_capital"] - 1.0
    T = len(eq_valid) - 1
    AR = (1 + CR) ** (A / T) - 1 if T > 0 else 0.0
    # MDD
    peak = np.maximum.accumulate(eq_valid)
    dd = (peak - eq_valid) / peak
    MDD = dd.max() if len(dd) else 0.0
    # Sharpe
    if daily_ret.std(ddof=1) > 0:
        sharpe = (daily_ret.mean() - rf_d) / daily_ret.std(ddof=1) * np.sqrt(A)
    else:
        sharpe = 0.0
    # Buy & Hold
    bh = p["initial_capital"] * (1 - commission) * close[start:] / close[start]
    bh_ret = bh[1:] / bh[:-1] - 1.0
    bh_CR = bh[-1] / p["initial_capital"] - 1.0
    bh_sharpe = (bh_ret.mean() - rf_d) / bh_ret.std(ddof=1) * np.sqrt(A) if bh_ret.std(ddof=1) > 0 else 0.0

    # 交易统计 (合并系统)
    total_rounds = sum(R[name]["count"] for name, _, _ in sys_cfg)
    wins = sum(R[name]["wins"] for name, _, _ in sys_cfg)
    pf_win = sum(R[name]["pf_win"] for name, _, _ in sys_cfg)
    pf_loss = sum(R[name]["pf_loss"] for name, _, _ in sys_cfg)
    hold_sum = sum(R[name]["hold_sum"] for name, _, _ in sys_cfg)
    hold_cnt = sum(R[name]["hold_cnt"] for name, _, _ in sys_cfg)
    win_rate = wins / total_rounds if total_rounds else 0.0
    profit_factor = pf_win / pf_loss if pf_loss > 0 else float("inf")
    avg_hold = hold_sum / hold_cnt if hold_cnt else 0.0
    max_units = int(units_count[start:].max())
    time_in_market = float(np.mean(units_count[start:] > 0))

    metrics = dict(CR=CR, AR=AR, MDD=MDD, Sharpe=sharpe,
                   bh_CR=bh_CR, bh_Sharpe=bh_sharpe,
                   total_rounds=total_rounds, win_rate=win_rate,
                   profit_factor=profit_factor, avg_hold=avg_hold,
                   max_units=max_units, time_in_market=time_in_market)

    return dict(equity=equity, bh=bh, close=close, dates=dates,
                ch=ch, N=N, metrics=metrics,
                buy_dates=np.array(buy_dates), buy_prices=np.array(buy_prices),
                sell_dates=np.array(sell_dates), sell_prices=np.array(sell_prices),
                units_count=units_count, start=start, sys_cfg=sys_cfg)

# ---------------------------------------------------------------- 绘图
def plot_stock(code, name, df, res, p):
    dates = res["dates"]
    close = res["close"]
    equity = res["equity"]
    bh = res["bh"]
    start = res["start"]
    N = res["N"]

    fig = plt.figure(figsize=(15, 10))
    gs = GridSpec(3, 1, height_ratios=[3, 1, 1.4], hspace=0.28)

    # --- 主图: 价格 + 通道 + 信号 ---
    ax0 = fig.add_subplot(gs[0])
    ax0.plot(dates, close, color="#555555", lw=1.0, label="Close (hfq)")
    colors = {"s1": "#1f77b4", "s2": "#ff7f0e"}
    for name_, ep, xp in res["sys_cfg"]:
        u, lo = res["ch"][name_]
        c = colors[name_]
        ax0.plot(dates, u, color=c, lw=1.1, ls="--", label=f"{name_.upper()} Upper ({ep})")
        ax0.plot(dates, lo, color=c, lw=1.1, ls=":", label=f"{name_.upper()} Lower ({xp})")
    if len(res["buy_dates"]):
        ax0.scatter(res["buy_dates"], res["buy_prices"], marker="^", color="#2ca02c",
                    s=60, zorder=5, label="Buy (entry/add)")
    if len(res["sell_dates"]):
        ax0.scatter(res["sell_dates"], res["sell_prices"], marker="v", color="#d62728",
                    s=55, zorder=5, label="Sell (stop/exit)")
    ax0.set_title(f"{code} | Turtle Strategy  S1({p['s1_entry']}/{p['s1_exit']})  "
                  f"S2({p['s2_entry']}/{p['s2_exit']})  ATR{p['atr_period']}  "
                  f"risk{int(p['risk_per_unit']*100)}%  add{p['add_step']}N  "
                  f"stop{p['stop_mult']}N  maxU{p['max_units']}", fontsize=12)
    ax0.legend(loc="upper left", fontsize=8, ncol=2)
    ax0.grid(alpha=0.25)

    # --- ATR 副图 ---
    ax1 = fig.add_subplot(gs[1], sharex=ax0)
    ax1.plot(dates, N, color="#9467bd", lw=1.0)
    ax1.set_title("ATR (N, Wilder)", fontsize=10)
    ax1.grid(alpha=0.25)

    # --- 净值副图 ---
    ax2 = fig.add_subplot(gs[2], sharex=ax0)
    ax2.plot(dates[start:], equity[start:], color="#2ca02c", lw=1.2, label="Turtle Strategy")
    ax2.plot(dates[start:], bh, color="#555555", lw=1.0, ls="--", label="Buy & Hold")
    ax2.set_title("Equity Curve", fontsize=10)
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(alpha=0.25)

    fig.autofmt_xdate()
    out = os.path.join(FIG_DIR, f"{code}_turtle.png")
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return out

def rpu_pct(p):
    return f"{int(p['risk_per_unit']*100)}%"

# ---------------------------------------------------------------- 主流程
def main():
    p = dict(DEFAULTS)
    rows = []
    for code, name in STOCKS.items():
        df = load_stock(code, p["use_hfq"])
        res = backtest(df, p)
        m = res["metrics"]
        fig = plot_stock(code, name, df, res, p)
        rows.append(dict(
            code=code, name=name,
            CR=m["CR"], AR=m["AR"], MDD=m["MDD"], Sharpe=m["Sharpe"],
            bh_CR=m["bh_CR"], bh_Sharpe=m["bh_Sharpe"],
            rounds=m["total_rounds"], win_rate=m["win_rate"],
            profit_factor=m["profit_factor"], avg_hold=m["avg_hold"],
            max_units=m["max_units"], time_in_market=m["time_in_market"],
        ))
        print(f"{code} {name}: CR={m['CR']*100:7.2f}%  AR={m['AR']*100:6.2f}%  "
              f"MDD={m['MDD']*100:5.2f}%  Sharpe={m['Sharpe']:.2f}  "
              f"回合={m['total_rounds']} 胜率={m['win_rate']*100:5.1f}%  "
              f"盈亏比={m['profit_factor']:.2f} 最大单位={m['max_units']} 持仓占比={m['time_in_market']*100:.1f}%  -> {fig}")

    mdf = pd.DataFrame(rows)
    csv_path = os.path.join(OUT_DIR, "metrics_summary.csv")
    mdf.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n指标汇总已保存: {csv_path}")
    print(mdf.to_string(index=False))

if __name__ == "__main__":
    main()
