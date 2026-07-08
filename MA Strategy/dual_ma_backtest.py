# -*- coding: utf-8 -*-
"""
双均线（Dual Moving Average）策略回测引擎 — Task 3
=====================================================

严格依据 `dual_ma_backtest_spec.md` 实现：

- 数据：Task 3/data/raw/ 下 4 只 A 股**后复权**日线（close 已消除除权除息跳空）。
- 信号：交叉事件驱动（cross_t - cross_{t-1} = +2 金叉 / -2 死叉），初始空仓，
        避免首根均线刚算出就"凭空满仓"。
- 前视偏差：第 t 日持仓与切换由"截至 t-1 日"的交叉事件决定，t 日才执行。
- 成本：单边万三（0.0003），仅在持仓由 0→1（买）或 1→0（卖）切换当日扣除。
- 指标：累计回报、年化收益、最大回撤 MDD、夏普（年化 ×√252）、索提诺、卡玛。

本文件既可直接运行（python dual_ma_backtest.py）产出 figs/*.png 与 metrics_summary.csv，
也可被 notebook / 其他脚本 import 复用其中函数。
"""

from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")  # 无界面后端，便于脚本/服务器运行
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.ticker import FuncFormatter

# 注册系统中文字体（macOS PingFang），避免 matplotlib 中文乱码方框
_CJK_FONT = "/System/Library/Fonts/PingFang.ttc"
if os.path.exists(_CJK_FONT):
    try:
        fm.fontManager.addfont(_CJK_FONT)
        _cjk_name = fm.FontProperties(fname=_CJK_FONT).get_name()
        plt.rcParams["font.family"] = _cjk_name
    except Exception:
        pass
plt.rcParams["axes.unicode_minus"] = False  # 正常显示负号

# ----------------------------------------------------------------------------
# 默认参数（与 spec §9 对齐，均可配置）
# ----------------------------------------------------------------------------
DEFAULTS = dict(
    N_short=5,
    N_long=20,
    rf_annual=0.0,          # 年化无风险利率，可改 0.02
    annualization=252,      # 年交易日数（A 股/美股）
    initial_capital=1.0,
    commission=0.0003,      # 单边交易成本（万三）
    start_date=None,        # 回测起始日（'YYYY-MM-DD'），None = 全区间
    end_date=None,          # 回测结束日（'YYYY-MM-DD'），None = 全区间
)

# 股票中文名映射（用于图标题）
NAME_MAP = {
    "600031.SH": "三一重工",
    "600900.SH": "长江电力",
    "688981.SH": "中芯国际",
    "002594.SZ": "比亚迪",
}

# ----------------------------------------------------------------------------
# 1) 数据读取与预处理
# ----------------------------------------------------------------------------
def load_stock(path: str, start_date=None, end_date=None) -> pd.DataFrame:
    """读取单只股票 CSV（utf-8-sig 去 BOM），按日期升序，返回带 DatetimeIndex 的 DataFrame。

    可选按日期区间过滤（start_date / end_date，格式 'YYYY-MM-DD' 或 None 表示不限制）。
    """
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d")
    df = df.sort_values("trade_date").reset_index(drop=True)
    df = df.set_index("trade_date")
    # 按回测区间过滤
    if start_date is not None:
        df = df.loc[pd.Timestamp(start_date):]
    if end_date is not None:
        df = df.loc[:pd.Timestamp(end_date)]
    if df.empty:
        raise ValueError(f"过滤后数据为空：{path} 区间 [{start_date}, {end_date}]")
    # 保护：缺失值前向填充
    df["close"] = df["close"].ffill()
    return df


# ----------------------------------------------------------------------------
# 2) 双均线与交叉事件信号
# ----------------------------------------------------------------------------
def compute_signals(df: pd.DataFrame, n_short: int, n_long: int) -> pd.DataFrame:
    """
    计算长短均线 + 方向变量 cross + 金叉/死叉事件 + 持仓 pos + 切换 switch。

    交叉事件驱动（spec §4）：
        cross_t = +1 (MA_short > MA_long) / -1 (MA_short < MA_long) / 0 (相等) / NaN (均线未就绪)
        金叉 golden：cross_{t-1} - cross_{t-2} == +2  → 在 t 日买入（pos 置 1）
        死叉 death ：cross_{t-1} - cross_{t-2} == -2  → 在 t 日卖出（pos 置 0）
    前 N_long-1 日均线无值，期间 pos = 0（空仓）。
    """
    df = df.copy()
    ma_s = df["close"].rolling(n_short, min_periods=n_short).mean()
    ma_l = df["close"].rolling(n_long, min_periods=n_long).mean()
    df["ma_short"] = ma_s
    df["ma_long"] = ma_l

    # 方向变量 cross（均线就绪后才取值，否则 NaN）
    cross = pd.Series(index=df.index, dtype="float64")
    valid = ma_s.notna() & ma_l.notna()
    cross[valid & (ma_s > ma_l)] = 1.0
    cross[valid & (ma_s < ma_l)] = -1.0
    cross[valid & (ma_s == ma_l)] = 0.0
    df["cross"] = cross

    # 交叉事件：用 t-1、t-2 的 cross 判定，在 t 日执行（无前视偏差）
    diff = cross.shift(1) - cross.shift(2)   # 即 cross_{t-1} - cross_{t-2}
    golden = (diff == 2).fillna(False)       # 由 -1 翻 +1
    death = (diff == -2).fillna(False)       # 由 +1 翻 -1
    df["golden"] = golden.values
    df["death"] = death.values

    # 持仓递推（初始 0；只在真实交叉事件翻转）
    n = len(df)
    pos = np.zeros(n, dtype=float)
    cur = 0.0
    g_arr = df["golden"].to_numpy()
    d_arr = df["death"].to_numpy()
    for i in range(n):
        if g_arr[i]:
            cur = 1.0
        elif d_arr[i]:
            cur = 0.0
        pos[i] = cur
    df["pos"] = pos

    # 切换标记：持仓由 0→1 或 1→0 当日 = 1（计费日）
    df["switch"] = (df["pos"].diff().fillna(0.0) != 0.0).astype(int)
    return df


# ----------------------------------------------------------------------------
# 3) 回测引擎
# ----------------------------------------------------------------------------
def backtest(df: pd.DataFrame, commission: float) -> pd.DataFrame:
    """
    计算策略日收益（含成本）、策略净值、买入持有净值。
        r_t        = close_t / close_{t-1} - 1
        strat_r_t  = pos_t * r_t - commission * switch_t
        equity_t   = equity_{t-1} * (1 + strat_r_t)
        bh_t       = (1 - commission) · ∏(1 + r_t)     # 买入持有：建仓时扣除单边万三成本
    说明：买入持有在 t=0 一次性建仓，扣除买入佣金 (1-commission)；
          与策略一致，区间内不另计退出佣金（两者期末均处于持有状态）。
    """
    df = df.copy()
    df["r"] = df["close"].pct_change().fillna(0.0)
    df["strat_r"] = df["pos"] * df["r"] - commission * df["switch"]
    df["equity"] = (1.0 + df["strat_r"]).cumprod()
    df["bh"] = (1.0 - commission) * (1.0 + df["r"]).cumprod()
    return df


# ----------------------------------------------------------------------------
# 4) 评价指标
# ----------------------------------------------------------------------------
def compute_metrics(df: pd.DataFrame, rf_annual: float, annualization: int) -> dict:
    """返回累计回报、年化收益、MDD、夏普、索提诺、卡玛，以及买入持有对照。"""
    equity = df["equity"].to_numpy()
    strat_r = df["strat_r"].to_numpy()
    r = df["r"].to_numpy()

    n = len(strat_r)
    num_ret = max(n - 1, 1)

    # 累计回报
    cr = equity[-1] / equity[0] - 1.0
    # 年化收益（几何）
    ar = (1.0 + cr) ** (annualization / num_ret) - 1.0 if (1.0 + cr) > 0 else float("nan")

    # 最大回撤
    running_max = np.maximum.accumulate(equity)
    drawdown = equity / running_max - 1.0
    mdd = float(np.min(drawdown))          # 负值
    mdd_abs = abs(mdd)

    # 夏普（年化）
    rf_daily = rf_annual / annualization
    mean_r = np.mean(strat_r)
    std_r = np.std(strat_r, ddof=1)
    sharpe = ((mean_r - rf_daily) / std_r) * np.sqrt(annualization) if std_r > 0 else 0.0

    # 索提诺（下行波动）
    downside = strat_r[strat_r < 0]
    if len(downside) > 1:
        downside_dev_ann = np.std(downside, ddof=1) * np.sqrt(annualization)
    else:
        downside_dev_ann = 0.0
    sortino = ((mean_r * annualization - rf_annual) / downside_dev_ann) if downside_dev_ann > 0 else 0.0

    # 卡玛
    calmar = (ar / mdd_abs) if mdd_abs > 0 else 0.0

    # 买入持有对照
    bh_equity = df["bh"].to_numpy()
    bh_cr = bh_equity[-1] / bh_equity[0] - 1.0
    bh_running_max = np.maximum.accumulate(bh_equity)
    bh_mdd = abs(float(np.min(bh_equity / bh_running_max - 1.0)))

    return dict(
        cumulative_return=cr,
        annualized_return=ar,
        mdd=mdd_abs,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        bh_cumulative_return=bh_cr,
        bh_mdd=bh_mdd,
        num_trades=int(df["switch"].sum()),
    )


# ----------------------------------------------------------------------------
# 5) 单只股票全流程
# ----------------------------------------------------------------------------
def run_one(path: str, params: dict) -> tuple[pd.DataFrame, dict, str]:
    """对单只股票跑完信号→回测→指标，返回 (df, metrics, code)。"""
    df = load_stock(path, params.get("start_date"), params.get("end_date"))
    df = compute_signals(df, params["N_short"], params["N_long"])
    df = backtest(df, params["commission"])
    metrics = compute_metrics(df, params["rf_annual"], params["annualization"])
    code = os.path.basename(path).split("_")[0]
    metrics["code"] = code
    metrics["name"] = NAME_MAP.get(code, code)
    metrics["N_short"] = params["N_short"]
    metrics["N_long"] = params["N_long"]
    metrics["commission"] = params["commission"]
    metrics["start"] = str(df.index[0].date())
    metrics["end"] = str(df.index[-1].date())
    return df, metrics, code


# ----------------------------------------------------------------------------
# 6) 可视化（matplotlib，浅色主题，中国配色：涨红跌绿）
# ----------------------------------------------------------------------------
def plot_one(df: pd.DataFrame, metrics: dict, code: str, out_png: str) -> None:
    name = metrics.get("name", code)
    ns, nl = metrics["N_short"], metrics["N_long"]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                                   gridspec_kw={"height_ratios": [2.2, 1]})

    # ---- 子图 1：价格 + 均线 + 买卖信号 ----
    ax1.plot(df.index, df["close"], color="#555555", lw=1.0, label="收盘价(后复权)", zorder=1)
    ax1.plot(df.index, df["ma_short"], color="#1f77b4", lw=1.2, label=f"MA{ns}(快线)")
    ax1.plot(df.index, df["ma_long"], color="#ff7f0e", lw=1.2, label=f"MA{nl}(慢线)")

    buy = df[df["golden"]]
    sell = df[df["death"]]
    # 买入 ▲ 绿；卖出 ▼ 红（中国习惯：红涨绿跌，但信号点按 spec 用绿买/红卖区分方向）
    ax1.scatter(buy.index, buy["close"], marker="^", color="#2ca02c", s=90,
                zorder=5, label="金叉·买入", edgecolors="black", linewidths=0.4)
    ax1.scatter(sell.index, sell["close"], marker="v", color="#d62728", s=90,
                zorder=5, label="死叉·卖出", edgecolors="black", linewidths=0.4)

    s, e = metrics.get("start"), metrics.get("end")
    rng = f"  [{s} ~ {e}]" if s and e else ""
    ax1.set_title(f"{code} {name}  双均线策略 MA{ns}/{nl}（后复权）{rng}", fontsize=12, fontweight="bold")
    ax1.set_ylabel("价格")
    ax1.legend(loc="best", fontsize=8, framealpha=0.9)
    ax1.grid(True, alpha=0.25)

    # ---- 子图 2：净值对比 ----
    ax2.plot(df.index, df["equity"], color="#2ca02c", lw=1.4, label="策略净值")
    ax2.plot(df.index, df["bh"], color="#555555", lw=1.2, ls="--", label="买入持有")
    ax2.set_ylabel("净值")
    ax2.set_xlabel("日期")
    ax2.legend(loc="best", fontsize=8, framealpha=0.9)
    ax2.grid(True, alpha=0.25)

    # ---- 指标文本面板（右上角，axes fraction）----
    pct = lambda x: f"{x*100:.2f}%"
    txt = (f"累计回报 : {pct(metrics['cumulative_return'])}\n"
           f"年化收益 : {pct(metrics['annualized_return'])}\n"
           f"最大回撤 : {pct(metrics['mdd'])}\n"
           f"夏普比率 : {metrics['sharpe']:.2f}\n"
           f"索提诺   : {metrics['sortino']:.2f}\n"
           f"卡玛比率 : {metrics['calmar']:.2f}\n"
           f"交易次数 : {metrics['num_trades']}\n"
           f"—— 对照 买入持有 ——\n"
           f"累计回报 : {pct(metrics['bh_cumulative_return'])}\n"
           f"最大回撤 : {pct(metrics['bh_mdd'])}")
    ax1.text(0.015, 0.97, txt, transform=ax1.transAxes, va="top", ha="left",
             fontsize=8.5,
             bbox=dict(boxstyle="round,pad=0.5", fc="white", ec="#cccccc", alpha=0.92))

    fig.tight_layout()
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


# ----------------------------------------------------------------------------
# 7) 批量运行入口
# ----------------------------------------------------------------------------
def run_all(data_dir: str, params: dict | None = None, figs_dir: str | None = None,
            summary_path: str | None = None) -> pd.DataFrame:
    params = {**DEFAULTS, **(params or {})}
    data_dir = data_dir or os.path.join(os.path.dirname(__file__), "data", "raw")
    figs_dir = figs_dir or os.path.join(os.path.dirname(__file__), "figs")
    summary_path = summary_path or os.path.join(os.path.dirname(__file__), "metrics_summary.csv")

    files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    rows = []
    for fp in files:
        df, metrics, code = run_one(fp, params)
        out_png = os.path.join(figs_dir, f"{code}_dual_ma.png")
        plot_one(df, metrics, code, out_png)
        rows.append(metrics)
        print(f"[OK] {code} {metrics['name']:<6} | 累计 {metrics['cumulative_return']*100:7.2f}% "
              f"| MDD {metrics['mdd']*100:6.2f}% | 夏普 {metrics['sharpe']:5.2f} "
              f"| 交易 {metrics['num_trades']:3d} | 图 → {out_png}")

    summary = pd.DataFrame(rows)
    col_order = ["code", "name", "start", "end", "N_short", "N_long", "commission",
                 "cumulative_return", "annualized_return", "mdd", "sharpe",
                 "sortino", "calmar", "num_trades",
                 "bh_cumulative_return", "bh_mdd"]
    summary = summary[col_order]
    os.makedirs(os.path.dirname(summary_path), exist_ok=True)
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"\n[汇总] 已写出 → {summary_path}")
    return summary


if __name__ == "__main__":
    import argparse

    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="双均线策略回测（Task 3）")
    parser.add_argument("--data-dir", default=os.path.join(here, "data", "raw"),
                        help="原始数据目录")
    parser.add_argument("--start", default=None, help="回测起始日 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="回测结束日 YYYY-MM-DD")
    parser.add_argument("--nshort", type=int, default=DEFAULTS["N_short"])
    parser.add_argument("--nlong", type=int, default=DEFAULTS["N_long"])
    parser.add_argument("--commission", type=float, default=DEFAULTS["commission"])
    args = parser.parse_args()

    params = dict(DEFAULTS)
    params.update(dict(N_short=args.nshort, N_long=args.nlong,
                       commission=args.commission,
                       start_date=args.start, end_date=args.end))
    run_all(args.data_dir, params=params)
