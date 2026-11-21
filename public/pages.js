import {esc,ico,btn,chip,badge,uniq,configTable,results,metadata,num,route} from './ui.js';
import {issues} from './data.js';
export function experiments(papers){
  const rows=[];
  for(const p of papers){
    const grouped=new Map();
    for(const m of p.metrics){
      const k=JSON.stringify([m.experiment_id,m.config_id,m.dataset,m.task,m.protocol]);
      if(!grouped.has(k)) grouped.set(k,[]);
      grouped.get(k).push(m);
    }
    for(const [k,ms] of grouped) rows.push({key:p.id+'|'+k,p,ms,dataset:ms[0].dataset,task:ms[0].task,protocol:ms[0].protocol});
  }
  return rows;
}
export const filters={task:'Задача',variant:'Тип RAG',dataset:'Датасет',model:'Модель',metric:'Метрика',year:'Год',collection:'Коллекция'};
export function values(row,k,collections){
  if(k==='collection') return collections.filter(c=>c.ids.includes(row.p.id)).map(c=>c.name);
  if(k==='metric') return uniq(row.ms.map(m=>m.name));
  return [String(row[k] || row.p.config[k] || row.p[k] || '')].filter(Boolean);
}
export const options=(items,val)=>items.map(x=>`<option value="${esc(x)}" ${x===val?'selected':''}>${esc(x)}</option>`).join('');
export function catalog(all,rows,s,collections){
  const pageSize=7, pages=Math.max(1,Math.ceil(rows.length/pageSize));
  s.page=Math.min(s.page,pages);
  const current=rows.slice((s.page-1)*pageSize,s.page*pageSize);
  const row=rows.find(r=>r.key===s.row)||current[0];
  const side=Object.entries(filters).map(([k,label])=>{
    const choices=uniq(all.flatMap(r=>values(r,k,collections))).sort();
    return choices.length?`<details ${['task','variant','dataset'].includes(k)||s.filters[k]?.length?'open':''}><summary>${label}</summary>${choices.map(v=>`<label class="filter"><input type="checkbox" data-filter="${k}" value="${esc(v)}" ${s.filters[k]?.includes(v)?'checked':''}><span>${esc(v)}</span><small>${all.filter(r=>values(r,k,collections).includes(v)).length}</small></label>`).join('')}</details>`:'';
  }).join('');
  return `<div class="catalog"><aside class="box facet"><h3>${ico('ListFilter')} Фильтры</h3>${side}${btn('clear','Сбросить фильтры','','subtle')}</aside><section class="box experiments"><div class="spread"><h3>Эксперименты <small>${rows.length}</small></h3>${btn('compare','Сравнить ('+s.compare.size+')','GitCompareArrows','subtle',s.compare.size<2?'disabled':'')}</div><div class="table-scroll"><table><thead><tr><th></th><th>Публикация / модель</th><th>Датасет</th><th>Метрика</th><th>Значение</th></tr></thead><tbody>${current.map(r=>`<tr class="${r===row?'picked':''}"><td><input type="checkbox" aria-label="Выбрать для сравнения" data-compare="${esc(r.key)}" ${s.compare.has(r.key)?'checked':''}></td><td><button class="rowtitle" data-a="row" data-key="${esc(r.key)}">${esc(r.p.title)}</button><small>${esc(r.p.config.model||'—')} · ${esc(r.p.year||'—')}</small></td><td>${esc(r.dataset||'—')}</td><td>${esc(r.ms[0].name)}</td><td>${num(r.ms[0].value)}</td></tr>`).join('')}</tbody></table></div>${rows.length?'':'<p class="empty">Нет экспериментов по выбранным условиям.</p>'}<div class="pager"><span>Страница ${s.page} из ${pages}</span>${btn('prev','Назад','ChevronLeft','subtle',s.page===1?'disabled':'')}${btn('next','Далее','ChevronRight','subtle',s.page>=pages?'disabled':'')}</div></section><aside class="box inspector">${row?`<div class="eyebrow"><i></i> ЭКСПЕРИМЕНТ</div><h3>${esc(row.p.title)}</h3>${badge(row.p)}<div class="divided"><h4>Конфигурация</h4><p>${esc(row.p.config.model||'—')} · ${esc(row.p.config.variant||'—')}</p><div class="chips">${[row.task,row.dataset].filter(Boolean).map(chip).join('')}</div><p class="muted">${esc(row.protocol||'Протокол не указан')}</p></div><h4>Метрики</h4>${row.ms.map(m=>`<div class="metricbar"><div><span>${esc(m.name)}</span><b>${num(m.value)}</b></div>${['fraction','%'].includes(m.unit)?`<i style="width:${Math.min(100,Math.max(0,Number(m.value)*100))}%"></i>`:''}</div>`).join('')}<a class="btn primary" href="${route('analysis',row.p.id)}">${ico('FileSearch',16)} Открыть PDF</a>`:'Выберите эксперимент.'}</aside></div>`;
}
export function analysis(p,s){
  const notes=issues(p);
  return `<div class="analysis"><section class="box pdfbox"><div class="pdfbar"><b>${ico('FileText',16)} PDF</b>${btn('pdfprev','','ChevronLeft','icon',`aria-label="Предыдущая страница" ${s.pdfPage===1?'disabled':''}`)}<label><input id="pageNumber" type="number" min="1" max="${p.pages}" value="${s.pdfPage}" aria-label="Страница PDF"> / ${p.pages}</label>${btn('pdfnext','','ChevronRight','icon',`aria-label="Следующая страница" ${s.pdfPage===p.pages?'disabled':''}`)}<span class="spacer"></span>${btn('minus','','Minus','icon','aria-label="Уменьшить масштаб"')}<small>${Math.round(s.zoom*100)}%</small>${btn('plus','','Plus','icon','aria-label="Увеличить масштаб"')}</div><div class="paper-scroll"><div id="sheet">Загрузка страницы…</div></div>${s.fragment?`<div class="quote">${ico('Quote',16)} <span>${esc(s.fragment)}</span></div>`:''}</section><div class="extract"><section class="box"><div class="spread"><h3>${ico('FileText')} Публикация</h3>${badge(p)}</div><h4>${esc(p.title)}</h4>${metadata(p)}</section><section class="box"><h3>${ico('Settings2')} Конфигурация RAG</h3>${configTable(p,true)}</section><section class="box"><h3>${ico('FlaskConical')} Эксперимент</h3><div class="chips">${[p.task,...p.datasets].filter(Boolean).map(chip).join('')}</div><p>${esc(p.protocol||'Протокол пока не указан.')}</p></section><section class="box"><h3>${ico('ChartNoAxesColumnIncreasing')} Метрики</h3>${results(p,true)}</section><section class="box"><h3>${ico('ShieldCheck')} Проверка и валидация</h3>${notes.length?notes.map(n=>`<p class="warning">${ico('CircleAlert',15)} ${esc(n)}</p>`).join(''):'<p class="good">Проверены параметры конфигурации, шкалы метрик и ссылки на источники.</p>'}</section></div></div>`;
}
export function comparison(rows) {
  const names=uniq(rows.flatMap(r=>r.ms.map(m=>m.name)));
  return `<div class="table-scroll"><table><thead><tr><th>Метрика</th>${rows.map(r=>`<th>${esc(r.p.title)}<small>${esc(r.dataset)} · ${esc(r.protocol)}</small></th>`).join('')}<th>Условия</th></tr></thead><tbody>${names.map(name=>{
    const groups=rows.map(r=>r.ms.filter(m=>m.name===name)),ms=groups.map(g=>g[0]);
    const ok=groups.every(g=>g.length===1) && ms.every(m=>m.task && m.dataset && m.protocol && m.value!=null && m.unit && ['fraction','%'].includes(m.unit) && (m.origin==='primary')) && uniq(ms.map(m=>JSON.stringify([m.task,m.dataset,m.protocol,m.name,m.metric_variant||'',m.metric_direction||'',m.metric_k||'',m.aggregation||'']))).length===1;
    return `<tr><th>${esc(name)}</th>${groups.map(g=>`<td>${g.length?g.map(m=>num(m.value)).join(' / '):'—'}</td>`).join('')}<td>${ok?'Сопоставимы':'Требуют проверки'}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}

