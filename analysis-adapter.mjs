import { createHash } from 'node:crypto';
import { extract } from './scientific-core.mjs';
import { scientificResult } from './scientific-result.mjs';

const running = new Map();
export async function analyze(request, response) {
  const reply = (status, body) => {
    response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify(body));
  };
  try {
    let length = 0;
    const chunks = [];
    for await (const chunk of request) {
      length += chunk.length;
      if (length > 64 * 1024 * 1024) return reply(413, { error: 'Максимальный размер PDF — 64 МБ.' });
      chunks.push(chunk);
    }
    const file = Buffer.concat(chunks);
    if (!file.subarray(0, 1024).includes('%PDF-')) return reply(400, { error: 'Ожидается файл PDF.' });
    const filename = decodeURIComponent(request.headers['x-pdf-filename'] || 'publication.pdf').split(/[\\/]/).pop();
    const digest = createHash('sha256').update(file).digest('hex');
    if (!running.has(digest)) {
      running.set(digest, extract(file, filename).finally(() => running.delete(digest)));
    }
    const extracted = await running.get(digest);
    reply(200, scientificResult(extracted, filename));
  } catch (error) {
    reply(502, { error: 'Не удалось завершить анализ PDF. ' + error.message });
  }
}
