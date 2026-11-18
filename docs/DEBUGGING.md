# ivcrag: отладка и трассировка

## TL;DR

```bash
python3 scripts/trace.py on            # включить трассировку (без рестарта)
python3 scripts/trace.py query "тел Жданко"
python3 scripts/trace.py last          # краткий разбор последнего запроса
python3 scripts/trace.py last-full     # полный JSON
python3 scripts/trace.py off           # выключить
python3 scripts/logs.py errors         # ошибки (errors.log)
python3 scripts/logs.py tracebacks     # только traceback'и
```

## Что есть для отладки

### 1. Per-request трейс (`logs/traces/YYYY-MM-DD/*.json`)

Один JSON на запрос. Поля:
- `request.query` — что спросили;
- `params` — `mode`, `top_k`, `max_context_chars`, `analytical_context_chars`, `stream`, `max_tokens`;
- `stages[]` — стадии в хронологии, у каждой `category`, `t_ms`, `data`:
  - `normalize` — исходный и нормализованный запрос;
  - `retrieval` — чанки из Qdrant: `id`, `source`, `chunk_index`, `text`, `score`, `rank`;
  - `context` — итоговый текст, ушедший в LLM, и его `chars`;
  - `llm_request` — `endpoint`, `model`, `max_tokens`, `prompt_chars`, полный `prompt`;
  - `llm_response` — `answer`, `answer_chars`, `usage` (реальные токены от LLM), `finish_reason`;
  - `shortcut` — сработал ли shortcut (`no_llm: true` — LLM не звался);
  - `error` — `type`, `msg` при исключении;
- `timings_ms` — суммарное время по стадиям;
- `status` — `ok` / `error`.

### 2. `logs/index.jsonl`

Одна строка на запрос. Быстрый поиск:
```bash
grep 'Жданко' ~/ivcrag/logs/index.jsonl
```
(путь: `~/ivcrag/logs/traces/index.jsonl`)

### 3. `logs/errors.log`

Только `WARNING+` от `app.*` и `ivcrag`. Ротация 5 МБ × 3. Сюда идут все ошибки — **искать ошибки здесь**, а не в `server.err.log`.

### 4. `logs/server.log` — access-логи (`GET /health`, `POST /v1/chat/completions`).

### 5. `logs/server.err.log` — stdout/stderr uvicorn + наши `INFO`. Шум от `urllib3`/`httpcore` приглушён.

## Как разобрать «почему долго»

1. `python3 scripts/trace.py last` — смотрим `timings_ms`.
2. Если `llm_response` >> `retrieval` + `context` + `llm_request` — долго LLM:
   - `usage.prompt_tokens` — сколько реально токенов (prefill);
   - `usage.prompt_tokens_details.cached_tokens` — сколько из кэша (чем больше, тем быстрее);
   - `usage.completion_tokens` — сколько сгенерировала (decode);
   - `finish_reason` — `stop` (сама) или `length` (обрезалось на `max_tokens`).
3. Если `retrieval` > 500 мс — Qdrant/сеть.
4. Если `shortcut.no_llm: true` — LLM не звался, всё быстро.

## Как разобрать «почему плохой ответ»

1. `python3 scripts/trace.py last-full` → `stages[]`.
2. `category=retrieval` → какие чанки нашли, какие `source`/`chunk_index`/`score`/`text`.
3. `category=context` → что реально ушло в LLM (полный текст).
4. `category=llm_request.data.prompt` → полный промпт (system + user).
5. `category=llm_response.data.answer` → что ответила LLM.

## Известные проблемы

- **Remote 192.168.10.217 перегружен** → `llm_response` 30–110 с, `cached_tokens` маленький (prefill с нуля). Не баг кода. Проверить `ssh user@192.168.10.217 'uptime'`.
- **`cached_tokens` маленький** → llama-server на 217 перезапускался или кэш префиксов сброшен. Повторный запрос с тем же промптом должен попасть в кэш.
- **`NameError: name 'tracing' is not defined`** → устаревший `__pycache__` после правок. Фикс: `find app -name __pycache__ -exec rm -rf {} +` и рестарт.
- **`GET /health` отвечает, `POST` падает** → смотреть `logs/errors.log` или `python3 scripts/logs.py tracebacks`.

## Эндпоинты

- `GET /health` — состояние (без auth).
- `GET /admin/trace` — статус трассировки (только localhost).
- `POST /admin/trace?on=1|0|toggle=1` — переключить (только localhost).
- `POST /v1/chat/completions` — основной запрос.
- `GET /v1/models` — список моделей.

## Что НЕ делать

- Не включать `IVCRAG_TRACE` через `sudo -E systemctl start` — systemd не наследует env. Только через `/admin/trace` или drop-in `Environment=IVCRAG_TRACE=1`.
- Не искать ошибки в `journalctl -u ivcrag-server` — там только `Started/Stopped`. Ошибки — в `logs/errors.log` и `logs/server.err.log`.