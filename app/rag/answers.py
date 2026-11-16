"""RAG answer generation and formatting."""
import re
from typing import List

from app.state import config, state
from app.rag.retrieval import _collect_all_entity_rows, _filter_hits_by_entity, _normalize_query_for_search


def _split_rows(text: str):
    return [row for row in text.split("\n---\n") if row.strip()]


def _format_department_answer(dept_query: str, all_sources_texts: list) -> str:
    pool = []
    for text in all_sources_texts:
        pool.extend(_split_rows(text))

    dq = config._normalize_text(dept_query).strip()
    if not dq or len(dq) < 2:
        return ""

    matched_rows = []
    for row in pool:
        if ":" not in row:
            continue
        fields = {}
        clean = re.sub(r"^\[[^\]]*\]\s*", "", row)
        for part in clean.split("|"):
            if ":" in part:
                key, value = part.split(":", 1)
                key = key.strip().lower()
                value = value.strip()
                if value:
                    fields[key] = value
        if not fields:
            continue

        dept_values = []
        for key in ("отдел", "отдел в тел."):
            if key in fields:
                dept_values.append(config._normalize_text(fields[key]))
        if not dept_values:
            continue

        dq_words = dq.split()
        dq_stems = []
        for word in dq_words:
            if len(word) >= 5:
                dq_stems.append(word[:5])
            elif len(word) >= 4:
                dq_stems.append(word[:4])
            else:
                dq_stems.append(word)
        if not dq_stems:
            continue

        if any(all(stem in value for stem in dq_stems) for value in dept_values):
            matched_rows.append(fields)

    if not matched_rows:
        return ""

    by_fio = {}
    for fields in matched_rows:
        fio = fields.get("ф.и.о.") or fields.get("фио") or ""
        if fio:
            by_fio[fio] = fields
        else:
            by_fio[tuple(sorted(fields.items()))] = fields

    records = list(by_fio.values())
    if not records:
        return ""

    canon = {
        "№": "№",
        "ф.и.о.": "Ф.И.О.",
        "фио": "Ф.И.О.",
        "отдел": "Отдел",
        "область": "Область",
        "внут.": "Внутренний",
        "внутренний": "Внутренний",
        "городской": "Городской",
        "мобильный": "Мобильный",
    }
    order = ["№", "Ф.И.О.", "Отдел", "Область", "Внутренний", "Городской", "Мобильный"]

    canonical_records = []
    for fields in records:
        mapped = {}
        for key, value in fields.items():
            mapped_key = canon.get(key)
            if mapped_key:
                mapped[mapped_key] = value
        if mapped.get("Ф.И.О."):
            canonical_records.append(mapped)

    if not canonical_records:
        return ""

    present = set()
    for record in canonical_records:
        present.update(record.keys())
    headers = [header for header in order if header in present]

    body_lines = []
    for record in canonical_records:
        values = [record.get(header, "") for header in headers]
        body_lines.append("| " + " | ".join(values) + " |")

    header_line = "| " + " | ".join(headers) + " |"
    separator = "|" + "|".join("---" for _ in headers) + "|"
    result = "\n".join([header_line, separator] + body_lines)
    result += f"\n\n_Сотрудников в отделе: {len(canonical_records)}._"
    return result


def _format_phone_answer_from_hit(hit_text: str, question: str, all_hits_texts=None) -> str:
    pool = _split_rows(hit_text)
    if all_hits_texts:
        for text in all_hits_texts:
            if text != hit_text:
                pool.extend(_split_rows(text))

    seen = set()
    unique_pool = []
    for row in pool:
        key = row.strip()
        if key and key not in seen:
            seen.add(key)
            unique_pool.append(row)

    entities = re.findall(r"[А-ЯЁA-Z][а-яёa-z]{3,}", question or "")
    ignore = {"что", "как", "где", "когда", "почему", "зачем", "какой", "какая", "какие", "телефон", "директора", "комната", "отдел"}
    entities = [entity for entity in entities if config._normalize_text(entity) not in ignore]

    def stems_for(entity: str):
        normalized = config._normalize_text(entity)
        output = []
        if normalized.endswith("ко") and len(normalized) > 5:
            output.append(normalized[:-1])
        if len(normalized) >= 5:
            output.append(normalized[:5])
        if len(normalized) >= 4:
            output.append(normalized[:4])
        return output

    matches = []
    for row in unique_pool:
        normalized_row = config._normalize_text(row)
        for entity in entities:
            if any(stem in normalized_row for stem in stems_for(entity)):
                matches.append(row)
                break

    if not matches:
        return ""

    def extract_fields(row: str):
        clean = re.sub(r"^\[[^\]]*\]\s*", "", row)
        clean = re.sub(r"\s*---.*$", "", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        fields = {}
        if ":" in clean:
            for part in clean.split("|"):
                if ":" in part:
                    key, value = part.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip()
                    if value:
                        fields[key] = value
        return fields

    canon = {
        "фио": "Ф.И.О.",
        "ф.и.о.": "Ф.И.О.",
        "фамилия": "Ф.И.О.",
        "имя": "Ф.И.О.",
        "комната": "Комната",
        "каб.": "Комната",
        "кабинет": "Комната",
        "внут.": "Внутренний",
        "внутренний": "Внутренний",
        "телефон внутренний": "Внутренний",
        "городской": "Городской",
        "телефон городской": "Городской",
        "мобильный": "Мобильный",
        "телефон мобильный": "Мобильный",
        "отдел": "Отдел",
        "должность": "Должность",
        "область": "Область",
        "№": "№",
    }
    order = ["№", "Ф.И.О.", "Должность", "Комната", "Отдел", "Область", "Внутренний", "Городской", "Мобильный"]

    records = []
    for match in matches:
        fields = extract_fields(match)
        mapped = {}
        for key, value in fields.items():
            mapped_key = canon.get(key)
            if mapped_key:
                mapped[mapped_key] = value
        if mapped:
            records.append(mapped)

    if not records:
        return ""

    by_key = {}
    for record in records:
        key = record.get("Ф.И.О.") or tuple(sorted(record.items()))
        if key not in by_key:
            by_key[key] = record
        else:
            if len([value for value in record.values() if value]) > len([value for value in by_key[key].values() if value]):
                by_key[key] = record
    unique_records = list(by_key.values())

    present = set()
    for record in unique_records:
        present.update(record.keys())
    headers = [header for header in order if header in present]
    extra = [header for header in present if header not in headers]
    headers.extend(sorted(extra))
    if not headers:
        return ""

    body_lines = []
    for record in unique_records:
        values = [record.get(header, "") for header in headers]
        body_lines.append("| " + " | ".join(values) + " |")

    header_line = "| " + " | ".join(headers) + " |"
    separator = "|" + "|".join("---" for _ in headers) + "|"
    result = "\n".join([header_line, separator] + body_lines)

    if len(unique_records) > 1:
        result += f"\n\n_Найдено несколько совпадений ({len(unique_records)}). Уточните ФИО, отдел или комнату._"
    return result


def _build_md_table(headers: List[str], values: List[str]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    separator = "|" + "|".join("---" for _ in headers) + "|"
    value_line = "| " + " | ".join(values) + " |"
    return f"{header_line}\n{separator}\n{value_line}"


def _build_context_adaptive(ranked, question, relevance_fn):
    """Собирает контекст при базовом лимите; если релевантные блоки не влезли —
    пересобирает при расширенном лимите. Без предметных словарей."""
    base = config.MAX_CONTEXT_CHARS
    extended = max(base, getattr(config, "ANALYTICAL_CONTEXT_CHARS", base))

    def collect(limit):
        parts, total, dropped_rel = [], 0, 0
        for hit in ranked:
            text = hit.payload.get("text", "") or ""
            block = f"[{hit.payload.get('source', '?')} | chunk {hit.payload.get('chunk_index', '?')}]\n{text}\n"
            if total + len(block) > limit:
                if relevance_fn(hit, question) > 0:
                    dropped_rel += 1
                continue
            parts.append(block)
            total += len(block)
        return parts, dropped_rel

    parts, dropped = collect(base)
    if dropped > 0 and extended > base:
        parts2, _ = collect(extended)
        if len("\n---\n".join(parts2)) > len("\n---\n".join(parts)):
            parts = parts2
    return "\n---\n".join(parts) if parts else "(контекст не найден)"


def _rag_answer(question: str, max_tokens: int = None) -> dict:
    search_question = _normalize_query_for_search(question)
    query_vector = list(state._dense_model.query_embed(f"query: {search_question}"))[0].tolist()

    query_filter = None
    file_match = re.search(r"[\w.-]+\.(?:md|txt|pdf|docx|xlsx|xls|py|sh|json|ya?ml)", question, re.IGNORECASE)
    if file_match:
        query_filter = state.models.Filter(
            must=[
                state.models.FieldCondition(
                    key="source",
                    match=state.models.MatchValue(value=file_match.group(0)),
                )
            ]
        )

    hits = state.qdrant_client.query_points(
        collection_name=config.COLLECTION_NAME,
        prefetch=[
            state.Prefetch(query=query_vector, using="dense", limit=25),
            state.Prefetch(query=state.Document(text=search_question, model="Qdrant/bm25"), using="sparse", limit=25),
        ],
        query=state.models.FusionQuery(fusion=state.models.Fusion.RRF),
        query_filter=query_filter,
        limit=config.TOP_K,
        with_payload=True,
    ).points

    hits = _filter_hits_by_entity(hits, question)

    _STOP = {"тел", "телефон", "отдел", "кто", "какие", "есть", "все", "список", "номер", "как", "чем", "что", "где", "когда"}

    def _ctx_relevance(hit, question):
        text = (hit.payload.get("text") or "").lower()
        words = [w for w in re.findall(r"\w{3,}", question.lower()) if w not in _STOP]
        if not words:
            return 0.0
        stems = [w[:5] for w in words]
        return sum(1 for st in stems if st in text) / len(stems)

    ranked = sorted(hits, key=lambda h: _ctx_relevance(h, question), reverse=True)
    context = _build_context_adaptive(ranked, question, _ctx_relevance)
    sources = sorted({hit.payload.get("source", "?") for hit in hits})

    has_name = bool(re.search(r"[А-ЯЁA-Z][а-яёa-z]{3,}", question))
    job_titles = r"директор|секретарь|бухгалтер|начальник|зам|специалист|электроник|инженер|менеджер|руководитель|главный|юрист|экономист|кадровик|делопроизводитель"
    has_job = bool(re.search(job_titles, question, re.IGNORECASE))

    if re.search(r"какие\s+отделы|список\s+отделов|все\s+отделы", question, re.IGNORECASE):
        try:
            all_depts = set()
            offset = None
            while True:
                points, offset = state.qdrant_client.scroll(
                    collection_name=config.COLLECTION_NAME,
                    limit=200,
                    offset=offset,
                    with_payload=True,
                )
                for point in points:
                    if point.payload and point.payload.get("text"):
                        for row in point.payload["text"].split("\n---\n"):
                            match = re.search(r"Отдел:\s*([^|]+)", row)
                            if match:
                                department = match.group(1).strip()
                                if department:
                                    all_depts.add(department)
                if offset is None:
                    break
            all_depts = {department for department in all_depts if config._normalize_text(department) not in {"отдел", "отдел в тел.", ""}}
            if all_depts:
                answer = "В справочнике есть отделы:\n" + "\n".join(f"- {config._department_with_alias(department)}" for department in sorted(all_depts))
                state.log.info(f"[rag] Прямой ответ (список отделов): {len(all_depts)} отделов")
                return {"answer": answer, "sources": sources, "hits": len(hits), "no_llm": True}
        except Exception as exc:  # pragma: no cover
            state.log.warning(f"[rag] list departments failed: {exc}")

    if re.search(r"телефон|мобильн|внутренн|городск|тел[.\s]|позвонить|контакт|кто\s+работает|кто\s+сотрудник|список\s+сотрудник|сотрудник|люди|людей|человек|сколько|количество|кол-во|как\s+много|кто\s+в\s+отдел", question, re.IGNORECASE):
        dept_query = re.sub(
            r"\b(тел|телефон|мобильн\w*|внутренн\w*|городск\w*|позвонить|контакт\w*|отдел\w*|кто|работает|сотрудник\w*|список|люди|людей|человек|в|на|по|сколько|количество|кол-во|как|много)\b",
            " ",
            question,
            flags=re.IGNORECASE,
        ).strip()
        dept_query = re.sub(r"\s+", " ", dept_query).strip(" .,!?-")
        if dept_query and len(dept_query) >= 2:
            try:
                all_src_texts = []
                offset = None
                while True:
                    points, offset = state.qdrant_client.scroll(
                        collection_name=config.COLLECTION_NAME,
                        limit=200,
                        offset=offset,
                        with_payload=True,
                    )
                    for point in points:
                        if point.payload and point.payload.get("text"):
                            all_src_texts.append(point.payload["text"])
                    if offset is None:
                        break
                dept_table = _format_department_answer(config._expand_department(dept_query), all_src_texts)
                if dept_table:
                    state.log.info(f"[rag] Прямой ответ по отделу «{dept_query}»:\n{dept_table[:200]}")
                    return {"answer": dept_table, "sources": sources, "hits": len(hits), "no_llm": True}
            except Exception as exc:  # pragma: no cover
                state.log.warning(f"[rag] dept answer failed: {exc}")

    if re.search(r"отдел|комнат|кабинет|где\s+сидит|где\s+работает", question, re.IGNORECASE):
        entity_words = re.findall(r"[А-ЯЁA-Z][а-яёa-z]{3,}", question)
        ignore_attr = {"каком", "какой", "какая", "какие", "отдел", "отделе", "комната", "комнате", "кабинет", "кабинете", "где", "сидит", "работает", "телефон"}
        entity_words = [word for word in entity_words if config._normalize_text(word) not in ignore_attr]
        if entity_words:
            try:
                all_src_texts = []
                offset = None
                while True:
                    points, offset = state.qdrant_client.scroll(
                        collection_name=config.COLLECTION_NAME,
                        limit=200,
                        offset=offset,
                        with_payload=True,
                    )
                    for point in points:
                        if point.payload and point.payload.get("text"):
                            all_src_texts.append(point.payload["text"])
                    if offset is None:
                        break
                found_rows = []
                for text in all_src_texts:
                    for row in text.split("\n---\n"):
                        if ":" not in row:
                            continue
                        normalized_row = config._normalize_text(row)
                        for entity in entity_words:
                            normalized_entity = config._normalize_text(entity)
                            stems = []
                            if normalized_entity.endswith("ко") and len(normalized_entity) > 5:
                                stems.append(normalized_entity[:-1])
                            if len(normalized_entity) >= 5:
                                stems.append(normalized_entity[:5])
                            if len(normalized_entity) >= 4:
                                stems.append(normalized_entity[:4])
                            if any(stem in normalized_row for stem in stems):
                                found_rows.append(row)
                                break
                unique_rows = []
                seen = set()
                for row in found_rows:
                    key = row.strip()
                    if key and key not in seen:
                        seen.add(key)
                        unique_rows.append(row)
                if unique_rows:
                    formatted = _format_phone_answer_from_hit(unique_rows[0], question, all_hits_texts=unique_rows)
                    if formatted:
                        state.log.info(f"[rag] Прямой ответ атрибута:\n{formatted}")
                        return {"answer": formatted, "sources": sources, "hits": len(hits), "no_llm": True}
            except Exception as exc:  # pragma: no cover
                state.log.warning(f"[rag] attr answer failed: {exc}")

    if (has_name or has_job) and re.search(r"телефон|мобильн|внутренн|городск|тел[.\s]|позвонить|контакт", question, re.IGNORECASE):
        all_texts = [hit.payload.get("text", "") for hit in hits]
        sources_in_hits = sorted({hit.payload.get("source", "") for hit in hits if hit.payload.get("source")})
        extra_rows = []
        for source_name in sources_in_hits:
            extra_rows.extend(_collect_all_entity_rows(source_name, question))
        try:
            all_sources = set()
            offset = None
            while True:
                points, offset = state.qdrant_client.scroll(
                    collection_name=config.COLLECTION_NAME,
                    limit=200,
                    offset=offset,
                    with_payload=True,
                )
                for point in points:
                    if point.payload and point.payload.get("source"):
                        all_sources.add(point.payload["source"])
                if offset is None:
                    break
            for source_name in sorted(all_sources):
                if source_name not in sources_in_hits:
                    extra_rows.extend(_collect_all_entity_rows(source_name, question))
        except Exception as exc:  # pragma: no cover
            state.log.warning(f"[rag] scroll all sources failed: {exc}")
        combined_texts = list(dict.fromkeys(all_texts + extra_rows))
        for text in combined_texts:
            formatted = _format_phone_answer_from_hit(text, question, all_hits_texts=combined_texts)
            if formatted:
                state.log.info(f"[rag] Прямой ответ без LLM:\n{formatted}")
                return {"answer": formatted, "sources": sources, "hits": len(hits), "no_llm": True}

    dept_query_for_llm = re.sub(
        r"\b(тел|телефон|мобильн\w*|внутренн\w*|городск\w*|позвонить|контакт\w*|отдел\w*|кто|работает|сотрудник\w*|список|люди|в|на|по)\b",
        " ",
        question,
        flags=re.IGNORECASE,
    ).strip()
    if dept_query_for_llm and len(dept_query_for_llm) >= 2:
        all_texts_for_llm = []
        offset = None
        while True:
            points, offset = state.qdrant_client.scroll(
                collection_name=config.COLLECTION_NAME,
                limit=200,
                offset=offset,
                with_payload=True,
            )
            for point in points:
                if point.payload and point.payload.get("text"):
                    all_texts_for_llm.append(point.payload["text"])
            if offset is None:
                break
        dept_table_for_llm = _format_department_answer(dept_query_for_llm, all_texts_for_llm)
        if dept_table_for_llm:
            extra_llm = "\n---\nТаблица сотрудников отдела:\n" + dept_table_for_llm + "\n"
            if len(context) + len(extra_llm) <= config.MAX_CONTEXT_CHARS + 1000:
                context += extra_llm
                state.log.info(f"[RAG] Добавлена таблица отдела {dept_query_for_llm} в контекст для LLM")

    tag_re = r"\b(токен|токен[а-я]*|ключ|пароль|api[_ ]?key|hf_|secret)\b"
    if re.search(tag_re, question, re.IGNORECASE) or re.search(r"\b\w+_\w+\b", question):
        prompt_to_use = config.FEW_SHOT_PROMPT
    else:
        prompt_to_use = config.SYSTEM_PROMPT
    user_prompt = prompt_to_use.format(context=context, question=question)

    def _post_llm(url: str, model: str):
        headers = {"Content-Type": "application/json"}
        if config.LLM_API_KEY:
            headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
        r = state.requests.post(
            url,
            json={
                "model": model,
                "messages": [{"role": "user", "content": user_prompt}],
                "max_tokens": max_tokens or config.MAX_ANSWER_TOKENS,
                "temperature": 0.3,
                "top_p": 0.9,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            headers=headers,
            timeout=config.LLM_TIMEOUT,
        )
        r.raise_for_status()
        return r

    try:
        response = _post_llm(config.LLM_URL, config.LLM_MODEL)
    except Exception as e:
        if config.LLM_MODE == "remote" and config.LLM_FALLBACK_TO_LOCAL:
            state.log.warning(f"[LLM] remote failed ({e}), fallback to local")
            response = _post_llm(config.LLM_LOCAL_URL, config.LLM_LOCAL_MODEL)
        else:
            raise
    data = response.json()
    answer = data["choices"][0]["message"].get("content", "").strip() or "(пустой ответ)"
    return {"answer": answer, "sources": sources, "hits": len(hits)}


__all__ = [
    "_split_rows",
    "_format_department_answer",
    "_format_phone_answer_from_hit",
    "_build_md_table",
    "_rag_answer",
]
