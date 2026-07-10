#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成海龟策略可调参数 HTML 看板 (turtle_dashboard.html)
- 将 4 只股票的原始日线数据内嵌进 HTML, 双击即可打开, 无需本地服务器
- JS 端完整复刻 Python 回测引擎: 后复权重建 + Donchian 通道 + Wilder ATR + 单位栈状态机
- 默认 use_hfq = true (后复权), 所有参数可实时调整, 图形/指标即时重算
"""
import os
import glob
import json
import pandas as pd

RAW_DIR = "/Users/xuyajing/Desktop/AI/Quant/data/raw"
OUT_DIR = "/Users/xuyajing/Desktop/AI/Quant/Turtle Strategy"
OUT_HTML = os.path.join(OUT_DIR, "turtle_dashboard.html")

STOCKS = {
    "002594.SZ": "比亚迪",
    "600031.SH": "三一重工",
    "600900.SH": "长江电力",
    "688981.SH": "中芯国际",
}

def load_raw(code):
    path = glob.glob(os.path.join(RAW_DIR, f"{code}_*.csv"))[0]
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d")
    df = df.sort_values("trade_date").reset_index(drop=True)
    return {
        "dates": df["trade_date"].dt.strftime("%Y-%m-%d").tolist(),
        "open": df["open"].round(4).tolist(),
        "high": df["high"].round(4).tolist(),
        "low": df["low"].round(4).tolist(),
        "close": df["close"].round(4).tolist(),
        "pct_chg": df["pct_chg"].round(4).tolist(),
    }

def main():
    data = {code: load_raw(code) for code in STOCKS}
    data_json = json.dumps(data, ensure_ascii=False)
    names_json = json.dumps(STOCKS, ensure_ascii=False)

    html = HTML_TEMPLATE.replace("__DATA__", data_json).replace("__NAMES__", names_json)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"看板已生成: {OUT_HTML}")
    print(f"内嵌股票: {list(STOCKS.keys())} | 数据大小: {len(data_json)//1024} KB")

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>海龟策略回测看板 (Turtle Strategy)</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root{ --bg:#f5f7fa; --card:#ffffff; --line:#e3e8ef; --ink:#1f2933;
         --muted:#6b7785; --blue:#1f77b4; --orange:#ff7f0e;
         --green:#2ca02c; --red:#d62728; --accent:#2563eb; }
  *{box-sizing:border-box;}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",
       "Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--ink);}
  header{background:linear-gradient(90deg,#0f6e56,#1d9e75);color:#fff;padding:18px 24px;}
  header h1{margin:0;font-size:20px;}
  header p{margin:4px 0 0;font-size:13px;opacity:.92;}
  .wrap{max-width:1200px;margin:0 auto;padding:18px;}
  .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;
         padding:16px 18px;margin-bottom:18px;box-shadow:0 1px 3px rgba(0,0,0,.04);}
  .controls{display:flex;flex-wrap:wrap;gap:14px 22px;align-items:flex-end;}
  .ctrl{display:flex;flex-direction:column;gap:6px;}
  .ctrl label{font-size:12px;color:var(--muted);}
  .ctrl select,.ctrl input{font-size:14px;padding:7px 9px;border:1px solid var(--line);
         border-radius:8px;background:#fff;color:var(--ink);min-width:92px;}
  .ctrl input[type=number]{width:104px;}
  .grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px 22px;}
  .sub{font-size:12px;font-weight:700;color:var(--accent);margin:10px 0 2px;}
  .toggles{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;margin-top:6px;}
  .toggles label{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:5px;cursor:pointer;}
  .hint{font-size:11px;color:var(--muted);margin-top:2px;}
  .btn{background:var(--accent);color:#fff;border:none;border-radius:8px;padding:8px 14px;
       font-size:13px;cursor:pointer;}
  .btn:hover{opacity:.9;}
  .metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:12px;}
  .metric{background:#f8fafc;border:1px solid var(--line);border-radius:10px;padding:12px 14px;}
  .metric .k{font-size:12px;color:var(--muted);}
  .metric .v{font-size:20px;font-weight:700;margin-top:4px;}
  .metric .sub{font-size:11px;color:var(--muted);margin-top:2px;font-weight:400;}
  .pos{color:var(--green);} .neg{color:var(--red);}
  .charts{display:grid;gap:14px;}
  .chart{width:100%;height:430px;}
  .chart.atr{height:240px;}
  .chart.eq{height:300px;}
  footer{text-align:center;color:var(--muted);font-size:12px;padding:20px;}
  code{background:#eef2f7;padding:1px 5px;border-radius:4px;font-size:12px;}
</style>
</head>
<body>
<header>
  <h1>海龟策略回测看板 (Turtle Strategy)</h1>
  <p>后复权日线 · Donchian 通道突破 + ATR 头寸规模 + 金字塔加仓 + 硬性止损 · 双系统合并 · 含交易成本 · 指标实时计算</p>
</header>

<div class="wrap">
  <div class="panel">
    <div class="controls">
      <div class="ctrl">
        <label>股票</label>
        <select id="stock"></select>
      </div>
      <div class="ctrl">
        <label>起始日期</label>
        <input id="sdate" type="date">
      </div>
      <div class="ctrl">
        <label>结束日期</label>
        <input id="edate" type="date">
      </div>
      <div class="ctrl">
        <label>组合模式</label>
        <select id="combine">
          <option value="both">双系统 (S1+S2)</option>
          <option value="sys1_only">仅 System1</option>
          <option value="sys2_only">仅 System2</option>
        </select>
      </div>
      <div class="ctrl">
        <label>成交价</label>
        <select id="fill">
          <option value="open">次日开盘</option>
          <option value="close">当日收盘</option>
        </select>
      </div>
      <div class="ctrl">
        <label>&nbsp;</label>
        <button class="btn" id="reset">重置默认参数</button>
      </div>
    </div>

    <div class="sub">System 1 (短周期)</div>
    <div class="grid2">
      <div class="ctrl"><label>S1 入场周期 (日)</label><input id="s1e" type="number" value="20" min="2" max="120"><span class="hint">突破买入, 默认 20</span></div>
      <div class="ctrl"><label>S1 离场周期 (日)</label><input id="s1x" type="number" value="10" min="2" max="120"><span class="hint">跌破卖出, 默认 10</span></div>
    </div>
    <div class="sub">System 2 (长周期)</div>
    <div class="grid2">
      <div class="ctrl"><label>S2 入场周期 (日)</label><input id="s2e" type="number" value="55" min="5" max="250"><span class="hint">突破买入, 默认 55</span></div>
      <div class="ctrl"><label>S2 离场周期 (日)</label><input id="s2x" type="number" value="20" min="5" max="250"><span class="hint">跌破卖出, 默认 20</span></div>
    </div>
    <div class="sub">头寸与风险</div>
    <div class="grid2">
      <div class="ctrl"><label>ATR 周期 (N)</label><input id="atr" type="number" value="20" min="5" max="60"><span class="hint">波动率窗口, 默认 20</span></div>
      <div class="ctrl"><label>单位风险 (%)</label><input id="risk" type="number" value="1" min="0.1" max="5" step="0.1"><span class="hint">每单位风险占净值, 默认 1%</span></div>
      <div class="ctrl"><label>加仓间距 (×N)</label><input id="add" type="number" value="0.5" min="0.1" max="3" step="0.1"><span class="hint">金字塔, 默认 0.5N</span></div>
      <div class="ctrl"><label>最大单位</label><input id="maxu" type="number" value="4" min="1" max="10"><span class="hint">单系统上限, 默认 4</span></div>
      <div class="ctrl"><label>止损倍数 (×N)</label><input id="stop" type="number" value="2" min="0.5" max="6" step="0.5"><span class="hint">硬性止损, 默认 2N</span></div>
      <div class="ctrl"><label>手续费 (单边)</label><input id="comm" type="number" value="0.0003" min="0" max="0.01" step="0.0001"><span class="hint">默认万三 0.0003</span></div>
    </div>
    <div class="toggles">
      <label><input type="checkbox" id="hfq" checked> 后复权数据</label>
      <label><input type="checkbox" id="shS1" checked> 显示 S1 通道</label>
      <label><input type="checkbox" id="shS2" checked> 显示 S2 通道</label>
      <label><input type="checkbox" id="shBuy" checked> 显示买入信号</label>
      <label><input type="checkbox" id="shSell" checked> 显示卖出信号</label>
    </div>
  </div>

  <div class="panel">
    <div class="metrics" id="metrics"></div>
  </div>

  <div class="panel">
    <div class="charts">
      <div id="chartMain" class="chart"></div>
      <div id="chartATR" class="chart atr"></div>
      <div id="chartEq" class="chart eq"></div>
    </div>
  </div>

  <footer>
    海龟策略回测看板 · 数据区间约 2025-07 ~ 2026-07 · 回测结果仅代表历史表现, 不构成未来收益保证
  </footer>
</div>

<script>
const STOCK_DATA = __DATA__;
const STOCK_NAMES = __NAMES__;

// ---------- 数据加载 / 股票下拉 ----------
function initStockSelect(){
  const sel = document.getElementById('stock');
  for(const code of Object.keys(STOCK_NAMES)){
    const o = document.createElement('option');
    o.value = code; o.textContent = STOCK_NAMES[code] + ' ' + code;
    sel.appendChild(o);
  }
  // 日期范围默认
  const d0 = STOCK_DATA[Object.keys(STOCK_DATA)[0]].dates;
  document.getElementById('sdate').min = d0[0]; document.getElementById('sdate').max = d0[d0.length-1];
  document.getElementById('edate').min = d0[0]; document.getElementById('edate').max = d0[d0.length-1];
  document.getElementById('sdate').value = d0[0];
  document.getElementById('edate').value = d0[d0.length-1];
}

// ---------- 后复权重建 (pct_chg 累乘) ----------
function rebuildHfq(d){
  const rawClose = d.close.slice();
  const hfq = [rawClose[0]];
  for(let k=1;k<d.close.length;k++) hfq.push(hfq[k-1]*(1 + d.pct_chg[k]/100));
  const ratio = hfq.map((v,i)=> v/rawClose[i]);
  return {
    dates: d.dates,
    open:  d.open.map((v,i)=> v*ratio[i]),
    high:  d.high.map((v,i)=> v*ratio[i]),
    low:   d.low.map((v,i)=> v*ratio[i]),
    close: hfq
  };
}

// ---------- Wilder ATR ----------
function wilderAtr(high, low, close, period){
  const n = high.length;
  const tr = new Array(n).fill(0);
  for(let i=0;i<n;i++){
    const pc = i>0 ? close[i-1] : close[i];
    tr[i] = Math.max(high[i]-low[i], Math.abs(high[i]-pc), Math.abs(low[i]-pc));
  }
  const atr = new Array(n).fill(null);
  if(n>=period){ let s=0; for(let i=0;i<period;i++) s+=tr[i]; atr[period-1]=s/period; }
  for(let i=period;i<n;i++) atr[i] = (atr[i-1]*(period-1) + tr[i])/period;
  return atr;
}

// ---------- Donchian 通道 (shifted, 无前视) ----------
function donchian(high, low, entryP, exitP){
  const n = high.length;
  const upper = new Array(n).fill(null);
  const lower = new Array(n).fill(null);
  for(let t=entryP;t<n;t++){ let m=-Infinity; for(let k=t-entryP;k<t;k++) m=Math.max(m,high[k]); upper[t]=m; }
  for(let t=exitP;t<n;t++){ let m=Infinity;  for(let k=t-exitP;k<t;k++) m=Math.min(m,low[k]);  lower[t]=m; }
  return {upper, lower};
}

// ---------- 回测引擎 (复刻 Python) ----------
function backtest(raw, p){
  const d = p.useHfq ? rebuildHfq(raw) : raw;
  const {dates, open, high, low, close} = d;
  const n = close.length;
  const N = wilderAtr(high, low, close, p.atrPeriod);

  let sysList = [['s1', p.s1Entry, p.s1Exit], ['s2', p.s2Entry, p.s2Exit]];
  if(p.combine==='sys1_only') sysList = [sysList[0]];
  else if(p.combine==='sys2_only') sysList = [sysList[1]];

  const ch={}, sigUp={}, sigDn={};
  for(const [name, ep, xp] of sysList){
    const c = donchian(high, low, ep, xp); ch[name]=c;
    sigUp[name] = close.map((v,i)=> c.upper[i]!=null && v>c.upper[i]);
    sigDn[name] = close.map((v,i)=> c.lower[i]!=null && v<c.lower[i]);
  }
  const start = Math.max(p.atrPeriod, p.s1Entry, p.s2Entry);
  let cash = p.initial;
  const systems={}, R={};
  for(const [name] of sysList){ systems[name]={units:[], last_add:null};
    R[name]={open:false, pnl:0, sidx:null, count:0, wins:0, pfw:0, pfl:0, hs:0, hc:0}; }
  const equity = new Array(n).fill(null);
  const unitsCount = new Array(n).fill(0);
  const buyD=[], buyP=[], sellD=[], sellP=[];
  let eqPrev = p.initial;
  const size = (eq, Nv)=> eq*p.riskPerUnit/Nv;

  for(let t=0;t<n;t++){
    if(t>=start){
      for(const [name, ep, xp] of sysList){
        const sys = systems[name];
        const Nt = (t-1>=0) ? N[t-1] : null;
        if(Nt==null || Nt<=0) continue;
        const up  = (t-1>=0) ? sigUp[name][t-1] : false;
        const dn  = (t-1>=0) ? sigDn[name][t-1] : false;
        const level = (sys.last_add!=null) ? sys.last_add + p.addStep*Nt : null;
        const add  = (sys.units.length>0 && level!=null && (t-1>=0) &&
                      close[t-1]>=level && sys.units.length<p.maxUnits);
        // 1) 止损
        const keep=[];
        for(const u of sys.units){
          if(low[t] <= u.stop){
            const px=u.stop; cash += px*u.sh; cash -= p.commission*px*u.sh;
            R[name].pnl += (px-u.entry)*u.sh; sellD.push(dates[t]); sellP.push(px);
          } else keep.push(u);
        }
        sys.units = keep;
        // 2) 通道离场
        if(sys.units.length>0 && dn){
          const px = (p.fill==='open') ? open[t] : close[t];
          for(const u of sys.units){ cash += px*u.sh; cash -= p.commission*px*u.sh;
            R[name].pnl += (px-u.entry)*u.sh; sellD.push(dates[t]); sellP.push(px); }
          sys.units=[]; sys.last_add=null;
          const r=R[name];
          if(r.open){ r.open=false; r.count++; if(r.pnl>0){r.wins++; r.pfw+=r.pnl;} else r.pfl+=(-r.pnl);
            r.hs+=(t-r.sidx); r.hc++; r.pnl=0; r.sidx=null; }
        }
        // 3) 初始入场
        if(sys.units.length===0 && up){
          const px = (p.fill==='open') ? open[t] : close[t];
          const sh = size(eqPrev, Nt);
          cash -= px*sh + p.commission*px*sh;
          const sp = px - p.stopMult*Nt;
          sys.units.push({sh, entry:px, stop:sp});
          sys.last_add = px; buyD.push(dates[t]); buyP.push(px);
          const r=R[name]; if(!r.open){ r.open=true; r.pnl=0; r.sidx=t; }
        }
        // 4) 金字塔加仓
        else if(add){
          const px = (p.fill==='open') ? Math.max(open[t], level) : level;
          const sh = size(eqPrev, Nt);
          cash -= px*sh + p.commission*px*sh;
          const sp = px - p.stopMult*Nt;
          sys.units.push({sh, entry:px, stop:sp});
          sys.last_add = px; buyD.push(dates[t]); buyP.push(px);
        }
      }
      let totSh=0; for(const [name] of sysList) for(const u of systems[name].units) totSh+=u.sh;
      equity[t] = cash + totSh*close[t];
      unitsCount[t] = sysList.reduce((a,[name])=> a+systems[name].units.length, 0);
      eqPrev = equity[t];
    } else equity[t] = p.initial;
  }
  // 期末了结未平回合
  for(const [name] of sysList){ const r=R[name];
    if(r.open){ r.open=false; r.count++; if(r.pnl>0){r.wins++; r.pfw+=r.pnl;} else r.pfl+=(-r.pnl);
      r.hs+=(n-1-r.sidx); r.hc++; } }

  // ---- 指标 ----
  const eqV = equity.slice(start).filter(v=>v!=null);
  const ret=[]; for(let i=1;i<eqV.length;i++) ret.push(eqV[i]/eqV[i-1]-1);
  const A=p.annual, rf=p.rf/A;
  const CR = eqV[eqV.length-1]/p.initial - 1;
  const T = eqV.length-1;
  const AR = Math.pow(1+CR, A/T) - 1;
  let peak=-Infinity, mdd=0; for(const v of eqV){ peak=Math.max(peak,v); mdd=Math.max(mdd,(peak-v)/peak); }
  const mean = a => a.length? a.reduce((x,y)=>x+y,0)/a.length : 0;
  const std  = a => { if(!a.length) return 0; const m=mean(a); return Math.sqrt(a.reduce((s,x)=>s+(x-m)**2,0)/(a.length-1)); };
  const sharpe = (ret.length && std(ret)>0) ? (mean(ret)-rf)/std(ret)*Math.sqrt(A) : 0;
  const bh = eqV.map((_,i)=> p.initial*(1-p.commission)*close[start+i]/close[start]);
  const bhr=[]; for(let i=1;i<bh.length;i++) bhr.push(bh[i]/bh[i-1]-1);
  const bhCR = bh[bh.length-1]/p.initial - 1;
  const bhSharpe = (bhr.length && std(bhr)>0) ? (mean(bhr)-rf)/std(bhr)*Math.sqrt(A) : 0;
  const rounds = sysList.reduce((a,[name])=>a+R[name].count,0);
  const wins  = sysList.reduce((a,[name])=>a+R[name].wins,0);
  const pfw   = sysList.reduce((a,[name])=>a+R[name].pfw,0);
  const pfl   = sysList.reduce((a,[name])=>a+R[name].pfl,0);
  const hs    = sysList.reduce((a,[name])=>a+R[name].hs,0);
  const hc    = sysList.reduce((a,[name])=>a+R[name].hc,0);
  const winRate = rounds? wins/rounds : 0;
  const pf = pfl>0 ? pfw/pfl : (pfw>0 ? Infinity : 0);
  const avgHold = hc? hs/hc : 0;
  const maxU = Math.max(...unitsCount.slice(start));
  const uc = unitsCount.slice(start);
  const timeInMkt = uc.filter(v=>v>0).length / uc.length;

  return {dates, close, open, high, low, N, ch, sysList, start, equity, bh,
          buyD, buyP, sellD, sellP, unitsCount,
          metrics:{CR, AR, MDD:mdd, Sharpe:sharpe, bhCR, bhSharpe, rounds, winRate, pf, avgHold, maxU, timeInMkt}};
}

// ---------- 布局 ----------
const BASE = {margin:{l:55,r:20,t:38,b:38}, hovermode:'x unified', legend:{orientation:'h', y:-0.18, font:{size:10}}};
function mainLayout(){ return Object.assign({}, BASE, {title:{text:'价格 + 高低价通道 + 买卖信号', font:{size:13}}}); }
function atrLayout(){ return Object.assign({}, BASE, {title:{text:'ATR (N) 波动率', font:{size:13}}, margin:{l:55,r:20,t:30,b:30}}); }
function eqLayout(){ return Object.assign({}, BASE, {title:{text:'净值曲线: 海龟 vs 买入持有', font:{size:13}}, margin:{l:55,r:20,t:30,b:30}}); }

// ---------- 指标卡 ----------
function fmtPct(x){ return (x*100).toFixed(2)+'%'; }
function fmtNum(x,d=2){ return (x===Infinity)?'∞': x.toFixed(d); }
function cls(x){ return x>=0?'pos':'neg'; }
function updateMetrics(m){
  const cards = [
    ['累计回报', fmtPct(m.CR), cls(m.CR), '买入持有 '+fmtPct(m.bhCR)],
    ['年化收益', fmtPct(m.AR), cls(m.AR), ''],
    ['最大回撤', fmtPct(m.MDD), 'neg', '幅度'],
    ['夏普比率', fmtNum(m.Sharpe), m.Sharpe>=0?'pos':'neg', '买入持有 '+fmtNum(m.bhSharpe)],
    ['交易回合', m.rounds, '', ''],
    ['胜率', fmtPct(m.winRate), m.winRate>=0.5?'pos':'neg', ''],
    ['盈亏比', fmtNum(m.pf), m.pf>=1?'pos':'neg', '盈利/亏损'],
    ['平均持仓', m.avgHold.toFixed(1)+' 天', '', ''],
    ['最大单位', m.maxU, '', '单标的'],
    ['持仓占比', fmtPct(m.timeInMkt), '', '时间'],
  ];
  const el = document.getElementById('metrics');
  el.innerHTML = cards.map(c=>
    '<div class="metric"><div class="k">'+c[0]+'</div>'+
    '<div class="v '+c[2]+'">'+c[1]+'</div>'+
    (c[3]?'<div class="sub">'+c[3]+'</div>':'')+'</div>').join('');
}

// ---------- 渲染 ----------
function getParams(){
  return {
    s1Entry:+document.getElementById('s1e').value,
    s1Exit:+document.getElementById('s1x').value,
    s2Entry:+document.getElementById('s2e').value,
    s2Exit:+document.getElementById('s2x').value,
    atrPeriod:+document.getElementById('atr').value,
    riskPerUnit:(+document.getElementById('risk').value)/100,
    addStep:+document.getElementById('add').value,
    maxUnits:+document.getElementById('maxu').value,
    stopMult:+document.getElementById('stop').value,
    commission:+document.getElementById('comm').value,
    initial:1.0, annual:252, rf:0.0,
    combine:document.getElementById('combine').value,
    useHfq:document.getElementById('hfq').checked,
    fill:document.getElementById('fill').value,
    showS1:document.getElementById('shS1').checked,
    showS2:document.getElementById('shS2').checked,
    showBuy:document.getElementById('shBuy').checked,
    showSell:document.getElementById('shSell').checked,
  };
}

function render(){
  const p = getParams();
  const code = document.getElementById('stock').value;
  const raw = STOCK_DATA[code];
  // 日期过滤
  const sd = document.getElementById('sdate').value;
  const ed = document.getElementById('edate').value;
  const idx = [...Array(raw.dates.length).keys()].filter(i =>
     (!sd || raw.dates[i] >= sd) && (!ed || raw.dates[i] <= ed));
  const sub = {
    dates: idx.map(i=>raw.dates[i]), open: idx.map(i=>raw.open[i]),
    high: idx.map(i=>raw.high[i]), low: idx.map(i=>raw.low[i]),
    close: idx.map(i=>raw.close[i]), pct_chg: idx.map(i=>raw.pct_chg[i])
  };
  const res = backtest(sub, p);
  updateMetrics(res.metrics);

  const x = res.dates;
  const traces = [{x, y:res.close, name:'收盘价(后复权)', line:{color:'#555', width:1}, type:'scatter'}];
  for(const [name, ep, xp] of res.sysList){
    if((name==='s1' && !p.showS1) || (name==='s2' && !p.showS2)) continue;
    const c = (name==='s1') ? '#1f77b4' : '#ff7f0e';
    traces.push({x, y:res.ch[name].upper, name:name.toUpperCase()+' 上轨('+ep+')', line:{color:c, dash:'dash', width:1}, type:'scatter'});
    traces.push({x, y:res.ch[name].lower, name:name.toUpperCase()+' 下轨('+xp+')', line:{color:c, dash:'dot', width:1}, type:'scatter'});
  }
  if(p.showBuy)  traces.push({x:res.buyD, y:res.buyP, name:'买入(入场/加仓)', mode:'markers',
                     marker:{symbol:'triangle-up', size:9, color:'#2ca02c', line:{color:'#1b7a1b', width:0.5}}, type:'scatter'});
  if(p.showSell) traces.push({x:res.sellD, y:res.sellP, name:'卖出(止损/离场)', mode:'markers',
                     marker:{symbol:'triangle-down', size:9, color:'#d62728', line:{color:'#9b1c1c', width:0.5}}, type:'scatter'});
  Plotly.newPlot('chartMain', traces, mainLayout(), {responsive:true, displayModeBar:false});

  Plotly.newPlot('chartATR', [{x, y:res.N, name:'ATR(N)', line:{color:'#9467bd', width:1}, type:'scatter'}],
                 atrLayout(), {responsive:true, displayModeBar:false});

  const xs = x.slice(res.start);
  Plotly.newPlot('chartEq', [
    {x:xs, y:res.equity.slice(res.start), name:'海龟策略', line:{color:'#2ca02c', width:1.4}, type:'scatter'},
    {x:xs, y:res.bh, name:'买入持有', line:{color:'#555', dash:'dash', width:1}, type:'scatter'}
  ], eqLayout(), {responsive:true, displayModeBar:false});
}

// ---------- 绑定 ----------
function bind(){
  initStockSelect();
  const ids = ['stock','sdate','edate','combine','fill','s1e','s1x','s2e','s2x','atr','risk','add','maxu','stop','comm','hfq','shS1','shS2','shBuy','shSell'];
  ids.forEach(id=> document.getElementById(id).addEventListener('input', render));
  document.getElementById('reset').addEventListener('click', ()=>{
    document.getElementById('s1e').value=20; document.getElementById('s1x').value=10;
    document.getElementById('s2e').value=55; document.getElementById('s2x').value=20;
    document.getElementById('atr').value=20; document.getElementById('risk').value=1;
    document.getElementById('add').value=0.5; document.getElementById('maxu').value=4;
    document.getElementById('stop').value=2; document.getElementById('comm').value=0.0003;
    document.getElementById('combine').value='both'; document.getElementById('fill').value='open';
    document.getElementById('hfq').checked=true;
    document.getElementById('shS1').checked=true; document.getElementById('shS2').checked=true;
    document.getElementById('shBuy').checked=true; document.getElementById('shSell').checked=true;
    const d0 = STOCK_DATA[Object.keys(STOCK_DATA)[0]].dates;
    document.getElementById('sdate').value=d0[0]; document.getElementById('edate').value=d0[d0.length-1];
    render();
  });
  render();
}
bind();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
