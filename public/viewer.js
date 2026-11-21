import { read } from './data.js';

let loaded, currentKey, serial = 0;
async function library() {
  const pdfjs = await import('./vendor/pdfjs/pdf.min.mjs');
  pdfjs.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/pdf.worker.min.mjs';
  return pdfjs;
}
export async function openPdf(source) {
  const pdfjs = await library();
  return pdfjs.getDocument({ ...source, standardFontDataUrl:'/vendor/pdfjs/standard_fonts/', cMapUrl:'/vendor/pdfjs/cmaps/', cMapPacked:true, wasmUrl:'/vendor/pdfjs/wasm/', iccUrl:'/vendor/pdfjs/iccs/', isEvalSupported:false }).promise;
}
export async function paint(paper, pageNo, zoom, fragment) {
  const seq = ++serial;
  const container = document.querySelector('#sheet');
  if (!container) return;
  try {
    if (paper.id !== currentKey) {
      currentKey = paper.id;
      const old = loaded;
      loaded = paper.demo ? openPdf({url:'/examples/' + paper.file}) : read('files', paper.id).then(async file => openPdf({data:await file.arrayBuffer()}));
      old?.then(doc => doc.destroy()).catch(()=>{});
    }
    const doc = await loaded;
    const page = await doc.getPage(pageNo);
    const natural = page.getViewport({scale:1});
    if (seq !== serial || !container.isConnected) return;
    const width = Math.max(260, container.parentElement.clientWidth-32) * zoom;
    const viewport = page.getViewport({scale:width / natural.width});
    const density = Math.min(window.devicePixelRatio || 1, 2);
    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(viewport.width*density);
    canvas.height = Math.ceil(viewport.height*density);
    canvas.style.width = viewport.width + 'px';
    canvas.style.height = viewport.height + 'px';
    canvas.setAttribute('aria-label','Страница ' + pageNo + ' публикации');
    const ctx = canvas.getContext('2d');
    await page.render({canvasContext:ctx, viewport, transform:[density,0,0,density,0,0]}).promise;
    if (fragment) {
      const text = await page.getTextContent();
      const norm = s => s.trim().replace(/\s+/g,' ').toLowerCase();
      const words = text.items.filter(x => x.str && x.str.trim());
      const full = words.map(x=>norm(x.str)).join(' ');
      const match = full.indexOf(norm(fragment));
      if (match >= 0) {
        let pos = 0;
        ctx.fillStyle = 'rgba(255,201,39,.35)';
        for (const item of words) {
          const end = pos + norm(item.str).length;
          if (pos < match + norm(fragment).length && end > match) {
            const [x,y] = viewport.convertToViewportPoint(item.transform[4], item.transform[5]);
            const h = item.height*viewport.scale;
            ctx.fillRect(x*density,(y-h)*density,item.width*viewport.scale*density,h*1.24*density);
          }
          pos = end+1;
        }
      }
    }
    if (seq === serial && container.isConnected) container.replaceChildren(canvas);
  } catch {
    if(seq === serial && container.isConnected) container.textContent = 'Не удалось отобразить эту страницу PDF.';
  }
}
