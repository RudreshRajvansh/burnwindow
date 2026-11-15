'use strict';
// Original explanation layer: descriptive statements from the displayed evidence.
// Never interprets report counts as fire counts, cloud truth, or hazard forecasts.
(()=>{
 let evidence=null;
 function note(id,anchor,where='after'){
  const p=document.createElement('p');p.id=id;p.className='data-meaning';p.hidden=true;
  anchor?.[where](p);return p;
 }
 function say(id,text){const p=$(id);if(!p)return;p.hidden=!text;p.replaceChildren();if(text){const b=document.createElement('strong');b.textContent='What this means: ';p.append(b,document.createTextNode(text));}}
 note('meaning-area',$('explore').querySelector('.workspace'),'before');
 const actions=document.createElement('div');actions.className='meaning-actions';actions.innerHTML='<button class="quiet" id="copy-explanation" disabled>Copy explanation</button><a href="#calendar">Explore historical context →</a>';$('meaning-area').after(actions);
 note('meaning-agreement',$('agreement-breakdown'));
 note('meaning-daily',$('daily-chart'),'before');
 note('meaning-calendar',$('calendar-content').querySelector('.section-intro'));
 note('meaning-season',$('season-summary'));
 note('meaning-model',$('model-metrics'),'before');
 note('meaning-evidence',$('evidence').querySelector('.section-intro'));
 function explore(){
  if(!analysis)return;const a=analysis.stats.aqua,b=analysis.stats[state.sensor],o=analysis.overlap;
  const prefix=`${LABELS[state.sensor]} recorded ${fmt(b.cell_days)} active cell-days around ${state.name}`;
  say('meaning-area',!b.file_complete?`${prefix}, but missing or partial source files prevent a complete count for these dates.`:b.cell_days?`${prefix} — each is one grid cell reporting on one UTC day, so this is not a count of separate fires.`:`No eligible ${LABELS[state.sensor]} reports were found around ${state.name}; unverified visibility means this does not prove there was no burning.`);
  say('meaning-agreement',!a.file_complete||!b.file_complete?'Some source dates are missing, so the displayed overlap describes only the reports available.':o.union?`Both satellites reported activity in ${fmt(o.both)} of ${fmt(o.union)} active cell-days (${pct(o.jaccard)}); this measures reporting overlap, not detection accuracy.`:'Neither platform has eligible reports in this selection, so agreement cannot be measured.');
  const rows=analysis.series.filter(r=>r[state.sensor]!=null),peak=rows.reduce((best,r)=>!best||r[state.sensor]>best[state.sensor]?r:best,null);
  say('meaning-daily',peak&&peak[state.sensor]>0?`${peak.date} had the largest recorded ${LABELS[state.sensor]} signal in this window (${fmt(peak[state.sensor])} active cells); other days can differ because of burning and observation conditions.`:'The available dates show no eligible VIIRS activity; gaps in the line mean unavailable source data.');
  $('copy-explanation').disabled=false;
 }
 function history(){
  if(historyData?.state!=='ready')return;
  const m=historyData.model,measure=$('calendar-measure').value;
  say('meaning-calendar',measure==='handoff'?'Stronger colours mean more recorded activity on the displayed Aqua scale; later values are estimates, and blank months have no usable loaded data.':`Stronger colours mean more ${measure==='aqua'?'Aqua':'VIIRS'} reported activity; compare the same calendar month across years, and treat blank months as missing data.`);
  const year=+$('season-year').value,rows=historyData.months.filter(r=>r.year===year&&r.aqua!=null),peak=rows.reduce((best,r)=>!best||r.aqua>best.aqua?r:best,null);
  say('meaning-season',peak&&peak.aqua>0?`${MONTHS[peak.month-1]} had the most Aqua activity among loaded months in ${year}; this describes the observed season, not when the next fire will occur.`:`No positive Aqua activity is available for the loaded months of ${year}, so a peak season cannot be identified.`);
  if(m.state!=='evaluated'){say('meaning-model','');return;}
  const raw=m.metrics.raw.wape,adjusted=m.metrics.pooled.wape,bias=m.metrics.pooled.bias;
  const direction=raw!=null&&adjusted!=null?(adjusted<raw?'reduces':adjusted>raw?'increases':'does not change'):null;
  say('meaning-model',adjusted==null?'There are too few Aqua comparison reports to calculate a percentage error.':`Seasonal adjustment ${direction||'has'} ${direction?'the total absolute error from '+fmt(raw,1)+'% to ':''}${fmt(adjusted,1)}% of the Aqua total${bias==null?'':`; estimates ${bias>0?'overstate':bias<0?'understate':'match'} the total by ${fmt(Math.abs(bias),1)}%`} across held-out months.`);
 }
 function validation(){
  say('meaning-evidence','This page separates the data behind your selected area from fixed validation studies, so you can check what was actually measured.');
  if(!evidence)return;
  if(!$('meaning-geo'))note('meaning-geo',$('v-geographic-table').closest('.scroll'),'before');
  const stratum=$('v-geographic-stratum').value,cases=evidence.geographic.cases.filter(c=>stratum==='all'||c.daynight===stratum),errors=cases.map(c=>c.metrics.pooled.wape).filter(v=>v!=null);
  say('meaning-geo',errors.length?`Across these ${cases.length} cases, adjusted absolute error is ${fmt(Math.min(...errors),1)}–${fmt(Math.max(...errors),1)}% of Aqua totals; ${stratum==='N'?'nighttime conversion is unreliable here.':'these are comparison errors, not percentages of fires detected.'}`:'No comparable geographic cases are available.');
  if(!$('meaning-events'))note('meaning-events',$('v-event-summary'));
  const dn=$('v-event-stratum').value,w=+$('v-event-window').value,km=+$('v-event-buffer').value;
  const r=evidence.independent.summary.find(r=>r.sensor==='noaa20'&&r.daynight===dn&&r.buffer_km===km&&r.window_days===w);
  if(r)say('meaning-events',`NOAA-20 reports coincide with ${r.events_with_reports} of ${r.evaluated_events} mapped events within ${w} days${km?' and a 1 km perimeter buffer':''}; this corroborates events without measuring fire-detection accuracy.`);
  if(!$('meaning-cloud'))note('meaning-cloud',$('v-nasa-summary').querySelector('.science-grid'),'before');
  const a=evidence.aqua,v=evidence.nasa_viirs;
  say('meaning-cloud',`${pct(a.counts.cloud/a.pixel_samples)} of sampled Aqua pixels and ${pct(v.counts.cloud/v.pixel_samples)} of sampled VIIRS pixels were cloud-labelled in this study; different observation times and pixel sizes prevent an accuracy ranking.`);
 }
 window.addEventListener('burnwindow-analysis',explore);
 window.addEventListener('burnwindow-history',history);
 window.addEventListener('burnwindow-validation',e=>{evidence=e.detail;validation();});
 window.addEventListener('burnwindow-scope',()=>{for(const id of ['area','agreement','daily','calendar','season','model'])say('meaning-'+id,'');$('copy-explanation').disabled=true;});
 document.addEventListener('change',e=>{if(['season-year','calendar-measure'].includes(e.target.id))history();if(e.target.id.startsWith('v-'))validation();});
 $('copy-explanation').onclick=async()=>{
  if(!analysis)return;
  const text=[`${state.name} · ${state.radius} km radius · ${state.start} to ${state.end} UTC · ${state.tier==='nrt'?'provisional reports':'standard archive'}`,$('meaning-area').textContent,$('meaning-agreement').textContent,'Observation coverage is unverified for this selection.',`Source/run ID: ${analysis.run_id}`,location.href].join('\n');
  try{await navigator.clipboard.writeText(text);toast('Explanation and analysis link copied.');}catch{download('BurnWindow-explanation.txt',text,'text/plain');toast('Explanation downloaded as text.');}
 };
 explore();history();validation();
})();
