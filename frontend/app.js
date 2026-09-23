'use strict';
const $ = id => document.getElementById(id);
const state = {data:null, selected:null, horizon:48, chart:'power', cursor:0, timer:null, map:null, markers:new Map(), customMarker:null, busy:false};
const colors = {power:'#b8ed85',wind_ms:'#80b0ef',temperature_c:'#b7a0e7'};
const units = {power:'%',wind_ms:'м/с',temperature_c:'°C'};
const fmt = (n,d=1) => Number.isFinite(Number(n)) ? Number(n).toLocaleString('ru-RU',{minimumFractionDigits:d,maximumFractionDigits:d}) : '—';
function dateLabel(value,withDate=true){const clean=value.replace('T',' ').slice(0,16);const [day,time]=clean.split(' ');if(!day||!time)return value;const [,month,date]=day.split('-');return withDate?`${date} ${['','янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'][Number(month)]}, ${time}`:time;}
const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,4500);}
function visibleRows(){return (state.selected?.forecast||[]).filter(r=>r.horizon_hours<=state.horizon);}
function pause(){clearInterval(state.timer);state.timer=null;$('play-forecast').textContent='▶';$('play-forecast').setAttribute('aria-label','Воспроизвести прогноз');}
async function request(url,options={}){const response=await fetch(url,options);let data;try{data=await response.json();}catch{throw new Error('Сервер вернул неожиданный ответ. Проверьте, запущен ли backend.');}if(!response.ok){throw new Error(typeof data.detail==='string'?data.detail:'Проверьте параметры запроса и попробуйте ещё раз.');}return data;}
async function load(){
 $('app-error').hidden=true;
 try{state.data=await request('/api/v1/dashboard');if(!state.data.turbines.length)throw new Error('Нет данных турбин.');renderStationList();initMap();selectStation(state.data.turbines[0]);$('export-top').disabled=false;const mae=state.data.metrics?.overall?.catboost?.mae;if(mae!=null)$('mae-footer').textContent=`MAE ${fmt(mae*100)}% номинала · окт–янв`;
 }catch(error){$('app-error').querySelector('span').textContent=error.message;$('app-error').hidden=false;$('chart-empty').textContent='Прогноз пока недоступен';}
}
function renderStationList(){
 const container=$('station-list');container.replaceChildren();
 for(const station of state.data.turbines){const button=document.createElement('button');button.className='station-item';button.dataset.id=station.id;button.innerHTML=`${icon('turbine')}<span>${station.name}</span><b>${station.snapshot?fmt(station.snapshot.power*100,0)+'%':'—'}</b>${icon('chevron')}`;button.addEventListener('click',()=>{selectStation(station);if(state.map)state.map.flyTo([station.latitude,station.longitude],16,{duration:.5});});container.append(button);}
}
function selectStation(station){pause();state.selected=station;state.cursor=0;render();updateMarkers();}
function render(){
 if(!state.selected)return;
 const s=state.selected,rows=visibleRows(),snap=s.snapshot,custom=s.mode==='scenario';
 $('station-name').textContent=s.name;$('station-coordinates').textContent=`${s.latitude.toFixed(5)}, ${s.longitude.toFixed(5)}`;
 $('map-coordinates').textContent=`${s.latitude.toFixed(4)}°, ${s.longitude.toFixed(4)}°`;
 $('map-context-label').textContent=custom?'Оценка новой площадки':'Алматинская область';
 $('station-kind').textContent=custom?'СЦЕНАРИЙ':'ВЭС';
 $('station-status').innerHTML=`<i class="dot"></i>${custom?'Нет датчиков':snap?(snap.power>.02?'Выработка есть':'Низкая выработка'):'Нет наблюдений'}`;
 $('station-status').classList.toggle('scenario',custom);
 $('station-power-label').textContent=custom?'Измеренная мощность':'Измеренная мощность';
 $('station-power').textContent=snap?fmt(snap.power*100):'—';
 $('sensor-timestamp').textContent=snap?dateLabel(snap.timestamp):'Наблюдения отсутствуют';
 $('sensor-samples').textContent=snap?`${snap.samples}/6 замеров`:'';
 $('station-note').textContent=custom?'Оценка перенесена с исходной турбины. На этой площадке точность не проверена.':'Архив датчиков · состояние оценено по мощности. Аварийные сигналы не предоставлены.';
 document.querySelectorAll('.station-item').forEach(b=>{b.classList.toggle('active',b.dataset.id===s.id);b.setAttribute('aria-pressed',String(b.dataset.id===s.id));});
 $('wind-label').textContent=custom?'Ветер · прогноз':'Ветер на турбине';$('temp-label').textContent=custom?'Температура · прогноз':'Температура на ВЭС';
 $('wind-source').textContent=custom?'На выбранный час':'Последний час наблюдений';$('temp-source').textContent=custom?'На выбранный час':'Последний час наблюдений';
 if(snap){$('sensor-wind').textContent=fmt(snap.wind_ms);$('sensor-temp').textContent=fmt(snap.temperature_c);$('temp-state').textContent='архив';}
 if(!rows.length){$('chart-empty').hidden=false;return;}
 const avg=rows.reduce((a,r)=>a+r.power,0)/rows.length,peak=rows.reduce((a,r)=>r.power>a.power?r:a,rows[0]);
 $('avg-power').textContent=fmt(avg*100);$('avg-period').textContent=`· ${state.horizon} ч`;$('peak-power').textContent=fmt(peak.power*100);$('peak-time').textContent=dateLabel(peak.target_time);
 $('forecast-subtitle').textContent=`${s.name} · выпуск 01 фев, 00:00 · Алматы`;
 $('table-caption').textContent=`${s.name} · ${rows.length} часов · мощность от номинала`;
 $('avg-power').closest('.metric').title='Среднее значение прогнозной мощности на выбранном горизонте';
 const pts=rows.map((r,i)=>`${i*104/(rows.length-1)},${29-r.power*27}`).join(' ');$('spark-power').innerHTML=`<polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>`;
 $('forecast-hour').max=rows.length-1;state.cursor=Math.min(state.cursor,rows.length-1);$('forecast-hour').value=state.cursor;
 renderInsights(rows);renderChart();renderTable(rows);
}
function renderInsights(rows){
 const low=rows.filter(r=>r.wind_ms<3).length,minTemp=Math.min(...rows.map(r=>r.temperature_c)),maxTemp=Math.max(...rows.map(r=>r.temperature_c));
 const maxWind=Math.max(...rows.map(r=>r.wind_ms));
 $('insight-wind-title').textContent=low?'Периоды слабого ветра':'Ветровые условия';
 $('insight-wind').textContent=low?`${low} из ${rows.length} ч с ветром ниже 3 м/с. Возможна низкая мощность.`:`Скорость ветра достигает ${fmt(maxWind)} м/с по прогнозу на высоте 100 м.`;
 $('insight-temp-title').textContent=minTemp<=-19?'Холоднее обучающей истории':'Температурный режим';
 $('insight-temp').textContent=`От ${fmt(minTemp)} до ${fmt(maxTemp)} °C. ${minTemp<=-19?'Оценка мощности при таком холоде менее надёжна.':'Обледенение не подтверждается одной температурой.'}`;
 let ramp=0,at=rows[0];for(let i=1;i<rows.length;i++){const change=Math.abs(rows[i].power-rows[i-1].power);if(change>ramp){ramp=change;at=rows[i];}}
 $('insight-ramp').textContent=`Максимальное изменение за час: ${fmt(ramp*100)} п.п. · ${dateLabel(at.target_time)}.`;
}
let chartGeometry=null;
function renderChart(){
 $('chart-tooltip').hidden=true;
 const rows=visibleRows();if(!rows.length)return;
 const wrap=$('chart-wrap'),svg=$('forecast-chart'),w=Math.max(280,wrap.clientWidth),h=wrap.clientHeight,pad={left:38,right:17,top:20,bottom:34};
 const values=rows.map(r=>r[state.chart]*(state.chart==='power'?100:1));
 let min=0,max=100;if(state.chart==='wind_ms')max=Math.max(5,Math.ceil(Math.max(...values)/5)*5);if(state.chart==='temperature_c'){min=Math.floor((Math.min(...values)-1)/5)*5;max=Math.ceil((Math.max(...values)+1)/5)*5;}
 const width=w-pad.left-pad.right,height=h-pad.top-pad.bottom,x=i=>pad.left+i*width/(rows.length-1),y=v=>pad.top+height-(v-min)*height/(max-min);
 svg.setAttribute('viewBox',`0 0 ${w} ${h}`);const color=colors[state.chart];let content=`<defs><linearGradient id="chart-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="${color}" stop-opacity=".24"/><stop offset="100%" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>`;
 for(let i=0;i<5;i++){const v=min+(max-min)*i/4,yy=y(v);content+=`<line x1="${pad.left}" x2="${w-pad.right}" y1="${yy}" y2="${yy}" stroke="#2c3c46" stroke-dasharray="3 5" stroke-width=".7"/><text x="${pad.left-10}" y="${yy+3}" text-anchor="end" font-size="9" fill="#7b929f">${fmt(v,0)}</text>`;}
 const ticks=w<470?[0,Math.round((rows.length-1)/2),rows.length-1]:[0,Math.round((rows.length-1)/4),Math.round((rows.length-1)/2),Math.round(3*(rows.length-1)/4),rows.length-1];
 for(const index of ticks){const date=rows[index].target_time.slice(5,10).split('-').reverse().join('.');const label=`${date} ${dateLabel(rows[index].target_time,false)}`;content+=`<text x="${x(index)}" y="${h-10}" text-anchor="${index===0?'start':index===rows.length-1?'end':'middle'}" font-size="9" fill="#849ba8">${label}</text>`;}
 const points=values.map((v,i)=>`${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
 const path=values.map((v,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
 content+=`<path d="${path} L${x(rows.length-1)},${y(min)} L${x(0)},${y(min)} Z" fill="url(#chart-fill)"/><polyline points="${points}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/><g id="chart-cursor"><line y1="${pad.top}" y2="${h-pad.bottom}" stroke="${color}" stroke-opacity=".45" stroke-dasharray="3 4"/><circle r="4" fill="${color}" stroke="#18252b" stroke-width="2"/></g>`;
 svg.innerHTML=content;$('chart-empty').hidden=true;$('chart-unit').textContent=state.chart==='power'?'% от номинала':units[state.chart];
 chartGeometry={x,y,w,h,values,pad,width};updateCursor(state.cursor,false);
}
function updateCursor(index,showTooltip=false){
 const rows=visibleRows();if(!rows.length||!chartGeometry)return;state.cursor=Math.max(0,Math.min(index,rows.length-1));const r=rows[state.cursor],g=chartGeometry,cursor=$('chart-cursor'),xx=g.x(state.cursor),yy=g.y(g.values[state.cursor]);
 if(cursor){const line=cursor.querySelector('line');line.setAttribute('x1',xx);line.setAttribute('x2',xx);const circle=cursor.querySelector('circle');circle.setAttribute('cx',xx);circle.setAttribute('cy',yy);}
 $('forecast-hour').value=state.cursor;$('selected-time').textContent=dateLabel(r.target_time);$('selected-reading').textContent=`${fmt(r.power*100)}% · ${fmt(r.wind_ms)} м/с · ${fmt(r.temperature_c)} °C`;
 if(state.selected.mode==='scenario'){$('sensor-wind').textContent=fmt(r.wind_ms);$('sensor-temp').textContent=fmt(r.temperature_c);$('temp-state').textContent='прогноз';}
 if(showTooltip){const tooltip=$('chart-tooltip');tooltip.replaceChildren();const date=document.createElement('span');date.textContent=dateLabel(r.target_time);const value=document.createElement('b');value.textContent=`${fmt(g.values[state.cursor])} ${units[state.chart]}`;tooltip.append(date,value);tooltip.style.left=`${Math.min(Math.max(0,xx-45),g.w-145)}px`;tooltip.style.top=`${Math.max(4,yy-65)}px`;tooltip.hidden=false;}
}
function renderTable(rows){$('hourly-table').innerHTML=rows.map(r=>`<tr><td>${dateLabel(r.target_time)}</td><td>${fmt(r.power*100)}</td><td>${fmt(r.wind_ms)}</td><td>${fmt(r.temperature_c)}</td><td>+${r.horizon_hours} ч</td></tr>`).join('');}
function pin(station,selected=false,custom=false){return L.divIcon({className:'turbine-marker',html:`<div class="map-pin ${selected?'selected':''} ${custom?'custom-pin':''}"><span class="pin-disc">${icon('turbine')}</span><span class="pin-label">${custom?'Новая точка':`ВЭС ${station.id.padStart(2,'0')}`}</span></div>`,iconSize:[84,64],iconAnchor:[42,20]});}
function initMap(){
 if(state.map){state.map.invalidateSize();return;}
 if(typeof L==='undefined'){$('map-error').hidden=false;$('map-error').textContent='Библиотека карты не загрузилась. Выберите ВЭС в списке справа.';return;}
 const map=L.map('map',{zoomControl:false,scrollWheelZoom:false,attributionControl:true});state.map=map;L.control.zoom({position:'topright'}).addTo(map);
 const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',maxZoom:19});let failures=0;tiles.on('tileerror',()=>{if(++failures>2)$('map-error').hidden=false;});tiles.on('tileload',()=>{$('map-error').hidden=true;});tiles.addTo(map);
 for(const s of state.data.turbines){const marker=L.marker([s.latitude,s.longitude],{icon:pin(s),title:s.name,keyboard:true}).addTo(map);marker.on('click',()=>selectStation(s));state.markers.set(s.id,marker);}
 fitMap();
 map.on('click',event=>{let {lat,lng}=event.latlng;lng=((lng+180)%360+360)%360-180;lat=Math.max(-90,Math.min(90,lat));$('latitude').value=lat.toFixed(6);$('longitude').value=lng.toFixed(6);showCustomMarker(lat,lng);toast('Точка выбрана. Нажмите «Рассчитать прогноз».');});
}
function fitMap(){if(!state.map||!state.data)return;state.map.fitBounds(state.data.turbines.map(s=>[s.latitude,s.longitude]),{padding:[65,65],maxZoom:16});}
function updateMarkers(){if(!state.map)return;for(const s of state.data.turbines){state.markers.get(s.id)?.setIcon(pin(s,state.selected.id===s.id));}}
function showCustomMarker(lat,lon){if(!state.map)return;if(state.customMarker)state.customMarker.remove();state.customMarker=L.marker([lat,lon],{icon:pin({id:'custom'},false,true),title:'Новая площадка'}).addTo(state.map);state.customMarker.on('click',()=>{if(state.custom&&Math.abs(state.custom.latitude-lat)<1e-6&&Math.abs(state.custom.longitude-lon)<1e-6)selectStation(state.custom);});}
async function calculate(event){
 event.preventDefault();if(state.busy)return;const form=$('coordinate-form');if(!form.reportValidity())return;
 const latitude=Number($('latitude').value),longitude=Number($('longitude').value);if(!Number.isFinite(latitude)||!Number.isFinite(longitude))return;
 state.busy=true;const button=$('calculate'),status=$('calculation-status');button.disabled=true;button.classList.add('loading');button.querySelector('span').textContent='Выполняем расчёт…';status.classList.remove('error');status.textContent='Архив погоды → модель → 48 часов прогноза';
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),45000);
 try{const data=await request('/api/v1/locations/forecast',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({latitude,longitude,horizon_hours:48,reference_turbine_id:$('reference').value}),signal:controller.signal});state.custom=data;selectStation(data);showCustomMarker(latitude,longitude);state.map?.flyTo([latitude,longitude],12,{duration:.8});status.textContent=`Готово · ${data.forecast.length} часов. Оценка без данных датчиков.`;toast('Сценарий новой площадки рассчитан');if(window.innerWidth<761)$('forecast-panel').scrollIntoView({behavior:'smooth',block:'start'});
 }catch(error){status.classList.add('error');status.textContent=error.name==='AbortError'?'Источник не ответил вовремя. Повторите запрос.':error.message;
 }finally{clearTimeout(timeout);state.busy=false;button.disabled=false;button.classList.remove('loading');button.querySelector('span').textContent='Рассчитать прогноз';}
}
// Keep local wall-clock values from the API; Date would apply the browser's timezone.
function csvDateTime(value){
 const match=String(value??'').match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/);
 if(!match)return [String(value??''),''];
 const [,year,month,day,hour,minute,second='00']=match;
 return [`${day}.${month}.${year}`,`${hour}:${minute}:${second}`];
}
function csvCell(value){
 const text=value==null?'':typeof value==='number'?String(value).replace('.',','):String(value);
 return `"${text.replace(/"/g,'""')}"`;
}
function exportCsv(){
 const rows=visibleRows();if(!rows.length)return;
 const station=state.selected;
 const issued=csvDateTime(station.issue_time??state.data?.issue_time);
 const timezone=station.timezone??state.data?.timezone??'Asia/Almaty';
 const header=['Дата выпуска прогноза','Время выпуска прогноза','Дата прогноза','Время прогноза',
  'Часовой пояс','Турбина или площадка','Идентификатор площадки','Широта, °','Долгота, °',
  'Режим расчёта','Горизонт прогноза, ч','Прогноз мощности, доля от номинала',
  'Скорость ветра, м/с','Температура, °C'];
 const mode=station.mode==='scenario'?'Сценарий новой площадки':'Архивный прогноз';
 const data=rows.map(r=>[...issued,...csvDateTime(r.target_time),timezone,station.name,station.id,
  station.latitude,station.longitude,mode,r.horizon_hours,r.power,r.wind_ms,r.temperature_c]);
 // Semicolons and decimal commas support Russian spreadsheet locale; BOM preserves Cyrillic.
 const csv=[header,...data].map(row=>row.map(csvCell).join(';')).join('\r\n')+'\r\n';
 const link=document.createElement('a');
 const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8;'}));
 link.href=url;link.download=`alem-wind-${station.id}-${state.horizon}h.csv`;
 document.body.append(link);link.click();link.remove();
 setTimeout(()=>URL.revokeObjectURL(url),5000);toast('CSV с датой и временем прогноза выгружен');
}
$('retry').addEventListener('click',load);$('export-top').addEventListener('click',exportCsv);$('fit-map').addEventListener('click',fitMap);$('coordinate-form').addEventListener('submit',calculate);
document.querySelectorAll('[data-horizon]').forEach(button=>button.addEventListener('click',()=>{pause();state.horizon=Number(button.dataset.horizon);document.querySelectorAll('[data-horizon]').forEach(b=>{const active=b===button;b.classList.toggle('active',active);b.setAttribute('aria-pressed',active);});render();}));
document.querySelectorAll('[data-chart]').forEach(button=>button.addEventListener('click',()=>{state.chart=button.dataset.chart;document.querySelectorAll('[data-chart]').forEach(b=>{const active=b===button;b.classList.toggle('active',active);b.setAttribute('aria-pressed',active);});$('chart-tooltip').hidden=true;renderChart();}));
$('forecast-hour').addEventListener('input',event=>{pause();updateCursor(Number(event.target.value));});
$('play-forecast').addEventListener('click',()=>{if(state.timer){pause();return;}if(!visibleRows().length)return;$('play-forecast').textContent='Ⅱ';$('play-forecast').setAttribute('aria-label','Приостановить прогноз');if(state.cursor>=visibleRows().length-1)state.cursor=-1;state.timer=setInterval(()=>{updateCursor(state.cursor+1);if(state.cursor>=visibleRows().length-1)pause();},650);});
$('forecast-chart').addEventListener('pointermove',event=>{if(!chartGeometry)return;const box=$('forecast-chart').getBoundingClientRect();const x=event.clientX-box.left;const index=Math.round((x-chartGeometry.pad.left)/chartGeometry.width*(visibleRows().length-1));updateCursor(index,true);});
$('forecast-chart').addEventListener('pointerleave',()=>$('chart-tooltip').hidden=true);
$('toggle-table').addEventListener('click',()=>{const hidden=!$('hourly-table-wrap').hidden;$('hourly-table-wrap').hidden=hidden;$('toggle-table').setAttribute('aria-expanded',!hidden);$('toggle-table').innerHTML=(hidden?'Показать таблицу':'Скрыть таблицу')+icon('chevron');});
document.querySelectorAll('.rail-link').forEach(link=>link.addEventListener('click',()=>{document.querySelectorAll('.rail-link').forEach(l=>l.classList.toggle('active',l===link));}));
new ResizeObserver(()=>{if(state.selected)renderChart();state.map?.invalidateSize();}).observe($('chart-wrap'));
document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
load();
