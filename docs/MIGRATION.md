# Миграция ivcrag на другой сервер

## Что переносить

- ~/ivcrag/ (без venv/, models/, logs/, data/)
- config.yaml (порты/пути под новый хост)
- .env (HF_TOKEN)
- /etc/allm-cred (если нужна SMB-шара, см. MOUNT_SMB.md)

НЕ переносить: venv/, models/*.gguf, logs/, data/, __pycache__/.

## Пошагово

### 1. На старом хосте - архив

    cd ~
    tar --exclude='ivcrag/venv' --exclude='ivcrag/models' --exclude='ivcrag/logs' \
        --exclude='ivcrag/data' --exclude='ivcrag/app/__pycache__' \
        -czf ivcrag_deploy.tgz ivcrag/

### 2. Копирование

    scp ivcrag_deploy.tgz user@newhost:~/

### 3. На новом хосте - распаковка

    tar -xzf ~/ivcrag_deploy.tgz
    cd ~/ivcrag

### 4. Правка config.yaml

- project.root -> /home/<newuser>/ivcrag
- paths.docs_source -> куда смонтирована шара
- paths.models_dir, paths.logs_dir, paths.venv
- ports.* -> если заняты

### 5. Установка

    bash install_ivcrag.sh --dry-run
    bash install_ivcrag.sh --yes

### 6. SMB-шара

Отдельный шаг - см. docs/MOUNT_SMB.md.

## Важное про PyTorch

НЕ ставить torch в venv ivcrag - CPU может не иметь AVX -> Illegal instruction.
Проект использует fastembed (ONNX Runtime).

Если torch нужен - отдельное venv ~/venv_torch:

    lscpu | grep -o 'avx[^ ]*' | head -1

Пусто -> torch упадёт; ставить torch==1.13.1 или не ставить.

## Откат

~/ivcrag создаётся с нуля, старый ~/embedding_server.py не трогается.
Откат = удалить ~/ivcrag/ и systemctl disable --now ivcrag-*.

## Сеть и зеркало pip (важно для медленного интернета)

По умолчанию `install_python.sh` использует **зеркало Tsinghua**:

    https://pypi.tuna.tsinghua.edu.cn/simple

Это в ~20 раз быстрее PyPI на медленных каналах (28 КБ/с -> 1-3 минуты вместо 30-60).

### Переопределить зеркало

    IVCRAG_PIP_MIRROR=https://pypi.org/simple \
    IVCRAG_PIP_MIRROR_HOST=pypi.org \
      bash scripts/install_python.sh

Или отредактировать `venv/pip.conf`:

    [global]
    index-url = https://pypi.tuna.tsinghua.edu.cn/simple
    trusted-host = pypi.tuna.tsinghua.edu.cn
    timeout = 120

### Проверить

    cat ~/ivcrag/venv/pip.conf
    ~/ivcrag/venv/bin/pip config list

## Имена docker-контейнеров (актуально на a3linux, 2026-11-12)

`ivcrag-qdrant.service` и `ivcrag-llama.service` вызывают `docker start <имя>`.
На a3linux имена **не совпадают** с каноническими из `config.yaml`:

    реальный контейнер    |  в config.yaml       |  в systemd (после фикса)
    ----------------------|----------------------|--------------------------
    qdrant                |  ivcrag-qdrant       |  qdrant
    micro-llm             |  micro-llm           |  micro-llm

**Было:** `docker start ivcrag-qdrant` -> failed (`control process exited`).
**Стало:** `docker start qdrant` (поправили sed'ом в `/etc/systemd/system/ivcrag-qdrant.service`).

### Как поправить на новом хосте

1. Посмотреть реальные имена:

       docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"

2. Поправить юнит (пример для qdrant -> qdrant):

       sudo sed -i 's|/usr/bin/docker start ivcrag-qdrant|/usr/bin/docker start qdrant|' /etc/systemd/system/ivcrag-qdrant.service
       sudo sed -i 's|/usr/bin/docker stop  ivcrag-qdrant|/usr/bin/docker stop  qdrant|' /etc/systemd/system/ivcrag-qdrant.service
       sudo systemctl daemon-reload
       sudo systemctl restart ivcrag-qdrant

3. То же для `ivcrag-llama.service` (если llama-контейнер называется иначе, чем `micro-llm`).

**Альтернатива:** пересоздать контейнеры с каноническими именами
(`docker run --name ivcrag-qdrant ... -v ivcrag_qdrant:/qdrant/storage`),
тогда юниты менять не нужно. Данные сохранятся в volume.

### Автоматизация (опционально)

В `install_ivcrag.sh` можно добавить шаг «подставить реальные имена контейнеров»:

    for svc in qdrant llama; do
      real=$(docker ps --format '{{.Names}}' | grep -iE "$svc" | head -1)
      # ... sed в /etc/systemd/system/ivcrag-$svc.service ...
    done

Пока делается вручную (см. выше).


## Полный список зависимостей (app/requirements.txt)

Web / API:

    fastapi, uvicorn, python-multipart, pydantic

RAG / Qdrant:

    fastembed, qdrant-client, pyyaml, requests, python-dotenv

Storage / parsing:

    redis, openpyxl, pypdf

torch НЕ включаем (CPU без AVX -> Illegal instruction).
Всё ставится из зеркала Tsinghua за 1-2 минуты.

## Windows / PowerShell: запросы к RAG

Проблемы:
- `curl` в PowerShell — алиас `Invoke-WebRequest` (другие параметры), не GNU curl
- `Invoke-RestMethod` в PowerShell 5.1 неправильно декодирует UTF-8 -> кракозябры
- `curl.exe -d '{\"..."}'` в PowerShell ломает JSON (кавычки)

### Решение 1 (рекомендуется) - Invoke-WebRequest + явное UTF-8

    $body = @{
      model = "rag"
      messages = @(@{ role = "user"; content = "тел Жданко" })
    } | ConvertTo-Json -Depth 5
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
    $resp = Invoke-WebRequest -Uri "http://192.168.10.21:8091/v1/chat/completions" `
      -Method Post -ContentType "application/json; charset=utf-8" -Body $bytes
    [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray()) | ConvertFrom-Json |
      Select-Object -ExpandProperty choices |
      Select-Object -ExpandProperty message |
      Select-Object -ExpandProperty content

### Решение 2 - curl.exe с --data-raw

    chcp 65001
    $json = '{"model":"rag","messages":[{"role":"user","content":"тел Жданко"}]}'
    curl.exe -s http://192.168.10.21:8091/v1/chat/completions `
      -H "Content-Type: application/json; charset=utf-8" `
      --data-raw $json

### Решение 3 - curl.exe из файла (UTF-8)

    @'
    {"model":"rag","messages":[{"role":"user","content":"тел Жданко"}]}
    '@ | Out-File -FilePath "$env:TEMP\req.json" -Encoding utf8
    curl.exe -s http://192.168.10.21:8091/v1/chat/completions `
      -H "Content-Type: application/json" `
      --data-binary "@$env:TEMP\req.json"

### Проверка health (любой вариант)

    curl.exe -s http://192.168.10.21:8091/health

## Модель LLM (v0.3.0)

Используется **Qwen2.5-1.5B-Instruct-Q4_K_M** (Q4_K_M, ~1 ГБ, RAM 11 ГБ свободно).
Запуск: llama.cpp:server с `--jinja` (поддержка `chat_template_kwargs.enable_thinking=false`).
Файл: `~/ivcrag/models/qwen2.5-1.5b-instruct-q4_k_m.gguf`.

## Модель LLM (v0.3.0+)

Используется **Qwen2.5-1.5B-Instruct-Q4_K_M** (~1 ГБ, Q4_K_M):
- лучше обобщает таблицы и списки, чем Qwen3-0.6B;
- отвечает на аналитические вопросы («УЗ1», «какие бывают классы защищенности», «что определяет уровень значимости»).

### Скачать модель (обязательно после git clone)

    cd ~/ivcrag/models
    wget -O qwen2.5-1.5b-instruct-q4_k_m.gguf \
      https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf

или через зеркало:

    wget -O qwen2.5-1.5b-instruct-q4_k_m.gguf \
      https://hf-mirror.com/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf

### Запуск llama.cpp с --jinja (обязательно для 1.5B)

`--jinja` включает поддержку `chat_template_kwargs.enable_thinking=false`
(иначе модель уходит в thinking-режим и `content` пустой).

В `scripts/run_llama.sh` строка запуска:

    "$IMG" -m "/models/$GGUF" --host 0.0.0.0 --port 8080 -c 4096 --jinja

Если контейнер уже создан без --jinja - пересоздать:

    docker rm -f micro-llm
    docker run -d --name micro-llm --restart unless-stopped \
      -p 8082:8080 \
      -v ~/ivcrag/models:/models:ro \
      ghcr.io/ggml-org/llama.cpp:server \
      -m /models/qwen2.5-1.5b-instruct-q4_k_m.gguf \
      --host 0.0.0.0 --port 8080 -c 4096 --jinja

### Проверка

    curl -s http://localhost:8082/health
    curl -s http://localhost:8082/v1/models | python3 -m json.tool | grep -E "model|name"

Ожидается: {"status":"ok"} и имя qwen2.5-1.5b-instruct-q4_k_m.gguf.

### Требования к RAM

- Qwen2.5-1.5B-Instruct-Q4_K_M: ~1.5-2 ГБ (плюс fastembed, qdrant, RAG-контекст)
- Рекомендуется >= 4 ГБ свободной RAM
- На a3linux: 15 ГБ total, 11 ГБ available - 1.5B влезает с запасом

### Старая модель (0.6B)

Qwen3-0.6B-Q4_K_M осталась в models/ (если скачивали ранее).
Переключиться обратно:

    # в config.yaml:
    llm_gguf: Qwen_Qwen3-0.6B-Q4_K_M.gguf
    llm_url: https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/Qwen_Qwen3-0.6B-Q4_K_M.gguf

    docker rm -f micro-llm
    docker run -d --name micro-llm ... -m /models/Qwen_Qwen3-0.6B-Q4_K_M.gguf ... --jinja
    sudo systemctl restart ivcrag-server

НО: 0.6B не обобщает таблицы - аналитические вопросы будут возвращать "нет информации".
