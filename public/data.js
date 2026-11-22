const db = await new Promise((resolve, reject) => {
  const request = indexedDB.open('viniti-rag-library', 1);
  request.onupgradeneeded = () => {
    for (const name of ['papers', 'files', 'collections']) request.result.createObjectStore(name);
  };
  request.onsuccess = () => resolve(request.result);
  request.onerror = () => reject(request.error);
});

export function read(store, key) {
  return new Promise((resolve, reject) => {
    const table = db.transaction(store).objectStore(store);
    const req = key === undefined ? table.getAll() : table.get(key);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
export function save(entries) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction([...new Set(entries.map(e => e[0]))], 'readwrite');
    for (const [store, key, value] of entries) tx.objectStore(store).put(value, key);
    tx.oncomplete = resolve;
    tx.onabort = tx.onerror = () => reject(tx.error);
  });
}
export const configLabels = { variant: 'Тип RAG', top_k: 'Top-k (поиск)', chunk_size: 'Размер фрагмента', chunk_overlap: 'Перекрытие фрагментов', embedding: 'Модель эмбеддингов', model: 'Генератор', retrieval: 'Метод поиска' };

export function issues(paper) {
  if (paper.pending) return ['Ожидается результат анализа PDF.'];
  const notes = [];
  const c = paper.config;
  if (c.top_k != null && !(Number.isInteger(Number(c.top_k)) && c.top_k > 0)) notes.push('Top-k должен быть положительным целым числом.');
  if (c.chunk_size != null && !(Number(c.chunk_size) > 0)) notes.push('Размер фрагмента должен быть положительным.');
  if (c.chunk_overlap != null && (c.chunk_overlap < 0 || (c.chunk_size != null && Number(c.chunk_overlap) >= Number(c.chunk_size)))) notes.push('Перекрытие должно быть меньше размера фрагмента.');
  if (!paper.metrics.length) notes.push('У публикации пока нет результатов метрик.');
  for (const m of paper.metrics) {
    const prefix = m.name + ' · ' + (m.dataset || 'датасет неизвестен') + ' · ' + m.id;
    if (!m.dataset || !m.task || !m.protocol || !m.config_id || !m.experiment_id) notes.push(prefix + ' — неполные условия эксперимента.');
    if (!m.fragment || !Number.isInteger(m.page) || m.page < 1 || m.page > paper.pages) notes.push(prefix + ' — проверьте ссылку на источник.');
    if (m.value == null || !Number.isFinite(Number(m.value))) notes.push(prefix + ' — отсутствует нормализованное значение.');
    if (m.unit === 'fraction' && (Number(m.raw) < 0 || Number(m.raw) > 1) || m.unit === '%' && (Number(m.raw) < 0 || Number(m.raw) > 100)) notes.push(prefix + ' — значение выходит за пределы шкалы.');
    if (/^(Recall|MRR|Precision|NDCG)@/i.test(m.name) && !/@[1-9]\d*$/i.test(m.name)) notes.push(prefix + ' — некорректное значение k.');
  }
  return notes;
}
export function acceptResult(input, paper) {
  if (!input || typeof input.title !== 'string' || !input.title.trim() || !Array.isArray(input.metrics) || !Array.isArray(input.datasets)) throw Error('В ответе сервиса ожидаются title, datasets и metrics.');
  const str = v => typeof v === 'string' ? v : '';
  const config = Object.fromEntries(Object.entries(input.config || {}).filter(([key,v]) => (Object.hasOwn(configLabels, key) || ['chunk_unit', 'top_k_unit'].includes(key)) && ['string','number'].includes(typeof v)));
  const evidence = {};
  for (const [key, e] of Object.entries(input.evidence || {})) {
    if (key in configLabels && e && Number.isInteger(e.page) && typeof e.fragment === 'string') evidence[key] = { page:e.page, fragment:e.fragment };
  }
  const metrics = input.metrics.map((m, index) => {
    if (!m || typeof m.name !== 'string' || !['string','number'].includes(typeof m.raw)) throw Error('Для каждой метрики требуются name и raw.');
    const rawNumber = Number(String(m.raw).replace(',', '.'));
    const normalized = m.value ?? (Number.isFinite(rawNumber) && String(m.raw).trim() ? (m.unit === '%' ? rawNumber / 100 : m.unit === 'fraction' ? rawNumber : null) : null);
    return { ...m, id: str(m.id) || paper.id + '-m' + (index+1), name:m.name, raw:String(m.raw), unit:str(m.unit), value:normalized == null || !Number.isFinite(Number(normalized)) ? null : Number(normalized), page:Number(m.page), fragment:str(m.fragment), dataset:str(m.dataset), task:str(m.task), protocol:str(m.protocol), experiment_id:str(m.experiment_id), config_id:str(m.config_id), origin:str(m.origin) || 'unknown' };
  });
  return { ...paper, scientific:input.scientific, title:input.title, authors:str(input.authors), year:Number(input.year)||null, kind:str(input.kind), abstract:str(input.abstract), protocol:str(input.protocol), task:str(input.task), datasets:input.datasets.filter(d=>typeof d==='string'), config, evidence, metrics, pending:false };
}
export async function library() {
  const examples = await fetch('/examples/library.json').then(r => r.json());
  return [...await read('papers'), ...examples];
}

