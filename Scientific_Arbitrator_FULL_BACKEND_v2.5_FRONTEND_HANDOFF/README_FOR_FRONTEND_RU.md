# The Scientific Arbitrator: передача backend v2.5 фронтенд-команде

## Состав архива
- `backend/`: полный доступный в рабочей проверочной сборке Python/FastAPI backend (с исходниками, тестами, зависимостями, инсталляторами обновлений v2.2–v2.5). Актуальное состояние кода: **RAG Context v2.5**.
- `frontend_reference_v1.1_OLDER/`: **исторический** комплект интерфейсной интеграции (TypeScript клиент, мок-сервер, пример UI, документация). Он старее backend v2.5; его типы и OpenAPI snapshot не следует считать актуальными.
- `backend/API_OPENAPI_CURRENT.json`: OpenAPI из актуальной сборки backend на момент упаковки (если доступен).

## Запуск backend
```bash
cd backend
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python dev.py run
```
API: http://127.0.0.1:8000 ; Swagger: http://127.0.0.1:8000/docs ; OpenAPI: http://127.0.0.1:8000/openapi.json
Возможны дополнительные зависимости и конфигурация LLM/Ollama для LLM-режима. Режим табличного PDF-извлечения работает без LLM.

## Основные функции для сайта
- Загрузка PDF, документы, запуск анализа, статус задания, результаты и доказательства: `/api/v1/...` (смотреть точные методы и схемы в OpenAPI).
- Научное сравнение: `POST /api/v1/scientific/compare` (тело с `left_record_id` и `right_record_id`).
- Контроль качества: `GET /api/v1/scientific/quality/{publication_id}`.
- RAG-аудит: `GET /api/v1/scientific/rag/audit`.
- Превью таблиц: `GET /api/v1/scientific/rag/table-preview`.
- Scientific Search: `GET /api/v1/scientific/search` (уточнить точный маршрут по OpenAPI).

## Проверенный пользовательский сценарий
D001.pdf: 252 записи из таблицы 1, 14 методов, 3 датасета, 3 генератора, EM/F1. Сравнение RA-CoT и ThreadRAG по HotpotQA/EM дало `comparable`, с доказательством общего протокола из PDF, при неизвестном точном названии split. В quality API: 252/252 `ready_for_comparison`. Это реальные результаты локального запуска пользователя, но **сама база пользователя и PDF не вложены**. На чистой установке этих UUID и записей нет.

## Безопасность и границы
- Не вложены `.env`, SQLite база, пользовательские документы, PDF, секреты, резервные копии, кэши.
- Используйте переменную `CORS_ORIGINS` для origin вашего сайта, не открывайте произвольно все origins в production.
- Приложение является прототипом: проверьте аутентификацию, ограничения загрузки файлов и изоляцию данных перед публичным доступом.
- Не заменяйте действующую базу backend; переносите только код и настройте отдельную БД.
- Обновляйте TS API client под актуальный OpenAPI (референс v1.1 устарел).

## Версии
Backend core FastAPI имеет внутренний `app.version = 0.1.0` и это не номер патча. Версия этого **снимка исходников**: RAG Context **v2.5**, поверх RAG Table **v2.4**. Архив сделан из доступной здесь собранной проверочной копии, а не напрямую из файлов компьютера пользователя. Если на его Mac были несинхронизированные изменения, их здесь нет.
