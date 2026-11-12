# ivcrag - RAG-сервис телефонного справочника

[![GitHub](https://img.shields.io/badge/github-bjdanko5%2Fivcrag-blue?logo=github)](https://github.com/bjdanko5/ivcrag)


OpenAI-совместимый API + встроенный UI на http://<host>:8091.

## Быстрый старт

    cd ~/ivcrag
    bash install_ivcrag.sh --dry-run
    bash install_ivcrag.sh --yes

## Структура

    ivcrag/
      install_ivcrag.sh        главный установщик
      config.yaml              порты, модели, пути, docker
      .env.example             шаблон секретов
      app/
        embedding_server.py    RAG-сервер
        requirements.txt       без torch
      scripts/
        check_*.sh             проверки
        install_*.sh           установка
        run_llama.sh, run_server.sh, index_docs.sh
        smoke_test.sh          7 curl-запросов
        check_all.sh           все проверки
      systemd/                 3 unit-файла
      docs/
        MOUNT_SMB.md           SMB-шара
        MIGRATION.md           перенос
      data/ models/ logs/
      venv/

## Управление

    sudo systemctl status ivcrag-qdrant ivcrag-llama ivcrag-server
    sudo systemctl restart ivcrag-server
    sudo journalctl -u ivcrag-server -f

## API

    curl -s http://localhost:8091/health | python3 -m json.tool
    curl -s http://localhost:8091/v1/chat/completions \
      -H "Content-Type: application/json" \
      -d '{"model":"rag","messages":[{"role":"user","content":"тел Жданко"}]}'

## UI

http://<host>:8091/


## Деплой на другой сервер

### 1. Создать архив на текущем сервере

    cd ~
    tar --exclude='ivcrag/venv' \
        --exclude='ivcrag/models' \
        --exclude='ivcrag/logs' \
        --exclude='ivcrag/data' \
        --exclude='ivcrag/app/__pycache__' \
        -czf ivcrag_deploy.tgz ivcrag/

НЕ включаем: venv/ (создастся), models/*.gguf (скачаются или скопируются),
logs/, data/ (пустые), __pycache__/.

### 2. Скопировать на новый хост

    scp ivcrag_deploy.tgz user@newhost:~/

### 3. Распаковать и поправить config.yaml

    tar -xzf ~/ivcrag_deploy.tgz
    cd ~/ivcrag

Обязательно проверить/поменять в `config.yaml`:

- `project.root`              -> /home/<newuser>/ivcrag
- `paths.docs_source`         -> куда смонтирована шара (см. docs/MOUNT_SMB.md)
- `paths.models_dir`          -> /home/<newuser>/ivcrag/models
- `paths.logs_dir`            -> /home/<newuser>/ivcrag/logs
- `paths.venv`                -> /home/<newuser>/ivcrag/venv
- `ports.*`                   -> если на новом хосте заняты

### 4. Установка

    bash install_ivcrag.sh --dry-run    # только проверки, ничего не меняет
    bash install_ivcrag.sh --yes        # установка + systemd

Установщик сам:

- проверит OS/python/docker/qdrant/models/ports
- поставит недостающее (apt, venv, pip с зеркалом Tsinghua, образы docker)
- скопирует .env.example -> .env
- поднимет qdrant + llama + server
- поставит systemd + enable
- прогонит smoke (7 запросов)

### 5. Проверить имена docker-контейнеров (ВАЖНО)

Перед `--yes` (или если `ivcrag-qdrant`/`ivcrag-llama` failed):

    docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"

Если имена НЕ `ivcrag-qdrant` / `micro-llm` - поправить юниты:

    sudo sed -i 's|docker start ivcrag-qdrant|docker start qdrant|' /etc/systemd/system/ivcrag-qdrant.service
    sudo sed -i 's|docker stop  ivcrag-qdrant|docker stop  qdrant|' /etc/systemd/system/ivcrag-qdrant.service
    sudo systemctl daemon-reload
    sudo systemctl restart ivcrag-qdrant

Подробнее - docs/MIGRATION.md, раздел «Имена docker-контейнеров».

### 6. SMB-шара (если нужна)

Отдельный шаг - docs/MOUNT_SMB.md. Установщик не монтирует.

### 7. Проверка

    sudo systemctl is-active ivcrag-qdrant ivcrag-llama ivcrag-server
    curl -s http://localhost:8091/health | python3 -m json.tool
    bash scripts/smoke_test.sh

Ожидается: все three active, health ok, smoke PASS=7 FAIL=0.

### Медленный интернет

По умолчанию pip идёт через зеркало Tsinghua (~20x быстрее PyPI).
Переопределить:

    IVCRAG_PIP_MIRROR=https://pypi.org/simple bash scripts/install_python.sh


### Деплой через GitHub (альтернатива tar и локальному bare-репо)

Репозиторий: https://github.com/bjdanko5/ivcrag

**На новом хосте:**

    git clone git@github.com:bjdanko5/ivcrag.git
    cd ivcrag
    cp .env.example .env       # вписать HF_TOKEN (и SMB_*, если нужно)
    bash install_ivcrag.sh --dry-run
    bash install_ivcrag.sh --yes

Установщик сам: venv, модели, qdrant, llama, systemd, smoke.

**Обновить существующий деплой:**

    cd ivcrag
    git pull origin main
    sudo systemctl restart ivcrag-server

**Версии (теги):**

    git tag -n                              # список
    git checkout v0.1.0                     # откат на версию
    git clone --branch v0.1.0 git@github.com:bjdanko5/ivcrag.git

## Документация

- SMB: docs/MOUNT_SMB.md
- Миграция: docs/MIGRATION.md
- PyTorch: НЕ нужен (см. MIGRATION.md)


## Статус на a3linux (2026-11-12)

- systemd: ivcrag-qdrant (active exited), ivcrag-llama (active exited), ivcrag-server (active running)
- /health: status ok, model_loaded true, qdrant_connected true, redis_connected true, tracked_files 6
- UI: HTTP 200
- smoke: PASS=7 FAIL=0
- docker: qdrant (Up), micro-llm (Up, healthy), embed (Up, healthy)
- llama :8082/health -> {"status":"ok"}
