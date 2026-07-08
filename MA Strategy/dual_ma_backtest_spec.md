# 双均线策略回测 Spec（Task 3）

## 1. 目标

利用已有的 A 股日线数据，构建"双均线（Dual Moving Average）"趋势跟踪策略并进行历史回测；绘制包含**股价、长短均线、买卖信号**的可视化图形；用**最大回撤（MDD）、夏普比率（Sharpe Ratio）、累计回报（Cumulative Return）** 三类指标评价策略质量。

## 2. 输入数据

- 原始位置：`Task 1&2/data/raw/`
- 为保持 Task 3 自包含，先复制到：`Task 3/data/raw/`
- 文件清单（4 只，区间 2025-07-02 ~ 2026-07-02，约 242 个交易日）：
  - `600031.SH_20250703_20260703.csv`（三一重工）
  - `600900.SH_20250703_20260703.csv`（长江电力）
  - `688981.SH_20250703_20260703.csv`（中芯国际）
  - `002594.SZ_20250703_20260703.csv`（比亚迪）
- 字段：`ts_code, trade_date(YYYYMMDD), open, high, low, close, pre_close, change, pct_chg, vol, amount, adj`
  - `adj` 列标记复权方式，本批数据值为 `hfq`（后复权）
- 回测使用列：`trade_date`（索引）、`close`（**后复权收盘价**）

### 2.1 后复权来源说明（重要）

本批数据的 `close` 为**真正连续的后复权价**，消除了除权除息造成的跳空（如比亚迪 2025-07-29 拆股 -66.9% 的断点已被抹平）。获取过程：

1. 直接 `pro.daily(adj='hfq')` 经实测**未对 OHLC 生效**（该账户疑似缺 hfq 权限，`adj` 被静默忽略，仅 `pct_chg` 为复权值）；
2. `pro.adj_factor` / `pro_bar(adj='hfq')` 接口被 Tushare 限流（触发后降至 **1 次/小时**），无法批量拉取；
3. **最终方案**：利用 Tushare 日线自带的 `pct_chg`（= 复权涨跌幅，已含分红送转的真实总回报），按
   `hfq_close[t] = hfq_close[t-1] × (1 + pct_chg[t]/100)`（锚定首日）累乘重建后复权价格路径，
   再用 `ratio = hfq_close/raw_close` 把 `open/high/low/pre_close` 同步复权。
   该结果与官方后复权**数学等价**（MDD / Sharpe / 累计回报 均为 scale-invariant，不受影响），已逐一校验
   序列自洽、拆股跳空消失、其余 -5%~-10% 均为真实市场波动。

> 实现脚本见 `Task 3/build_hfq_v2.py`（重建）、`fetch_hfq.py` 为最初未生效的尝试（保留备查）。

## 3. 数据预处理

- 读取 CSV → DataFrame，**务必用 `encoding='utf-8-sig'`** 消除首列 BOM（`ts_code` 才能正确解析）；
- `trade_date` 解析为 datetime，按日期升序排序；
- 取 `close` 列作为价格序列（已是后复权价，见 §2.1）；
- **回测区间过滤（可调）**：按 `start_date` / `end_date`（`'YYYY-MM-DD'`，`None` = 全区间）对日期索引切片，再做后续计算；区间过窄导致均线无法初始化时抛出提示；
- 缺失值：丢弃或前向填充（数据应已连续，仅做保护）；
- 4 只股票分别处理，函数化循环。

## 4. 策略定义（双均线）

- 快线（短周期）：`MA_short = SMA(close, N_short)`，默认 `N_short = 5`
- 慢线（长周期）：`MA_long  = SMA(close, N_long)`，默认 `N_long = 20`
- 信号规则（以交叉事件驱动，而非每日重算持仓状态）：
  - 定义方向变量 `cross_t = +1`（当 `MA_short_t > MA_long_t`），`cross_t = -1`（当 `MA_short_t < MA_long_t`）
  - **金叉（Golden Cross）**：`cross_t - cross_{t-1} = +2`（即由 -1 翻转为 +1）→ 买入信号，持仓置 1
  - **死叉（Death Cross）**：`cross_t - cross_{t-1} = -2`（即由 +1 翻转为 -1）→ 卖出信号，持仓置 0
  - 其余交易日持仓维持不变，**只在交叉事件发生时切换**
  - 说明：该写法与"每日用 `MA_short > MA_long` 判断持仓"在序列**内部**完全等价（持仓本就只在交叉处翻转）；
    但交叉事件法更严谨——不会在首根均线刚算出就出现 `short > long` 时"凭空满仓"，而是等待一次真实金叉才入场。

## 5. 回测引擎

- 资产日收益：`r_t = close_t / close_{t-1} - 1`
- **避免前视偏差**：第 t 日的持仓与切换均由"截至 t-1 日"的均线交叉事件决定，t 日才执行：
  - 方向变量 `cross_k = +1`（`MA_short_k > MA_long_k`）/ `-1`（`MA_short_k < MA_long_k`），k = t-2, t-1
  - 金叉事件 `golden_{t-1} = (cross_{t-1} - cross_{t-2} == +2)`
  - 死叉事件 `death_{t-1}  = (cross_{t-1} - cross_{t-2} == -2)`
  - 持仓递推（初始 `pos = 0`，并以首个可用 `cross` 作为种子避免首日误触发）：
    `pos_t = pos_{t-1}`；若 `golden_{t-1}` 则 `pos_t = 1`；若 `death_{t-1}` 则 `pos_t = 0`
  - 切换标记 `switch_t = golden_{t-1} or death_{t-1}`（仅交叉事件当日计费，空仓维持不扣费）
- 策略日收益（含交易成本）：`strat_r_t = pos_t * r_t - commission * switch_t`
  - `commission` 默认 **万三（0.0003，单边）**；每次切换（开仓或平仓）各扣一次，买卖往返合计约 **0.0006**
  - 仅在持仓实际切换时计费，空仓维持（`switch_t = 0`）不扣费
- 策略净值曲线：`equity_t = equity_{t-1} * (1 + strat_r_t)`，`equity_0 = 1.0`
- 对照基准：**买入持有（Buy & Hold）**净值
  `bh_t = (1 - commission) · ∏(1 + r_k)`（建仓当日即扣除单边 `commission`，与策略一致，期末均处于持有状态，不再另计退出佣金）
- 前 `N_long - 1` 日均线无值，期间 `pos = 0`（空仓）

## 6. 评价指标

设策略日收益序列为 `s_t`，年化因子 `A = 252`，无风险年化 `rf`（默认 0，可选 0.02）：

- **累计回报 Cumulative Return**
  ```
  CR = equity_last / equity_0 - 1 = ∏(1 + s_t) - 1
  ```
- **年化收益 Annualized Return（参考）**
  ```
  AR = (1 + CR)^(A / T) - 1        # T 为交易日数
  ```
- **最大回撤 MDD**
  ```
  peak_t = max_{k<=t} equity_k
  MDD = min_t (peak_t - equity_t) / peak_t     # 负值；报告时取绝对值（正数幅度），如 19.21%
  ```
- **夏普比率 Sharpe（年化）**
  ```
  rf_daily = rf / A
  Sharpe = (mean(s_t) - rf_daily) / std(s_t) * sqrt(A)
  # 若 rf = 0：Sharpe = mean(s_t) / std(s_t) * sqrt(252)
  ```
- （可选补充）索提诺比率（下行波动）、卡玛比率（AR / |MDD|）

## 7. 可视化（matplotlib）

每只股票输出一张主图（主示例股 `600031.SH` 重点展示，其余批量输出）：

- **子图 1 — 价格与均线 + 信号**
  - 收盘价折线（灰）
  - `MA_short` 折线（蓝）
  - `MA_long` 折线（橙）
  - 买入信号：金叉点在收盘价上用绿色 ▲ 标注
  - 卖出信号：死叉点在收盘价上用红色 ▼ 标注
  - 含图例、标题（股票代码 + `MA{N_short}/{N_long}`）
- **子图 2 — 净值对比**
  - 策略净值（绿）vs 买入持有净值（灰虚线）
- **指标面板**：在图侧或单独文本块输出
  `MDD / Sharpe / Cumulative Return / Annualized Return` 数值
- 保存为 PNG：`Task 3/figs/<code>_dual_ma.png`
- （可选）用 plotly 额外生成交互式 HTML 便于缩放查看

## 8. 输出物

| 路径 | 说明 |
|------|------|
| `Task 3/data/raw/` | 复制的原始数据 |
| `Task 3/dual_ma_backtest.py` | 回测脚本 |
| `Task 3/figs/*.png` | 可视化图形 |
| `Task 3/metrics_summary.csv` | 各股指标汇总 |
| `Task 3/dual_ma_backtest_spec.md` | 本文件 |

## 9. 默认参数（可配置）

| 参数 | 默认值 |
|------|--------|
| `N_short` | 5 |
| `N_long` | 20 |
| `rf_annual` | 0.0（可改 0.02） |
| `annualization_factor` | 252 |
| `initial_capital` | 1.0 |
| `commission`（交易成本，单边） | 0.0003（万三，即 0.03%；pos 由 0→1 买入或 1→0 卖出切换时按单边扣除，买卖往返合计约 0.0006；买入持有基准建仓时同样扣除） |
| `start_date` / `end_date`（回测区间，可调） | `None` / `None`（`'YYYY-MM-DD'`，`None` 表示全区间） |

## 10. 实现步骤

1. 复制 `Task 1&2/data/raw/*.csv` → `Task 3/data/raw/`
2. 编写 `Task 3/dual_ma_backtest.py`：`load → preprocess → MA → signals → backtest → metrics → plot → save`
3. 对 4 只股票循环运行，生成图与汇总 CSV
4. 校验：手算某股前几个金叉/死叉点，确认信号与指标无误

## 11. 注意事项

- **前视偏差**：信号用 `t-1` 生成，`t` 日才成交；
- **交易成本**：默认计入，单边 `commission = 0.0003`（万三），在持仓由 0→1（买入）或 1→0（卖出）切换当日从当日收益中扣除；买卖往返合计约 0.0006。若要忽略成本，将 `commission` 设为 0 即可；
- 均线前 `N_long-1` 日无值，期间按空仓处理；
- 结果受参数与样本区间影响，仅代表历史表现，不构成未来收益保证。
