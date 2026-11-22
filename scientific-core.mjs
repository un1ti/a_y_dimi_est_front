import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { setTimeout as sleep } from 'node:timers/promises';

const backend = './Scientific_Arbitrator_FULL_BACKEND_v2.5_FRONTEND_HANDOFF/backend/';
const runtime = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
const python = fileURLToPath(new URL(backend + runtime, import.meta.url));
let startup;

function start() {
  if (!existsSync(python)) throw Error('Установите зависимости Python в backend/.venv по инструкции из README.');
  const worker = spawn(python, [fileURLToPath(new URL('./start-core.py', import.meta.url))], {
    windowsHide: true, stdio: ['pipe', 'pipe', 'inherit'], env: { ...process.env, PYTHONUTF8: '1' }
  });
  const lines = createInterface({input:worker.stdout});
  return new Promise((resolve,reject) => {
    const timer = setTimeout(() => worker.kill(), 30000);
    lines.on('line', line => {
      const match = /^RAG_PORT=(\d+)$/.exec(line);
      if (match) {
        clearTimeout(timer);
        resolve('http://127.0.0.1:' + match[1] + '/api/v1');
      }
    });
    function stopped() {
      clearTimeout(timer);
      startup = undefined;
      reject(Error('Ядро v2.5 не запустилось. Проверьте зависимости backend и сообщения Python в консоли.'));
    }
    worker.once('error', stopped);
    worker.once('exit', stopped);
  });
}

async function api(base, path, options) {
  const response = await fetch(base + path, { signal:AbortSignal.timeout(180000), ...options });
  const body = await response.json();
  if (!response.ok) {
    const message = typeof body.detail === 'string' ? body.detail : 'HTTP ' + response.status;
    throw Error(message.includes('no extractable text') ? 'PDF без текстового слоя. Для анализа требуется OCR.' : message);
  }
  return body;
}

export async function extract(file, filename) {
  startup ??= start();
  const base = await startup;
  const form = new FormData();
  form.append('domain','rag');
  form.append('file',new Blob([file], {type:'application/pdf'}),filename);
  const doc = await api(base,'/documents',{method:'POST',body:form});
  let job = await api(base,'/documents/' + doc.id + '/analyze',{method:'POST'});
  const deadline = Date.now() + 10 * 60 * 1000;
  while (job.status === 'queued' || job.status === 'running') {
    if (Date.now() >= deadline) throw Error('Истекло время ожидания результата ядра v2.5.');
    await sleep(550);
    job = await api(base,'/jobs/' + job.id);
  }
  if (job.status !== 'done') throw Error(job.error || 'Анализ PDF завершился ошибкой.');
  const [result,quality] = await Promise.all([
    api(base,'/documents/' + doc.id + '/results'),
    api(base,'/scientific/quality/' + doc.id + '?limit=1000')
  ]);
  if (result.latest_job?.id !== job.id) throw Error('У документа уже есть новый запуск анализа. Повторите запрос.');
  return {doc,job,records:result.records,quality};
}
