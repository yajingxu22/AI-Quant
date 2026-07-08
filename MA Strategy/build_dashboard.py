# -*- coding: utf-8 -*-
"""
生成可交互调参的 HTML 看板（dual_ma_dashboard.html）。

- 读取 Task 3/data/raw/ 下 4 只股票的后复权 close + 日期，嵌入为 JS 数据，
  使 HTML 完全自包含（仅需联网加载 Plotly CDN）。
- 浏览器端用 JavaScript 实时复现 Python 引擎逻辑：双均线 → 交叉事件信号 →
  回测（含万三成本）→ 指标。参数（股票 / 快线 / 慢线 / 交易成本 / 无风险利率）
  通过控件实时调整，图表与指标即时刷新。
"""

import glob
import json
import os

import pandas as pd

NAME_MAP = {
    "600031.SH": "三一重工",
    "600900.SH": "长江电力",
    "688981.SH": "中芯国际",
    "002594.SZ": "比亚迪",
}

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data", "raw")
OUT_HTML = os.path.join(HERE, "dual_ma_dashboard.html")


def build_data() -> dict:
    data = {}
    for fp in sorted(glob.glob(os.path.join(DATA_DIR, "*.csv"))):
        df = pd.read_csv(fp, encoding="utf-8-sig")
        df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d")
        df = df.sort_values("trade_date").reset_index(drop=True)
        code = os.path.basename(fp).split("_")[0]
        data[code] = {
            "name": NAME_MAP.get(code, code),
            "dates": df["trade_date"].dt.strftime("%Y-%m-%d").tolist(),
            "close": [round(float(x), 4) for x in df["close"].tolist()],
        }
    return data


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>双均线策略回测看板 · Task 3</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root{ --bg:#f5f7fa; --card:#ffffff; --line:#e3e8ef; --ink:#1f2933;
         --muted:#6b7785; --blue:#1f77b4; --orange:#ff7f0e;
         --green:#2ca02c; --red:#d62728; --accent:#2563eb; }
  *{box-sizing:border-box;}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",
       "Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--ink);}
  header{background:linear-gradient(90deg,#2563eb,#1f77b4);color:#fff;padding:18px 24px;}
  header h1{margin:0;font-size:20px;}
  header p{margin:4px 0 0;font-size:13px;opacity:.9;}
  .wrap{max-width:1180px;margin:0 auto;padding:18px;}
  .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;
         padding:16px 18px;margin-bottom:18px;box-shadow:0 1px 3px rgba(0,0,0,.04);}
  .controls{display:flex;flex-wrap:wrap;gap:16px 24px;align-items:flex-end;}
  .ctrl{display:flex;flex-direction:column;gap:6px;}
  .ctrl label{font-size:12px;color:var(--muted);}
  .ctrl select,.ctrl input{font-size:14px;padding:7px 9px;border:1px solid var(--line);
         border-radius:8px;background:#fff;color:var(--ink);min-width:96px;}
  .ctrl input[type=number]{width:110px;}
  .hint{font-size:11px;color:var(--muted);margin-top:2px;}
  .metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;}
  .metric{background:#f8fafc;border:1px solid var(--line);border-radius:10px;padding:12px 14px;}
  .metric .k{font-size:12px;color:var(--muted);}
  .metric .v{font-size:20px;font-weight:700;margin-top:4px;}
  .metric .sub{font-size:11px;color:var(--muted);margin-top:2px;}
  .pos{color:var(--green);} .neg{color:var(--red);}
  .charts{display:grid;gap:14px;}
  .chart{width:100%;height:430px;}
  footer{text-align:center;color:var(--muted);font-size:12px;padding:20px;}
  code{background:#eef2f7;padding:1px 5px;border-radius:4px;font-size:12px;}
</style>
</head>
<body>
<header>
  <h1>双均线（Dual MA）策略回测看板</h1>
  <p>后复权日线 · 交叉事件驱动（金叉买入 / 死叉卖出）· 含交易成本 · 指标实时计算</p>
</header>

<div class="wrap">
  <div class="panel">
    <div class="controls">
      <div class="ctrl">
        <label>股票</label>
        <select id="stock"></select>
      </div>
      <div class="ctrl">
        <label>快线周期 N_short</label>
        <input id="nshort" type="number" value="5" min="2" max="60" step="1">
        <span class="hint">默认 5 日</span>
      </div>
      <div class="ctrl">
        <label>慢线周期 N_long</label>
        <input id="nlong" type="number" value="20" min="3" max="250" step="1">
        <span class="hint">默认 20 日</span>
      </div>
      <div class="ctrl">
        <label>交易成本（万分之）</label>
        <input id="comm" type="number" value="3" min="0" max="50" step="0.5">
        <span class="hint">3 = 万三（0.03% 单边）</span>
      </div>
      <div class="ctrl">
        <label>无风险利率（年化 %）</label>
        <input id="rf" type="number" value="0" min="0" max="10" step="0.5">
        <span class="hint">默认 0</span>
      </div>
      <div class="ctrl">
        <label>起始日期</label>
        <input id="start" type="date">
        <span class="hint">留空 = 全区间起</span>
      </div>
      <div class="ctrl">
        <label>结束日期</label>
        <input id="end" type="date">
        <span class="hint">留空 = 全区间止</span>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="metrics" id="metrics"></div>
  </div>

  <div class="panel charts">
    <div id="chartPrice" class="chart"></div>
    <div id="chartEquity" class="chart"></div>
  </div>

  <footer>
    数据区间约 2025-07 ~ 2026-07（242 个交易日）· 区间/参数均可调 · 前视偏差已规避（信号 t-1 生成、t 日成交）·
    本看板仅供方法演示，不代表未来收益。
  </footer>
</div>

<script>
const DATA = __DATA__;

// ---------- 工具函数 ----------
const A = 252;
function sma(arr, n){
  const out = new Array(arr.length).fill(null);
  let sum = 0;
  for(let i=0;i<arr.length;i++){
    sum += arr[i];
    if(i>=n) sum -= arr[i-n];
    if(i>=n-1) out[i] = sum/n;
  }
  return out;
}
function sign(x){ return x>0?1:(x<0?-1:0); }
function fmtPct(x){ return (x*100).toFixed(2)+'%'; }
function cls(x){ return x>=0?'pos':'neg'; }

// ---------- 核心回测（与 Python 引擎一致）----------
function backtest(close, nShort, nLong, commission, rfAnnual){
  const N = close.length;
  const maS = sma(close, nShort);
  const maL = sma(close, nLong);
  const cross = new Array(N).fill(null);
  for(let i=0;i<N;i++){
    if(maS[i]===null||maL[i]===null) continue;
    cross[i] = sign(maS[i]-maL[i]);
  }
  const golden = new Array(N).fill(false);
  const death  = new Array(N).fill(false);
  for(let i=0;i<N;i++){
    if(i>=2 && cross[i-1]!==null && cross[i-2]!==null){
      const d = cross[i-1]-cross[i-2];
      if(d===2) golden[i]=true;
      else if(d===-2) death[i]=true;
    }
  }
  const pos = new Array(N).fill(0);
  let cur = 0;
  for(let i=0;i<N;i++){ if(golden[i]) cur=1; else if(death[i]) cur=0; pos[i]=cur; }
  const sw = new Array(N).fill(0);
  for(let i=1;i<N;i++) if(pos[i]!==pos[i-1]) sw[i]=1;
  const r = new Array(N).fill(0);
  for(let i=1;i<N;i++) r[i] = close[i]/close[i-1]-1;
  const stratR = new Array(N).fill(0);
  for(let i=0;i<N;i++) stratR[i] = pos[i]*r[i] - commission*sw[i];
  const equity = new Array(N).fill(1);
  const bh = new Array(N).fill(1 - commission);   // 买入持有：建仓时扣单边万三
  for(let i=1;i<N;i++){ equity[i]=equity[i-1]*(1+stratR[i]); bh[i]=bh[i-1]*(1+r[i]); }

  // 指标
  const cr = equity[N-1]/equity[0]-1;
  const numRet = Math.max(N-1,1);
  const ar = Math.pow(1+cr, A/numRet)-1;
  let peak = -Infinity, mdd = 0;
  for(let i=0;i<N;i++){ peak = Math.max(peak, equity[i]); mdd = Math.min(mdd, equity[i]/peak-1); }
  const mddAbs = Math.abs(mdd);
  const mean = stratR.reduce((a,b)=>a+b,0)/N;
  let varSum=0; for(let i=0;i<N;i++) varSum += (stratR[i]-mean)**2;
  const std = Math.sqrt(varSum/(N-1));
  const rfDaily = rfAnnual/A;
  const sharpe = std>0 ? (mean-rfDaily)/std*Math.sqrt(A) : 0;
  let downSum=0, downN=0;
  for(let i=0;i<N;i++) if(stratR[i]<0){ downSum += stratR[i]**2; downN++; }
  const downDevAnn = downN>1 ? Math.sqrt(downSum/(downN-1))*Math.sqrt(A) : 0;
  const sortino = downDevAnn>0 ? (mean*A - rfAnnual)/downDevAnn : 0;
  const calmar = mddAbs>0 ? ar/mddAbs : 0;
  const bhCr = bh[N-1]/bh[0]-1;
  let bhPeak=-Infinity, bhMdd=0;
  for(let i=0;i<N;i++){ bhPeak=Math.max(bhPeak,bh[i]); bhMdd=Math.min(bhMdd,bh[i]/bhPeak-1); }

  return {maS,maL,golden,death,pos,equity,bh,
    metrics:{cumulative_return:cr,annualized_return:ar,mdd:mddAbs,sharpe,sortino,calmar,
      num_trades:sw.reduce((a,b)=>a+b,0),bh_cumulative_return:bhCr,bh_mdd:Math.abs(bhMdd)}};
}

// ---------- 渲染 ----------
function render(){
  const code = document.getElementById('stock').value;
  const nShort = +document.getElementById('nshort').value;
  const nLong = +document.getElementById('nlong').value;
  const comm = (+document.getElementById('comm').value)/10000;
  const rf = (+document.getElementById('rf').value)/100;
  const start = document.getElementById('start').value || gMin;
  const end = document.getElementById('end').value || gMax;
  const d = DATA[code];
  // 按日期区间切片
  const idx = [];
  for(let i=0;i<d.dates.length;i++){ if(d.dates[i]>=start && d.dates[i]<=end) idx.push(i); }
  const dates = idx.map(i=>d.dates[i]);
  const close = idx.map(i=>d.close[i]);
  const res = backtest(close, nShort, nLong, comm, rf);
  const rangeTxt = `  [${start} ~ ${end}]`;

  // 指标卡片
  const m = res.metrics;
  const cards = [
    ['累计回报', fmtPct(m.cumulative_return), cls(m.cumulative_return), '买入持有 '+fmtPct(m.bh_cumulative_return)],
    ['年化收益', fmtPct(m.annualized_return), cls(m.annualized_return), '几何年化'],
    ['最大回撤', fmtPct(m.mdd), 'neg', '买入持有 '+fmtPct(m.bh_mdd)],
    ['夏普比率', m.sharpe.toFixed(2), cls(m.sharpe), '年化 ×√252'],
    ['索提诺', m.sortino.toFixed(2), cls(m.sortino), '仅下行波动'],
    ['卡玛比率', m.calmar.toFixed(2), cls(m.calmar), '年化/|MDD|'],
    ['交易次数', m.num_trades, '', '金叉+死叉'],
    ['参数', `MA${nShort}/${nLong}`, '', '成本 '+(comm*10000).toFixed(1)+'‱'],
  ];
  document.getElementById('metrics').innerHTML = cards.map(c=>
    `<div class="metric"><div class="k">${c[0]}</div><div class="v ${c[2]}">${c[1]}</div><div class="sub">${c[3]}</div></div>`
  ).join('');

  // 买入/卖出点
  const buyX=[],buyY=[],sellX=[],sellY=[];
  for(let i=0;i<dates.length;i++){
    if(res.golden[i]){ buyX.push(dates[i]); buyY.push(close[i]); }
    if(res.death[i]){ sellX.push(dates[i]); sellY.push(close[i]); }
  }
  const traces1 = [
    {x:dates,y:close,type:'scatter',mode:'lines',name:'收盘价(后复权)',line:{color:'#555',width:1}},
    {x:dates,y:res.maS,type:'scatter',mode:'lines',name:`MA${nShort}(快线)`,line:{color:'#1f77b4',width:1.3}},
    {x:dates,y:res.maL,type:'scatter',mode:'lines',name:`MA${nLong}(慢线)`,line:{color:'#ff7f0e',width:1.3}},
    {x:buyX,y:buyY,type:'scatter',mode:'markers',name:'金叉·买入',marker:{symbol:'triangle-up',size:10,color:'#2ca02c',line:{color:'#000',width:0.5}}},
    {x:sellX,y:sellY,type:'scatter',mode:'markers',name:'死叉·卖出',marker:{symbol:'triangle-down',size:10,color:'#d62728',line:{color:'#000',width:0.5}}},
  ];
  Plotly.newPlot('chartPrice', traces1, {
    title:{text:`${code} ${d.name}  双均线 MA${nShort}/${nLong}（后复权）${rangeTxt}`,font:{size:14}},
    margin:{t:40,r:16,b:36,l:48}, legend:{orientation:'h',y:1.08,x:0},
    xaxis:{type:'date'}, yaxis:{title:'价格'}, hovermode:'x unified'
  }, {responsive:true,displayModeBar:false});

  const traces2 = [
    {x:dates,y:res.equity,type:'scatter',mode:'lines',name:'策略净值',line:{color:'#2ca02c',width:1.6}},
    {x:dates,y:res.bh,type:'scatter',mode:'lines',name:'买入持有',line:{color:'#555',width:1.3,dash:'dash'}},
  ];
  Plotly.newPlot('chartEquity', traces2, {
    title:{text:'净值对比：策略 vs 买入持有',font:{size:14}},
    margin:{t:40,r:16,b:36,l:48}, legend:{orientation:'h',y:1.08,x:0},
    xaxis:{type:'date'}, yaxis:{title:'净值'}, hovermode:'x unified'
  }, {responsive:true,displayModeBar:false});
}

// ---------- 初始化 ----------
const sel = document.getElementById('stock');
Object.keys(DATA).forEach(code=>{
  const o=document.createElement('option'); o.value=code; o.textContent=`${code} ${DATA[code].name}`; sel.appendChild(o);
});
// 全局日期上下界（取所有股票并集）
let gMin='9999-12-31', gMax='0000-01-01';
for(const c in DATA){
  const d=DATA[c].dates;
  if(d[0]<gMin) gMin=d[0];
  if(d[d.length-1]>gMax) gMax=d[d.length-1];
}
document.getElementById('start').value = gMin;
document.getElementById('end').value = gMax;
['stock','nshort','nlong','comm','rf','start','end'].forEach(id=>document.getElementById(id).addEventListener('input',render));
render();
</script>
</body>
</html>
"""


def main():
    data = build_data()
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] 看板已生成 → {OUT_HTML}")
    print(f"     含 {len(data)} 只股票：", ", ".join(f"{c}({data[c]['name']})" for c in data))


if __name__ == "__main__":
    main()
