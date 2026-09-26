const state={charts:{}};

function fmtCr(n){return `₹${Number(n).toLocaleString('en-IN')} Cr`}
function fmtPct(n){return `${Number(n).toFixed(2)}%`}

async function loadData(){
  const getJson=async(path,label)=>{
    const r=await fetch(path+'?ts='+Date.now());
    if(!r.ok)throw new Error(label+' failed: '+r.status);
    return r.json();
  };

  const results=await Promise.allSettled([
    getJson('data/weekly.json','weekly.json'),
    getJson('data/sector_fpi.json','sector_fpi.json'),
    getJson('data/stocks.json','stocks.json')
  ]);

  const [weeklyR,sectorR,stocksR]=results;

  if(weeklyR.status==='rejected') throw weeklyR.reason;

  return {
    weekly:weeklyR.value,
    sector:sectorR.status==='fulfilled' ? sectorR.value : {as_of:null,items:[],warning:'Sector data unavailable'},
    stocks:stocksR.status==='fulfilled' ? stocksR.value : {items:[],meta:{status:'Stock screen unavailable'}}
  };
}

function fillWeeks(weekly){
  const s=document.getElementById('weekSelect'); s.innerHTML='';
  [...weekly.weeks].reverse().forEach(w=>{
    const o=document.createElement('option');
    o.value=w.week_ending;
    o.textContent=w.week_ending;
    s.appendChild(o);
  });
}

function selectedWeek(weekly){
  const value=document.getElementById('weekSelect').value || weekly.weeks.at(-1).week_ending;
  return weekly.weeks.find(w=>w.week_ending===value) || weekly.weeks.at(-1);
}

function renderSummary(w){
  const cards=[
    ['FII / FPI',fmtCr(w.fii),w.fii>=0?'positive':'negative'],
    ['DII',fmtCr(w.dii),w.dii>=0?'positive':'negative'],
    ['Combined',fmtCr(w.fii+w.dii),(w.fii+w.dii)>=0?'positive':'negative'],
    ['Market return',w.nifty_return_pct == null ? '—' : fmtPct(w.nifty_return_pct),(w.nifty_return_pct ?? 0)>=0?'positive':'negative']
  ];
  document.getElementById('summaryCards').innerHTML=cards.map(([l,v,c])=>`<div class="card"><div class="label">${l}</div><div class="value ${c}">${v}</div></div>`).join('');
}

function destroy(name){if(state.charts[name])state.charts[name].destroy()}

function chartOptions(){
  return {
    responsive:true,
    interaction:{mode:'index',intersect:false},
    plugins:{legend:{labels:{color:'#edf2f7'}}},
    scales:{
      x:{ticks:{color:'#93a4bd'},grid:{color:'rgba(147,164,189,.08)'}},
      y:{ticks:{color:'#93a4bd'},grid:{color:'rgba(147,164,189,.08)'}}
    }
  };
}

function renderFlow(selected){
  destroy('flow');

  const heading=document.querySelector('#flowChart')?.closest('.panel')?.querySelector('.panel-head h2');
  if(heading){
    heading.textContent='Weekly FII / DII Flow · '+selected.week_ending;
  }

  state.charts.flow=new Chart(document.getElementById('flowChart'),{
    type:'bar',
    data:{
      labels:[selected.week_ending],
      datasets:[
        {label:'FII/FPI',data:[selected.fii],borderWidth:0},
        {label:'DII',data:[selected.dii],borderWidth:0}
      ]
    },
    options:chartOptions()
  });
}

function renderTrend(weekly){
  destroy('trend');
  state.charts.trend=new Chart(document.getElementById('trendChart'),{
    type:'line',
    data:{
      labels:weekly.weeks.map(x=>x.week_ending),
      datasets:[
        {
          label:'FII/FPI',
          data:weekly.weeks.map(x=>x.fii),
          tension:.25,
          pointRadius:3,
          borderWidth:2
        },
        {
          label:'DII',
          data:weekly.weeks.map(x=>x.dii),
          tension:.25,
          pointRadius:3,
          borderWidth:2
        }
      ]
    },
    options:chartOptions()
  });
}

function renderSector(sector){
  destroy('sector');
  const heading=document.querySelector('#sectorChart')?.closest('.panel')?.querySelector('.panel-head h2');
  if(heading){
    const asOf=sector.as_of ? new Date(sector.as_of).toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'}) : 'date unavailable';
    heading.textContent='Sector Rotation · FPI (as of '+asOf+')';
  }
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
  const status=meta?.status || 'unknown';
  const sources=(meta?.sources || []).join(' · ');
  document.getElementById('notes').innerHTML=`
    <p><b>Week ending:</b> ${week.week_ending}</p>
    <p><b>Official sector-flow cadence:</b> fortnightly. The dashboard does not manufacture weekly sector-FPI numbers.</p>
    <p><b>Daily flow:</b> aggregated into weekly totals from daily FII/FPI and DII observations.</p>
    <p><b>Status:</b> ${status}</p>
    <p><b>Data pipeline:</b> ${sources}</p>`;
}

async function render(){
  const data=await loadData();
  fillWeeks(data.weekly);
  const w=selectedWeek(data.weekly);
  renderSummary(w);
  renderFlow(w);
  renderTrend(data.weekly);
  renderSector(data.sector);
  renderStocks(data.stocks);
  renderNotes(data.weekly.meta,w);
}

document.getElementById('refreshBtn').addEventListener('click',render);
document.getElementById('weekSelect').addEventListener('change',async()=>{
  const d=await loadData();
  const w=selectedWeek(d.weekly);
  renderSummary(w);
  renderFlow(w);
});

render().catch(e=>{
  console.error(e);
  document.getElementById('summaryCards').innerHTML=
    '<div class="card"><div class="value negative">Data load error</div><div class="label">'+e.message+'</div></div>';
});
