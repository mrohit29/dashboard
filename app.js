const state={charts:{}};

function fmtCr(n){return `₹${Number(n).toLocaleString('en-IN')} Cr`}
function fmtPct(n){return `${Number(n).toFixed(2)}%`}

async function loadData(){
  const [weekly,sector,stocks]=await Promise.all([
    fetch('data/weekly.json?ts='+Date.now()).then(r=>r.json()),
    fetch('data/sector_fpi.json?ts='+Date.now()).then(r=>r.json()),
    fetch('data/stocks.json?ts='+Date.now()).then(r=>r.json())
  ]);
  return {weekly,sector,stocks};
}

function fillWeeks(weekly){
  const s=document.getElementById('weekSelect'); s.innerHTML='';
  weekly.weeks.forEach(w=>{const o=document.createElement('option');o.value=w.week_ending;o.textContent=w.week_ending;s.appendChild(o)});
}

function selectedWeek(weekly){
  const value=document.getElementById('weekSelect').value || weekly.weeks[weekly.weeks.length-1].week_ending;
  return weekly.weeks.find(w=>w.week_ending===value) || weekly.weeks.at(-1);
}

function renderSummary(w){
  const cards=[
    ['FII / FPI',fmtCr(w.fii),w.fii>=0?'positive':'negative'],
    ['DII',fmtCr(w.dii),w.dii>=0?'positive':'negative'],
    ['Combined',fmtCr(w.fii+w.dii),(w.fii+w.dii)>=0?'positive':'negative'],
    ['Market return',fmtPct(w.nifty_return_pct),w.nifty_return_pct>=0?'positive':'negative']
  ];
  document.getElementById('summaryCards').innerHTML=cards.map(([l,v,c])=>`<div class="card"><div class="label">${l}</div><div class="value ${c}">${v}</div></div>`).join('');
}

function destroy(name){if(state.charts[name])state.charts[name].destroy()}

function renderFlow(weekly){
  destroy('flow');
  state.charts.flow=new Chart(document.getElementById('flowChart'),{
    type:'bar',
    data:{labels:weekly.weeks.map(x=>x.week_ending),datasets:[
      {label:'FII/FPI',data:weekly.weeks.map(x=>x.fii)},
      {label:'DII',data:weekly.weeks.map(x=>x.dii)}
    ]},
    options:{responsive:true,plugins:{legend:{labels:{color:'#edf2f7'}}},scales:{x:{ticks:{color:'#93a4bd'}},y:{ticks:{color:'#93a4bd'}}}}
  });
}

function renderSector(sector){
  destroy('sector');
  const rows=[...sector.items].sort((a,b)=>Math.abs(b.flow_cr)-Math.abs(a.flow_cr)).slice(0,10);
  state.charts.sector=new Chart(document.getElementById('sectorChart'),{
    type:'bar',
    data:{labels:rows.map(x=>x.sector),datasets:[{label:'FPI flow (₹ Cr)',data:rows.map(x=>x.flow_cr)}]},
    options:{indexAxis:'y',responsive:true,plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#93a4bd'}},y:{ticks:{color:'#93a4bd'}}}}
  });
}

function renderStocks(stocks){
  const body=document.getElementById('stocksBody');
  body.innerHTML=stocks.items.sort((a,b)=>b.score-a.score).slice(0,12).map(s=>{
    const cls=s.score>=70?'positive':s.score<45?'negative':'';
    return `<tr>
      <td><strong>${s.symbol}</strong><div class="muted">${s.name}</div></td>
      <td class="${s.fii_qoq>=0?'positive':'negative'}">${fmtPct(s.fii_qoq)}</td>
      <td class="${s.dii_qoq>=0?'positive':'negative'}">${fmtPct(s.dii_qoq)}</td>
      <td>${fmtPct(s.promoter_change)}</td><td>${fmtPct(s.delivery_pct)}</td>
      <td>${s.rsi.toFixed(1)}</td><td>${s.pe.toFixed(1)}</td>
      <td class="score ${cls}">${s.score}</td>
    </tr>`;
  }).join('');
}

function renderNotes(meta,week){
  document.getElementById('notes').innerHTML=`
    <p><b>Week ending:</b> ${week.week_ending}</p>
    <p><b>Official sector-flow cadence:</b> fortnightly. The dashboard does not manufacture weekly sector-FPI numbers.</p>
    <p><b>Daily flow:</b> aggregated into weekly totals from daily FII/FPI and DII observations.</p>
    <p><b>Status:</b> ${meta.status}</p>
    <p><b>Data pipeline:</b> ${meta.sources.join(' · ')}</p>`;
}

async function render(){
  const data=await loadData();
  fillWeeks(data.weekly);
  const w=selectedWeek(data.weekly);
  renderSummary(w); renderFlow(data.weekly); renderSector(data.sector); renderStocks(data.stocks);
  renderNotes(data.weekly.meta,w);
}

document.getElementById('refreshBtn').addEventListener('click',render);
document.getElementById('weekSelect').addEventListener('change',async()=>{const d=await loadData();const w=selectedWeek(d.weekly);renderSummary(w);});
render().catch(e=>{document.getElementById('summaryCards').innerHTML='<div class="card"><div class="value negative">Data load error</div><div class="label">'+e.message+'</div></div>'});
