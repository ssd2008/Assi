# API-спецификация v0.4

API проекта **Асси — Medical Learning Assistant**.

```text
Base URL: http://127.0.0.1:8000/api/v1
Swagger UI: http://127.0.0.1:8000/docs
OpenAPI JSON: http://127.0.0.1:8000/openapi.json
```

## Основные сущности

### Папка

Каждый материал обязан принадлежать одной папке. Папка `Без папки` является системной: её нельзя переименовать или удалить. При удалении обычной папки её материалы автоматически перемещаются в `Без папки`.

```json
{
  "id": "uuid",
  "name": "Кардиология",
  "is_system": false,
  "document_count": 4,
  "created_at": "2026-08-08T12:00:00Z",
  "updated_at": "2026-08-08T12:00:00Z"
}
```

### Материал

`DocumentOut` содержит обязательный `folder_id`. Поле `specialty` удалено из API и схемы хранения.

## Краткая сводка API

| Метод | Endpoint | Назначение |
|---|---|---|
| `GET` | `/health` | Проверка компонентов |
| `GET` | `/folders` | Список папок с количеством материалов |
| `POST` | `/folders` | Создать папку |
| `PATCH` | `/folders/{folder_id}` | Переименовать папку |
| `DELETE` | `/folders/{folder_id}` | Удалить папку; материалы перемещаются в `Без папки` |
| `POST` | `/documents` | Создать материал из текста или URL |
| `POST` | `/documents/upload` | Загрузить PDF |
| `POST` | `/documents/upload/video` | Загрузить видео |
| `GET` | `/documents` | Список материалов; поддерживает `folder_id` |
| `GET` | `/documents/{document_id}` | Один материал |
| `POST` | `/documents/{document_id}/index` | Индексировать / переиндексировать |
| `DELETE` | `/documents/{document_id}` | Удалить материал и его векторы |
| `GET` | `/videos/{document_id}` | Workspace видео: транскрипт, главы, хайлайты |
| `GET` | `/videos/{document_id}/stream` | Поток исходного видео с HTTP Range |
| `POST` | `/videos/{document_id}/ask` | Чат, ограниченный текущим видео |
| `GET` | `/jobs/{job_id}` | Статус фоновой индексации |
| `POST` | `/search` | Dense retrieval по материалам |
| `POST` | `/answer` | Ответ по найденным фрагментам |
| `POST` | `/feedback` | Пользовательская оценка ответа |

## Folders

### `GET /folders`

Возвращает все папки. В ответе у каждой папки есть `document_count`.

### `POST /folders`

```json
{
  "name": "Кардиология"
}
```

Название: 1–120 символов. Названия уникальны без учёта регистра.

### `PATCH /folders/{folder_id}`

```json
{
  "name": "Кардиология и сосудистые заболевания"
}
```

При переименовании обновляется также `folder_name` в Qdrant payload уже проиндексированных chunks.

### `DELETE /folders/{folder_id}`

Удаляет обычную папку. Все связанные материалы получают `folder_id` системной папки `Без папки`. Qdrant payload обновляется тем же образом. Системную папку удалить нельзя.

## Documents

### `POST /documents`

Для `text` и `url` поле `folder_id` обязательно.

```json
{
  "title": "Лекция по артериальной гипертензии",
  "source_type": "text",
  "raw_text": "Полный текст лекции...",
  "folder_id": "3be73d43-d98f-4afb-a54d-e1fb8220c512",
  "lecture_date": "2026-08-08",
  "language": "ru",
  "metadata": {}
}
```

### `POST /documents/upload`

`multipart/form-data`:

| Поле | Обязательно |
|---|---|
| `file` | да |
| `title` | да |
| `folder_id` | да |
| `language` | нет, default `ru` |
| `lecture_date` | нет |
| `metadata` | нет |

### `POST /documents/upload/video`

Поля совпадают с PDF upload. Поддерживаются `.mp4`, `.mov`, `.mkv`, `.webm`, `.m4v`. Видео транскрибируется локально через `faster-whisper`.

### `GET /documents`

Параметры: `limit`, `offset`, `status`, `source_type`, `folder_id`.

## Индексация видео

Pipeline V1:

```text
video file
  -> faster-whisper + word timestamps
  -> timed chunks
  -> multilingual-e5-large embeddings
  -> Qdrant
  -> semantic chapter boundary detection
  -> optional OpenAI-compatible title/highlight generation
```

Без генеративного backend главы строятся локально по semantic shift между соседними embedding-векторами. Хайлайты без генеративной модели не генерируются.

## Video workspace

### `GET /videos/{document_id}`

```json
{
  "document": {"id": "...", "folder_id": "..."},
  "transcript": [
    {"index": 0, "start_seconds": 0.4, "end_seconds": 8.1, "text": "..."}
  ],
  "chapters": [
    {"index": 0, "start_seconds": 0.4, "end_seconds": 340.0, "title": "Введение..."}
  ],
  "highlights": [],
  "analysis_status": "local",
  "generative_features_enabled": false
}
```

`analysis_status`: `pending`, `local`, `generated`, `failed`.

### `GET /videos/{document_id}/stream`

Возвращает исходный видеофайл. Поддерживается один HTTP `Range` диапазон, поэтому HTML5-плеер может перематывать видео без полной загрузки файла.

### `POST /videos/{document_id}/ask`

```json
{
  "message": "Какие противопоказания перечислены?",
  "history": [
    {"role": "user", "content": "О чем эта часть лекции?"},
    {"role": "assistant", "content": "..."}
  ]
}
```

Retrieval всегда ограничен `document_id` текущего видео. Ответ содержит обычные `citations` с `time_start_seconds` / `time_end_seconds`.

Если генеративный backend отключён, используется существующий extractive answer backend, а последние сообщения диалога добавляются к retrieval-query. Если генеративный backend включён, follow-up сначала преобразуется в самостоятельный поисковый запрос.

## Search

```json
{
  "query": "Какие препараты применяют при гипертензии?",
  "top_k": 10,
  "candidate_k": 30,
  "use_reranker": false,
  "filters": {
    "folder_ids": ["3be73d43-d98f-4afb-a54d-e1fb8220c512"],
    "document_ids": null,
    "source_types": ["pdf", "video"],
    "language": "ru"
  }
}
```

Основной production-режим остаётся Dense retrieval. Reranker включается только при `RERANKER_ENABLED=true` и `use_reranker=true`.

## OpenAI-compatible backend

По умолчанию GPT/LLM-функции выключены:

```dotenv
ANSWER_BACKEND=extractive
```

Для включения генеративных ответов, улучшенных названий глав, хайлайтов и contextualization multi-turn вопросов:

```dotenv
ANSWER_BACKEND=openai
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
OPENAI_TIMEOUT_SECONDS=90
```

`OPENAI_BASE_URL` настраивается отдельно от ключа, поэтому вместо OpenAI можно указать совместимый gateway/API. Backend использует OpenAI-compatible `chat/completions`.

Видео, аудиофайл и кадры в LLM не отправляются: генеративному endpoint передаются только текстовые chunks/транскрипт и пользовательские сообщения.
