import http from 'node:http';
import { analyze } from './analysis-adapter.mjs';
import { createPaper, updatePaper, getPapers, getPdf, getCollections, saveCollection } from './database.mjs';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('./public/', import.meta.url));
const port = Number(process.env.PORT || 4173);
const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.pdf': 'application/pdf', '.svg': 'image/svg+xml', '.wasm': 'application/wasm' };
function json(res, status, value) {
  res.writeHead(status, {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'}).end(JSON.stringify(value));
}
async function body(req, limit) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw Object.assign(Error('Превышен допустимый размер запроса.'), {status:413});
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}
const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname.startsWith('/api/')) {
      if (req.headers.origin && req.headers.origin !== 'http://' + req.headers.host) {
        return json(res,403,{error:'Запрос отклонён.'});
      }
      if (url.pathname === '/api/status') return json(res,200,{connected:true,engine:'scientific-v2.5',database:'SQLite'});
      if (url.pathname === '/api/analyze' && req.method === 'POST') return await analyze(req,res);
      if (url.pathname === '/api/library' && req.method === 'GET') return json(res,200,{papers:getPapers(),collections:getCollections()});
      const fileRoute = /^\/api\/files\/([a-zA-Z0-9_-]{1,80})$/.exec(url.pathname);
      if (fileRoute && req.method === 'GET') {
        const item = getPdf(fileRoute[1]);
        if (!item) return json(res,404,{error:'PDF не найден.'});
        res.writeHead(200,{'Content-Type':'application/pdf','Content-Length':(await stat(item.file)).size});
        return createReadStream(item.file).on('error',()=>res.destroy()).pipe(res);
      }
      if (fileRoute && req.method === 'POST') {
        const buffer = await body(req,64*1024*1024);
        if (!buffer.subarray(0,1024).includes('%PDF-')) return json(res,400,{error:'Ожидается PDF-файл.'});
        const file = decodeURIComponent(req.headers['x-file-name'] || 'publication.pdf');
        const pages = Number(req.headers['x-page-count']);
        if (!Number.isInteger(pages) || pages < 1) return json(res,400,{error:'Некорректное число страниц.'});
        const paper = {id:fileRoute[1],file,pages,title:decodeURIComponent(req.headers['x-paper-title'] || '') || file.replace(/\.pdf$/i,''),
          authors:'',year:null,kind:'PDF',abstract:'',config:{},datasets:[],task:'',protocol:'',metrics:[],evidence:{},pending:true,demo:false};
        createPaper(paper,buffer);
        return json(res,201,paper);
      }
      if (url.pathname === '/api/papers' && req.method === 'POST') {
        updatePaper(JSON.parse(await body(req,64*1024*1024)));
        return json(res,200,{ok:true});
      }
      if (url.pathname === '/api/collections' && req.method === 'POST') {
        saveCollection(JSON.parse(await body(req,1024*1024)));
        return json(res,200,{ok:true});
      }
      return json(res,404,{error:'Маршрут API не найден.'});
    }
    const name = decodeURIComponent(url.pathname);
    const file = path.resolve(root, '.' + (name === '/' ? '/index.html' : name));
    if (!file.startsWith(path.resolve(root) + path.sep) || !(await stat(file)).isFile()) throw Error();
    res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream', 'X-Content-Type-Options': 'nosniff' });
    createReadStream(file).on('error', () => res.destroy()).pipe(res);
  } catch (err) {
    if (req.url.startsWith('/api/')) return json(res,err.status || 400,{error:err.message});
    res.writeHead(404).end('Файл не найден');
  }
});
server.on('error', err => { console.error(err.message); process.exitCode = 1; });
server.listen(port, '127.0.0.1', () => console.log('RAG Research Analyzer  http://127.0.0.1:' + server.address().port));

