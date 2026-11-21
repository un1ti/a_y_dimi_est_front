// Единственная точка интеграции с сервисом анализа PDF.
export async function analyze(request, response) {
  const reply = (status, body) => {
    response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify(body));
  };
  if (!process.env.RAG_ANALYSIS_URL) {
    return reply(503, { error: 'Сервис анализа ещё не подключён. PDF сохранён в библиотеке.' });
  }
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
    const form = new FormData();
    form.append('file', new Blob([file], { type: 'application/pdf' }), 'publication.pdf');
    const headers = {};
    if (process.env.RAG_ANALYSIS_TOKEN) headers.Authorization = 'Bearer ' + process.env.RAG_ANALYSIS_TOKEN;
    const result = await fetch(process.env.RAG_ANALYSIS_URL, {
      method: 'POST', headers, body: form, signal: AbortSignal.timeout(180000), redirect: 'error'
    });
    if (!result.ok) return reply(502, { error: 'Сервис анализа вернул HTTP ' + result.status + '. Можно повторить запрос.' });
    reply(200, await result.json());
  } catch {
    reply(502, { error: 'Не удалось получить результат анализа. Проверьте адрес сервиса и формат ответа.' });
  }
}
