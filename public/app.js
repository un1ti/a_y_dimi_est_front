import {read,save,library,issues,acceptResult} from './data.js';
import {esc,ico,btn,route,chip,keys,statCards,detail,publicationList} from './ui.js';
import {catalog,experiments,values,analysis,comparison} from './pages.js';
import {openPdf,paint} from './viewer.js';

const $=q=>document.querySelector(q);
const state={view:'overview',id:'',selected:'',q:'',sort:'new',tab:0,filters:{},row:'',compare:new Set(),page:1,pdfPage:1,zoom:1,fragment:'',collection:''};
const titles={overview:'Обзор исследований RAG',experiments:'Каталог экспериментов',collections:'Коллекции',analysis:'Анализ публикации'};
let papers=[],collections=[],connected=false,toastTimer;
const main=$('#main'),modal=$('#modal');
const active=()=>papers.find(p=>p.id===state.id);
const visible=()=>papers.filter(p=>[p.title,p.authors,p.year,p.task,...keys(p),...Object.values(p.config),...p.metrics.map(m=>m.name)].join(' ').toLowerCase().includes(state.q.toLowerCase().trim()));
function notify(t){$('#notice').textContent=t;$('#notice').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#notice').classList.remove('show'),4500);}
function dialog(title,content,wide=false){
  if(modal.open)modal.close();
  modal.className=wide?'wide':'';
  modal.innerHTML=`<div class="dialoghead"><h2>${esc(title)}</h2>${btn('close','','X','icon','aria-label="Закрыть"')}</div>${content}`;
  modal.showModal();
}
function go(view,id=''){location.hash=route(view,id);}
function header(){
  $('#header').innerHTML=`<div class="top"><a href="#overview" class="brand"><span class="mark">${ico('Layers3',26)}</span><span>RAG <b>Research Analyzer</b></span></a><nav>${[['overview','Обзор'],['experiments','Исследования'],['collections','Коллекции']].map(([k,t])=>`<a class="${state.view===k||k==='experiments'&&state.view==='analysis'?'on':''}" href="${route(k)}">${t}</a>`).join('')}</nav><label class="search">${ico('Search',16)}<input id="query" type="search" value="${esc(state.q)}" placeholder="Поиск по библиотеке" aria-label="Поиск по публикациям, методам и метрикам"><kbd>Ctrl K</kbd></label><span class="avatar" title="Локальное рабочее пространство">R</span></div>`;
}
function body(){
  const p=active();
  const view=state.view;
  document.title=titles[view]+' · RAG Research Analyzer';
  const subs={overview:'Анализ научных публикаций по Retrieval-Augmented Generation',experiments:'Конфигурации, метрики и условия оценки RAG-систем',collections:'Тематические подборки публикаций из вашей библиотеки',analysis:p?.file||''};
  let actions=btn('upload','Загрузить PDF','Upload','primary');
  if(view==='analysis'&&p)actions=(p.pending?btn('analyze','Анализировать','FlaskConical','primary'):btn('validate','Проверить','ShieldCheck','primary'))+btn('export','Экспорт','Download');
  if(view==='collections')actions=btn('newCollection','Создать коллекцию','Plus','primary');
  main.innerHTML=`<div class="crumb">${ico('Layers3',14)} Рабочее пространство ${ico('ChevronRight',12)} <span>${({overview:'Обзор',experiments:'Исследования',collections:'Коллекции',analysis:'Исследования / Анализ'})[view]}</span></div><div class="heading"><div>${view==='analysis'?'<a class="text-link" href="#experiments">← К экспериментам</a>':''}<h1>${titles[view]}</h1><p>${esc(subs[view])}</p></div><div class="actions">${actions}</div></div><div id="content"></div>`;
  content();
}
function content(){
  const target=$('#content'), found=visible();
  if(state.view==='overview'){
    const sorted=found.slice().sort((a,b)=> state.sort==='title'?a.title.localeCompare(b.title):state.sort==='old'?(a.year||9999)-(b.year||9999):(b.year||9999)-(a.year||9999));
    const selected=sorted.find(p=>p.id===state.selected)||sorted[0];
    state.selected=selected?.id||'';
    target.innerHTML=statCards(papers)+`<div class="sectionhead"><div>${ico('Library',19)}<h2>Библиотека исследований</h2></div><span>${papers.filter(p=>p.demo).length} демопримеров · ${papers.filter(p=>!p.demo).length} загружено</span></div><div class="overview">${publicationList(sorted,state.selected,state.sort)}${detail(selected,state.tab)}</div>`;
  } else if(state.view==='experiments'){
    const all=experiments(papers),allowed=new Set(found.map(p=>p.id));
    const rows=all.filter(r=>allowed.has(r.p.id)&&Object.entries(state.filters).every(([k,list])=>!list.length||values(r,k,collections).some(v=>list.includes(v))));
    target.innerHTML=catalog(all,rows,state,collections);
  } else if(state.view==='analysis'){
    const p=active();
    target.innerHTML=p?analysis(p,state):'<p class="empty">Публикация не найдена. <a href="#overview">Открыть библиотеку</a></p>';
    if(p)paint(p,state.pdfPage,state.zoom,state.fragment);
  } else {
    const current=collections.find(c=>c.id===state.collection)||collections[0];
    state.collection=current?.id||'';
    target.innerHTML=`<div class="collections"><section class="box"><h3>Мои коллекции</h3>${collections.map(c=>`<button class="collection ${c===current?'picked':''}" data-a="collection" data-id="${esc(c.id)}">${ico('Folder')}<b>${esc(c.name)}</b><small>${c.ids.length}</small></button>`).join('')||'<p>Создайте первую тематическую подборку.</p>'}</section><section class="box"><div class="spread"><h3>${esc(current?.name||'Публикации')}</h3>${current?btn('members','Выбрать публикации','Plus','subtle'):''}</div>${found.filter(p=>current?.ids.includes(p.id)).map(p=>`<a class="collectionpaper" href="${route('analysis',p.id)}">${ico('FileText')}<span>${esc(p.title)}</span>${ico('ArrowUpRight',15)}</a>`).join('')||'<p class="empty">В этой подборке пока нет публикаций по выбранным условиям.</p>'}</section></div>`;
  }
}
function navigate(){
  const [view,id]=location.hash.slice(1).split('/');
  state.view=Object.hasOwn(titles,view)?view:'overview';
  state.id=id?decodeURIComponent(id):'';
  if(state.view==='analysis'){state.pdfPage=1;state.zoom=1;state.fragment='';}
  header();body();
}
function upload(){
  dialog('Загрузить публикацию',`<form id="uploadform"><p>Добавьте PDF в локальную библиотеку. Для извлечения данных используется подключаемый сервис анализа.</p><label class="drop">${ico('Upload',28)}<strong>Выберите PDF-файл</strong><span>До 64 МБ</span><input id="uploadfile" type="file" accept=".pdf,application/pdf" required></label><label class="field">Название в библиотеке<input name="title" placeholder="По умолчанию — имя файла" maxlength="500"></label><p class="formerr" role="alert"></p><div class="dialogactions">${btn('close','Отмена','','subtle','type="button"')}<button class="btn primary" type="submit">Добавить в библиотеку</button></div></form>`);
}
async function addPaper(form){
  const file=$('#uploadfile').files[0];
  if(!file || file.size>64*1024*1024)throw Error('Выберите PDF размером до 64 МБ.');
  let pdf;
  try{pdf=await openPdf({data:await file.arrayBuffer()});}catch{throw Error('Не удалось открыть PDF. Проверьте формат и защиту паролем.');}
  const pages=pdf.numPages;
  await pdf.destroy();
  const id=crypto.randomUUID();
  const p={id,title:form.elements.title.value.trim()||file.name.replace(/\.pdf$/i,''),authors:'',year:null,kind:'PDF',abstract:'',config:{},datasets:[],task:'',protocol:'',metrics:[],evidence:{},file:file.name,pages,pending:true,demo:false};
  await save([['papers',id,p],['files',id,file]]);
  papers.unshift(p); state.selected=id;state.q='';modal.close();go('analysis',id);notify('PDF добавлен в библиотеку');
}
const processing=new Set();
async function runAnalysis(){
  const p=active();
  if(!p||processing.has(p.id))return;
  if(!connected){dialog('Подключение нейросети','<p>PDF сохранён. Для запуска анализа укажите адрес готового сервиса в переменной RAG_ANALYSIS_URL и перезапустите сервер сайта.</p>');return;}
  processing.add(p.id);notify('PDF передан на анализ…');
  try{
    const res=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/pdf'},body:await read('files',p.id)});
    const result=await res.json();
    if(!res.ok)throw Error(result.error||'Ошибка сервиса анализа.');
    const next=acceptResult(result,p);
    await save([['papers',next.id,next]]);papers[papers.findIndex(x=>x.id===p.id)]=next;
    body();notify('Результаты анализа сохранены');
  }finally{processing.delete(p.id);}
}
function exportFile(p,type){
  let data=JSON.stringify({...p,validation:issues(p)},null,2);
  if(type==='csv'){
    const cols=['id','experiment_id','config_id','task','dataset','protocol','name','raw','unit','value','page','fragment','origin'];
    const cell=v=>'"'+String(v??'').replaceAll('"','""')+'"';
    data='\uFEFF'+[['publication_id',...cols],...p.metrics.map(m=>[p.id,...cols.map(k=>m[k])])].map(row=>row.map(cell).join(',')).join('\r\n');
  }
  const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([data],{type:type==='csv'?'text/csv;charset=utf-8':'application/json'}));link.download=p.id+'.'+type;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),2000);modal.close();
}
function showSource(e,p){
  if(!e)return;
  const show=()=>{state.pdfPage=Math.max(1,Math.min(p.pages,Number(e.page)||1));state.fragment=e.fragment||'';content();};
  if(state.view!=='analysis'){window.addEventListener('hashchange',show,{once:true});go('analysis',p.id);}else show();
}
document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-a]');if(!b)return;
  const {a,id,key,index}=b.dataset;
  try{
    switch(a){
      case 'close':modal.close();return;
      case 'upload':upload();return;
      case 'select':state.selected=id;state.tab=0;break;
      case 'tab':state.tab=Number(index);break;
      case 'row':state.row=key;break;
      case 'clear':state.filters={};state.q='';state.page=1;header();break;
      case 'prev':state.page--;break;
      case 'next':state.page++;break;
      case 'compare':dialog('Сравнение экспериментов',comparison(experiments(papers).filter(r=>state.compare.has(r.key))),true);return;
      case 'pdfprev':case 'pdfnext':state.pdfPage+=a==='pdfnext'?1:-1;state.fragment='';break;
      case 'minus':case 'plus':state.zoom=Math.max(.5,Math.min(2,state.zoom+(a==='plus'?.25:-.25)));break;
      case 'metric':{const p=active()||papers.find(x=>x.id===state.selected);showSource(p.metrics[Number(index)],p);return;}
      case 'evidence':showSource(active().evidence[key],active());return;
      case 'validate':{const notes=issues(active());dialog('Проверка данных',notes.length?notes.map(n=>`<p>${esc(n)}</p>`).join(''):'<p class="good">Проверки пройдены. Параметры конфигурации согласованы, у значений метрик указаны эксперимент и источник.</p>');return;}
      case 'analyze':await runAnalysis();return;
      case 'export':dialog('Экспорт результатов',`<p>JSON содержит карточку, связи, источники и замечания. CSV содержит строки метрик.</p><div class="dialogactions">${btn('json','Скачать JSON','Download','primary')}${btn('csv','Скачать CSV','Download')}</div>`);return;
      case 'csv':case 'json':exportFile(active(),a);return;
      case 'collection':state.collection=id;break;
      case 'newCollection':dialog('Новая коллекция','<form id="collectionform"><label class="field">Название<input name="name" required maxlength="100" autofocus></label><p class="formerr"></p><button class="btn primary">Создать</button></form>');return;
      case 'members':{const c=collections.find(x=>x.id===state.collection);dialog('Состав коллекции',`<form id="membersform"><div class="memberlist">${papers.map(p=>`<label><input type="checkbox" name="member" value="${esc(p.id)}" ${c.ids.includes(p.id)?'checked':''}>${esc(p.title)}</label>`).join('')}</div><p class="formerr"></p><button class="btn primary">Сохранить</button></form>`);return;}
    }
    content();
  }catch(err){notify(err.message);}
});
document.addEventListener('submit',async event=>{
  const f=event.target;event.preventDefault();const button=f.querySelector('[type=submit],button.primary');button.disabled=true;
  try{
    if(f.id==='uploadform'){await addPaper(f);return;}
    let c;
    if(f.id==='collectionform'){
      const name=f.elements.name.value.trim();if(!name||collections.some(x=>x.name===name))throw Error('Введите уникальное название.');
      c={id:crypto.randomUUID(),name,ids:[]};
    }else{
      c={...collections.find(x=>x.id===state.collection),ids:new FormData(f).getAll('member')};
    }
    await save([['collections',c.id,c]]);collections=await read('collections');state.collection=c.id;modal.close();content();
  }catch(e){f.querySelector('.formerr').textContent=e.message;}finally{button.disabled=false;}
});
document.addEventListener('input',e=>{
  if(e.target.id==='query'){
    state.q=e.target.value;state.page=1;
    if(state.view==='analysis'){state.view='overview';location.hash='overview';}
    content();
  }
});
document.addEventListener('change',e=>{
  const el=e.target;
  if(el.id==='sort')state.sort=el.value;
  else if(el.id==='pageNumber'){state.pdfPage=Math.max(1,Math.min(active().pages,parseInt(el.value,10)||1));state.fragment='';}
  else if(el.dataset.filter){const k=el.dataset.filter;let set=new Set(state.filters[k]||[]);el.checked?set.add(el.value):set.delete(el.value);state.filters[k]=[...set];state.page=1;}
  else if(el.dataset.compare){el.checked?state.compare.add(el.dataset.compare):state.compare.delete(el.dataset.compare);}
  else return;
  content();
});
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();$('#query')?.focus();}});
window.addEventListener('hashchange',navigate);
try{
  [papers,collections]=await Promise.all([library(),read('collections')]);
  const initialized=await read('collections','benchmarks');
  if(!initialized){const c={id:'benchmarks',name:'RAG-бенчмарки',ids:['demo-1','demo-2','demo-4']};await save([['collections',c.id,c]]);collections.push(c);}
  connected=await fetch('/api/status').then(r=>r.json()).then(s=>s.connected).catch(()=>false);
  navigate();
}catch(e){main.textContent='Не удалось открыть локальную библиотеку. Разрешите хранилище сайта и обновите страницу. '+e.message;}

