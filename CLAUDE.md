# Project Rules: ivcrag
## Central Wiki Integration (`~/wiki`)

- **Wiki Path**: `/home/user/wiki` (on Windows: `%USERPROFILE%\wiki`).
- **Pre-Task Context**: Before modifying infrastructure, Docker configs, `llama.cpp`, `qdrant`, or core architecture in `ivcrag`, read `/home/user/wiki/wiki/entities/ivcrag/profile.md` and check `/home/user/wiki/wiki/decisions/` to avoid repeating past mistakes (e.g., CPU AVX limitations).
- **Auto-Sync Documentation & Decisions**:
  1. Whenever you create or update files in `docs/*.md`, change deployment scripts (`scripts/*.sh`), or make major architectural changes in `ivcrag`, offer (or execute upon confirmation) an update to `/home/user/wiki`.
  2. To sync: run `git pull --rebase` inside `/home/user/wiki`, copy updated `docs/*.md` into `/home/user/wiki/wiki/raw/ivcrag-<filename>`, update `/home/user/wiki/wiki/entities/ivcrag/profile.md` (or add a decision note in `/home/user/wiki/wiki/decisions/`), run `python scripts/wiki_index.py`, and run `git add . && git commit -m "docs(ivcrag): sync project updates" && git push` inside `/home/user/wiki`.
- **Language**: Write all wiki summaries and communicate with the user in Russian while keeping code and technical terms in English.
