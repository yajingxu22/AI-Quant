# 海龟策略回测 Spec（Turtle Strategy Backtest）

## 1. 目标

利用已存储的 A 股日线数据，实现经典 **海龟交易策略（Turtle Trading）** 的历史回测：
在可视化中同时呈现 **股价、高低价通道（Donchian）、交易信号（买入/卖出标记）**；
并产出一个 **可调整参数的 HTML 看板**，用户可在浏览器端实时修改策略参数、查看信号与绩效。

策略核心：趋势跟踪 + Donchian 通道突破入场 + 基于 ATR 波动率的头寸规模（Unit）+ 金字塔加仓 + 硬性止损。

## 2. 输入数据

- 原始位置：`data/raw/`（与 `indicators_spec.yaml` / 双均线回测同源）
- 文件清单（4 只，区间约 2025-07-02 ~ 2026-07-02，约 242 个交易日）：
  - `002594.SZ_20250703_20260703.csv`（比亚迪）
  - `600031.SH_20250703_20260703.csv`（三一重工）
  - `600900.SH_20250703_20260703.csv`（长江电力）
  - `688981.SH_20250703_20260703.csv`（中芯国际）
- 实际字段（实测 CSV 无 `adj` 列）：
  `ts_code, trade_date(YYYYMMDD), open, high, low, close, pre_close, change, pct_chg, vol, amount`
- 回测使用列：`trade_date`（索引）、`open / high / low / close`（OHLC，用于通道突破与止损）
- 复权说明：当前 CSV 的 `close/high/low` 为 Tushare 原始日线价（含除权跳空）。
  双均线任务已用 `pct_chg` 累乘重建后复权路径（见 `MA Strategy/build_hfq_v2.py`）。
  **本策略两种模式均可选**（见 §9 `use_hfq`）：
  - `false`（默认）：直接使用存储的 `high/low/close`，简单直观；
  - `true`：复用后复权重建逻辑，消除除权日假突破，更贴合真实收益。

## 3. 数据预处理

- 读取 CSV → DataFrame，**务必 `encoding='utf-8-sig'`** 消除首列 BOM；
- `trade_date` 解析为 datetime，按日期升序排序；
- 回测区间过滤（可调）：`start_date` / `end_date`（`'YYYY-MM-DD'`，`None` = 全区间）对日期索引切片；
  区间过窄导致通道/ATR 无法初始化时抛出提示；
- 缺失值：丢弃或前向填充（数据应已连续，仅做保护）；
- 4 只股票分别处理，函数化循环。

## 4. 策略定义（海龟）

### 4.1 Donchian 通道（高低价通道）

对第 t 日，用 **前一日及之前** 的窗口（避免前视）计算：

- 上轨（突破买入线）：`upper_N[t] = max(high[t-N : t-1])`
- 下轨（跌破卖出线）：`lower_N[t] = min(low[t-N : t-1])`

两套系统并行：

| 系统 | 入场周期（上轨） | 离场周期（下轨） | 默认 |
|------|----------------|----------------|------|
| **System 1（短）** | 20 日 | 10 日 | entry=20, exit=10 |
| **System 2（长）** | 55 日 | 20 日 | entry=55, exit=20 |

### 4.2 ATR（N，波动率）

- 真实波幅 `TR = max(high-low, |high-pre_close|, |low-pre_close|)`
- `N`（ATR）采用 **Wilder 平滑**（海龟原版）：
  - 首值 `N = mean(TR[0:20])`
  - 之后 `N[t] = (N[t-1]*(20-1) + TR[t]) / 20`
- 用途：① 定头寸单位 ② 定止损距离 ③ 定加仓间距

### 4.3 头寸规模（Unit）

```
Unit = (账户当前净值 × risk_per_unit) / N
```
- `risk_per_unit` 默认 **1%**：每 1 个单位在价格反向变动 1×N 时亏损账户的 1%；
- 同一标的 **最多 `max_units = 4` 个单位**；
- 账户对单一标的的单一方向暴露上限即 4 单位。

### 4.4 入场与金字塔加仓

- **首次入场**：当收盘价 `close[t] > upper_entry[t]`（对应系统上轨），以 1 单位开仓，
  入场价 ≈ `close[t]`（次日以开盘/信号价成交，见 §5 前视处理）；
- **加仓**：价格相对**该系统的上一次加仓价**每上涨 `add_step × N`（默认 `0.5N`）再加 1 单位，
  直到达到 `max_units`；加仓价递增，形成金字塔（越涨买得越少）；
- **System 1 与 System 2 各自独立维护仓位与加仓阶梯**，互不抵消。

### 4.5 止损（硬性）

- 每个单位记录自身止损价：`stop_i = entry_i - stop_mult × N`（默认 `stop_mult = 2`）；
- 回测中若当日 `low[t] <= stop_i` → 该单位以止损价 `stop_i` 离场（若止损价劣于收盘价，保守按收盘价成交，见 §5）；
- 全部单位止损清空后，该系统的该方向仓位归零，需等待下一次突破重新入场。

### 4.6 离场（反向突破）

- 当收盘价 `close[t] < lower_exit[t]`（对应系统离场下轨）→ 平掉该系统全部剩余单位；
- 离场优先级：先检查止损（盘中触及），再检查通道离场（收盘跌破）。

### 4.7 System 1 / System 2 组合

- 两系统**同时运行、独立核算**，默认等权合并净值（各自单位数相加计入总持仓/净值）；
- 可选 `combine_mode`：`both`（默认） / `sys1_only` / `sys2_only`；
- 单系统最大 4 单位，两系统并行时单标的理论最大 8 单位（可由 `max_units` 总上限约束，见 §9）。

## 5. 回测引擎

- **避免前视偏差**：第 t 日的突破/止损判定基于截至 **t-1** 日的通道与 `N`；信号在 t-1 生成，t 日
  以 `open[t]`（或 `close[t]`，由 `fill_mode` 配置，默认 `open`）成交。
- **状态机**（每只股票、每系统维护）：
  - 持仓单位栈 `units[]`，每元素含 `{entry_price, stop_price}`；
  - 上次加仓参考价 `last_add_price`；
  - 当日流程：① 先判止损（遍历单位，`low <= stop` 则剔除）② 再判通道离场（清栈）③ 最后判突破入场/加仓；
- 单位市值：`value = Σ units * close[t]`；账户净值 = 现金 + 持仓市值；
- **交易成本**：默认单边 `commission = 0.0003`（万三），每次开/平仓（增/减单位）各扣一次；
  加仓/减仓按对应金额计费；
- **策略净值曲线**：`equity[t] = equity[t-1] × (1 + strat_ret[t])`，`equity_0 = initial_capital`；
- **对照基准**：买入持有（Buy & Hold）净值 `bh[t] = initial_capital × close[t]/close[0]`
  （建仓日同样计单边 `commission`）；
- 通道/ATR 初始化期（前 `max(entry_period, atr_period)` 日）按空仓处理。

## 6. 评价指标

设策略日收益序列为 `s_t`，年化因子 `A = 252`，无风险年化 `rf`（默认 0）：

- **累计回报 Cumulative Return**：`CR = equity_last / equity_0 - 1`
- **年化收益 Annualized Return**：`AR = (1 + CR)^(A / T) - 1`
- **最大回撤 MDD**：`MDD = min_t (peak_t - equity_t)/peak_t`（报告取绝对值，正数幅度）
- **夏普比率 Sharpe（年化）**：`(mean(s_t) - rf/A) / std(s_t) × sqrt(A)`
- （海龟专属补充）
  - **交易次数 Trade Count**：单位开仓事件总数（或回合次数，可配置）
  - **胜率 Win Rate**：盈利回合 / 总回合
  - **盈亏比 Profit Factor**：总盈利 / 总亏损（绝对值）
  - **平均持仓天数 Avg Hold Days**
  - **最大持仓单位 Max Units Reached**
  - **持仓时间占比 Time in Market**：有持仓的交易日占比

## 7. 可视化

### 7.1 静态图（matplotlib，PNG）

每只股票输出主图（重点股 `600031.SH` 详示，其余批量）：

- **主图 — 价格 + 高低价通道 + 信号**
  - 收盘价折线（灰）
  - System 1 上/下轨（蓝，实线/虚线）
  - System 2 上/下轨（橙）
  - **买入信号 ▲**：突破入场/加仓日，标记在对应价格点（按本项目双均线约定：**绿色 ▲**）
  - **卖出信号 ▼**：止损/通道离场日，标记在对应价格点（**红色 ▼**）
  - 止损线（可选）：各单位止损价水平线
  - 图例、标题（股票代码 + 系统参数）
- **副图 1 — ATR(N) 波动率**
- **副图 2 — 净值对比**：策略净值（绿）vs 买入持有（灰虚线）
- **副图 3（可选）— 持仓单位数**：units over time
- 保存：`Turtle Strategy/figs/<code>_turtle.png`
- （可选）plotly 额外生成交互式 HTML

### 7.2 可调整参数 HTML 看板（核心交付）

> 风格对齐 `MA Strategy/dual_ma_dashboard.html`：纯前端、Plotly CDN、轻主题、参数改动实时重算重绘。

- **控制面板（可调参数，全部实时生效）**
  | 控件 | 含义 | 默认 |
  |------|------|------|
  | 股票 `stock` | 下拉切换 4 只 | 600031.SH |
  | 回测区间 `start/end` | 日期范围 | 全区间 |
  | Sys1 入场/离场 `s1_entry/s1_exit` | 20 / 10 |
  | Sys2 入场/离场 `s2_entry/s2_exit` | 55 / 20 |
  | ATR 周期 `atr_period` | 20 |
  | 单位风险 `risk_per_unit` | 1% |
  | 加仓间距 `add_step` | 0.5（×N） |
  | 最大单位 `max_units` | 4 |
  | 止损倍数 `stop_mult` | 2（×N） |
  | 交易成本 `commission` | 0.0003 |
  | 初始资金 `initial_capital` | 1.0（或 100000） |
  | 组合模式 `combine_mode` | both / sys1 / sys2 |
  | 复权 `use_hfq` | false / true |
  | 显示开关 | Sys1 通道 / Sys2 通道 / 买入标记 / 卖出标记 / 止损线 |
  | 重置按钮 | 一键恢复默认 |
- **图表区（Plotly 多子图 / grid）**
  1. 主图：收盘价 + Sys1/Sys2 上下轨 + 买入▲/卖出▼ 标记 + 止损线（可选）
  2. 副图：ATR(N) 波动率
  3. 副图：策略净值 vs 买入持有
  4. 副图（可选）：持仓单位数
- **指标卡（实时）**：累计回报、年化收益、最大回撤、夏普、交易次数、胜率、盈亏比、平均持仓天数、最大单位、持仓占比
- **数据表格**：最近 N 天 OHLC + N(ATR) + 信号 + 单位数
- **交互**：参数改动即重算（所有海龟逻辑在浏览器端 JS 实现：Donchian + Wilder ATR + 单位栈状态机 + 净值）、tooltip、缩放、重置
- 数据源：首次从 `data/raw/<code>_*.csv` `fetch()` 加载并缓存于内存，切换股票无需重请求

## 8. 输出物

| 路径 | 说明 |
|------|------|
| `Turtle Strategy/turtle_strategy_backtest_spec.md` | 本文件 |
| `Turtle Strategy/turtle_backtest.py` | 回测 + 静态图脚本（Python 权威引擎，默认 `use_hfq=true`） |
| `Turtle Strategy/build_turtle_dashboard.py` | 看板生成器（把 4 股原始数据内嵌进 HTML，无需本地服务器） |
| `Turtle Strategy/turtle_dashboard.html` | 可调整参数交互看板（JS 端完整复刻回测引擎，默认 `use_hfq=true`） |
| `Turtle Strategy/figs/*.png` | 各股静态可视化（价格+通道+买卖标记+ATR+净值） |
| `Turtle Strategy/metrics_summary.csv` | 各股指标汇总 |

> **引擎一致性**：`turtle_dashboard.html` 的 JS 引擎与 `turtle_backtest.py` 在默认参数下逐位对齐
> （CR / AR / MDD / 夏普 / 回合数 / 持仓占比 误差 < 1e-6），已用 Node 交叉验证。

## 9. 默认参数（可配置）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `s1_entry` / `s1_exit` | 20 / 10 | System 1 入场/离场周期 |
| `s2_entry` / `s2_exit` | 55 / 20 | System 2 入场/离场周期 |
| `atr_period` | 20 | N（ATR）窗口 |
| `risk_per_unit` | 0.01 | 每单位风险占净值比例（1%） |
| `add_step` | 0.5 | 加仓间距（×N） |
| `max_units` | 4 | 单系统最大单位数 |
| `stop_mult` | 2.0 | 止损距离（×N） |
| `commission` | 0.0003 | 单边手续费（万三） |
| `initial_capital` | 1.0 | 初始净值 |
| `annualization_factor` | 252 | 年化因子 |
| `rf_annual` | 0.0 | 无风险年化（可改 0.02） |
| `combine_mode` | `both` | both / sys1_only / sys2_only |
| `use_hfq` | `true` | 是否用后复权重建 OHLC（**默认开启**：实测 `data/raw/*.csv` 为原始日线、含除权跳空，如比亚迪 2025-07-29 `close` 337→111.42 但 `pct_chg` 仅 +0.37%，须用后复权消除假突破） |
| `fill_mode` | `open` | 信号成交价：open（次日开盘）/ close |
| `start_date` / `end_date` | `None` / `None` | 回测区间（`'YYYY-MM-DD'`，None=全区间） |

## 10. 实现步骤

1. 编写 `Turtle Strategy/turtle_backtest.py`：`load → preprocess → donchian → atr(N) → signals/state_machine → backtest → metrics → plot → save`
2. 对 4 只股票循环运行，生成 PNG 与 `metrics_summary.csv`
3. 校验：手算某股前几个 20/55 日突破点与 2N 止损，确认信号与单位栈无误
4. 编写 `Turtle Strategy/turtle_dashboard.html`：复用 `dual_ma_dashboard.html` 骨架，
   以 JS 实现 Donchian + Wilder ATR + 单位栈状态机 + 净值，绑定控制面板实时重绘
5. 校验看板数值与 Python 引擎在默认参数下一致

## 11. 注意事项

- **前视偏差**：通道/ATR 用 t-1 及之前数据；信号 t-1 生成、t 日成交（`fill_mode`）；
- **交易成本**：默认计入，单边万三，增/减单位各扣一次；忽略成本则设 `commission=0`；
- **止损成交价**：触及止损时保守按 `min(stop_price, close[t])` 成交（避免止损价优于收盘价的不合理假设），可由 `fill_mode` 调整；
- **通道初始化**：前 `max(entry_period, atr_period)` 日空仓；
- 结果受参数与样本区间影响，仅代表历史表现，不构成未来收益保证；
- `use_hfq=true` 时若 `pct_chg` 不可用（如部分数据缺失），自动回退 `use_hfq=false` 并提示。
