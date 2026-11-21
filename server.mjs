import http from 'node:http';
import { analyze } from './analysis-adapter.mjs';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('./public/', import.meta.url));
const port = Number(process.env.PORT || 4173);
const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.pdf': 'application/pdf', '.svg': 'image/svg+xml', '.wasm': 'application/wasm' };
const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/api/status') {
      res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ connected: Boolean(process.env.RAG_ANALYSIS_URL) }));
      return;
    }
    if (url.pathname === '/api/analyze' && req.method === 'POST') {
      if (req.headers.origin && req.headers.origin !== 'http://' + req.headers.host) {
        res.writeHead(403).end();
        return;
      }
      return await analyze(req, res);
    }
    const name = decodeURIComponent(url.pathname);
    const file = path.resolve(root, '.' + (name === '/' ? '/index.html' : name));
    if (!file.startsWith(path.resolve(root) + path.sep) || !(await stat(file)).isFile()) throw Error();
    res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream', 'X-Content-Type-Options': 'nosniff' });
    createReadStream(file).on('error', () => res.destroy()).pipe(res);
  } catch {
    res.writeHead(404).end('Файл не найден');
  }
});
server.on('error', err => { console.error(err.message); process.exitCode = 1; });
server.listen(port, '127.0.0.1', () => console.log('RAG Research Analyzer  http://127.0.0.1:' + port));

