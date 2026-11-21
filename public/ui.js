import {configLabels, issues} from './data.js';
export const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const ico = (name,size=18) => `<svg width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><use href="/icons.svg#${name}"></use></svg>`;
export const uniq = a => [...new Set(a.filter(Boolean))];
export const chip = t => `<span class="chip">${esc(t)}</span>`;
export const btn = (action,label,icon,cls='',extra='')=>`<button class="btn ${cls}" data-a="${action}" ${extra}>${icon?ico(icon,16):''}${esc(label)}</button>`;
export const route = (page,id='')=>'#'+page+(id?'/'+encodeURIComponent(id):'');
export const num = v=>v==null?'—':Number(v).toFixed(3);
export const keys = p=>uniq([p.config.variant,p.task,...p.datasets]);
export const status = p=>p.pending?'Ожидает анализа':issues(p).length?'Есть замечания':'Проверено';
export const badge = p=>`<span class="status ${issues(p).length?'amber':''}">${ico(p.pending?'Clock':issues(p).length?'CircleAlert':'CircleCheck',14)}${status(p)}</span>`;
const kind = p=>p.kind||'PDF';
export function metadata(p){
  return `<div class="meta"><span>${ico('FileText',14)}${esc(kind(p))}</span><span>${ico('CalendarDays',14)}${esc(p.year||'—')}</span><span>${ico('Users',15)}${esc(p.authors||'Авторы не указаны')}</span></div>`;
}
export function chart(papers) {
  const counts = new Map();
  for(const p of papers) if(p.year) counts.set(p.year,(counts.get(p.year)||0)+1);
  const years=[...counts.keys()].sort((a,b)=>a-b);
  if(!years.length)return '<p class="muted">Годы публикаций пока не указаны.</p>';
  let total=0;
  const pts=years.map((y,i)=>{total+=counts.get(y);return {y,x:20+i*360/Math.max(years.length-1,1),n:total};});
  const points=pts.map(p=>[p.x,76-62*p.n/total]);
  const line=points.map(p=>p.join(',')).join(' ');
  return `<svg class="trend" viewBox="0 0 400 96" role="img" aria-label="Количество публикаций нарастающим итогом"><defs><linearGradient id="fill" x1="0" x2="0" y1="0" y2="1"><stop stop-color="#6794f3" stop-opacity=".32"/><stop offset="1" stop-color="#6794f3" stop-opacity=".025"/></linearGradient></defs>${[20,46,74].map(y=>`<path d="M12 ${y}H390" stroke="#dae2ef" stroke-dasharray="3 4"/>`).join('')}<polygon points="${points[0][0]},76 ${line} ${points.at(-1)[0]},76" fill="url(#fill)"/><polyline points="${line}" fill="none" stroke="#3a6bd5" stroke-width="2.6"/>${pts.map((p,i)=>`<g><title>${p.y} · ${p.n}</title><circle cx="${p.x}" cy="${points[i][1]}" r="3.5" fill="white" stroke="#3765c6" stroke-width="2"/><text x="${p.x}" y="93" text-anchor="middle">${p.y}</text></g>`).join('')}</svg>`;
}
export function statCards(papers){
  const items=[['FileText','Публикации',papers.length,'в библиотеке','blue'],['Database','Датасеты',uniq(papers.flatMap(p=>p.datasets)).length,'наборов данных','teal'],['FlaskConical','Методы RAG',uniq(papers.map(p=>p.config.variant)).length,'вариантов систем','violet']];
  return `<section class="stats">${items.map(([ic,t,n,sub,color])=>`<div class="stat box"><span class="stat-icon ${color}">${ico(ic,22)}</span><span class="stat-label">${t}</span><strong>${n}</strong><small>${sub}</small></div>`).join('')}<div class="box chart"><div class="spread"><b>Динамика публикаций</b>${ico('ChartLine',17)}</div>${chart(papers)}</div></section>`;
}
export function configTable(p,linked=false) {
  return `<div class="kv">${Object.entries(configLabels).filter(([k])=>p.config[k]!=null).map(([k,label])=>`<div><span>${label}</span><strong>${esc(p.config[k])} ${linked && p.evidence[k]?`<button class="source" data-a="evidence" data-key="${k}" title="Показать источник">${ico('Crosshair',14)}</button>`:''}</strong></div>`).join('')||'<p class="muted">Конфигурация пока не извлечена.</p>'}</div>`;
}
export function results(p,linked=false){
  if(!p.metrics.length) return '<p class="muted">Результаты появятся после анализа публикации.</p>';
  const sets=uniq(p.metrics.map(m=>m.dataset));
  const metricNames=uniq(p.metrics.map(m=>m.name));
  // A matrix is meaningful only when there is one result per metric and dataset.
  const matrix=sets.length && p.metrics.every(m=>m.dataset && m.unit==='fraction' && m.value!=null) && new Set(p.metrics.map(m=>m.name+'|'+m.dataset)).size===p.metrics.length && uniq(p.metrics.map(m=>m.protocol)).length===1 && uniq(p.metrics.map(m=>m.task)).length===1 && uniq(p.metrics.map(m=>m.config_id)).length===1;
  if(matrix && !linked) return `<div class="table-scroll"><table><thead><tr><th>Метрика</th>${sets.map(d=>`<th>${esc(d)}</th>`).join('')}<th>Среднее</th></tr></thead><tbody>${metricNames.map(n=>{const row=p.metrics.filter(m=>m.name===n);return `<tr><th>${esc(n)}</th>${sets.map(d=>`<td>${num(row.find(m=>m.dataset===d)?.value)}</td>`).join('')}<td class="mean">${num(row.reduce((s,m)=>s+Number(m.value),0)/row.length)}</td></tr>`;}).join('')}</tbody></table></div>`;
  return `<div class="table-scroll"><table><thead><tr><th>Метрика</th><th>Датасет</th><th>Исходное</th><th>Норм.</th><th>Источник</th></tr></thead><tbody>${p.metrics.map((m,i)=>`<tr><th>${esc(m.name)}</th><td>${esc(m.dataset||'—')}</td><td>${esc(m.raw)} ${esc(m.unit)}</td><td>${num(m.value)}</td><td>${m.page?`<button class="source" data-a="metric" data-index="${i}">стр. ${esc(m.page)} ↗</button>`:'—'}</td></tr>`).join('')}</tbody></table></div>`;
}
export function detail(p,tab){
  if(!p)return '<div class="empty">Выберите публикацию из списка.</div>';
  const first=p.metrics[0];
  return `<article class="box article"><div class="spread"><div class="eyebrow"><i></i> КАРТОЧКА ПУБЛИКАЦИИ</div>${badge(p)}</div><h2>${esc(p.title)}</h2>${metadata(p)}<div class="tabs">${['Обзор','Конфигурация RAG','Результаты'].map((t,i)=>`<button class="${tab===i?'active':''}" data-a="tab" data-index="${i}">${t}</button>`).join('')}</div>${tab===0?`<div class="abstract-grid"><section><h3>Аннотация</h3><p>${esc(p.abstract||'Аннотация пока не извлечена.')}</p></section><section class="summary"><h4>Основное</h4>${[['Задача',p.task],['Датасеты',p.datasets.join(', ')],['Генератор',p.config.model]].map(([k,v])=>`<div><span>${k}</span><b>${esc(v||'—')}</b></div>`).join('')}</section></div><div class="divided"><h3>Результаты эксперимента</h3>${results(p)}</div>`:tab===1?`<h3>Конфигурация RAG</h3>${configTable(p)}`:`<h3>Метрики и источники</h3>${results(p,true)}`}<div class="article-foot"><div class="chips">${keys(p).slice(0,3).map(chip).join('')}</div><a class="text-link" href="${route('analysis',p.id)}">Анализ публикации ${ico('ArrowUpRight',15)}</a></div></article>`;
}
export function publicationList(papers,selected,sort){
  return `<section class="box publist"><div class="listhead"><h3>Последние публикации <small>${papers.length}</small></h3><select id="sort" aria-label="Сортировка"><option value="new">Сначала новые</option><option value="old" ${sort==='old'?'selected':''}>Сначала старые</option><option value="title" ${sort==='title'?'selected':''}>По названию</option></select></div><div class="rows">${papers.map(p=>`<button data-a="select" data-id="${esc(p.id)}" class="pubrow ${selected===p.id?'selected':''}"><span class="docicon">${ico('FileText',16)}</span><span><b>${esc(p.title)}</b><small>${esc(p.authors||'Загруженный PDF')} · ${esc(p.year||'—')}</small><em>${esc(p.config.variant||'Ожидает анализа')}</em></span></button>`).join('')||'<div class="empty">Публикаций по этому запросу нет.</div>'}</div></section>`;
}

