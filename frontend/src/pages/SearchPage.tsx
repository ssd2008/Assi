import { FormEvent, useState } from "react";
import { api } from "../api/client";
import type { DocumentItem, FolderItem, SearchResponse, SourceType } from "../api/types";
import { DocumentPicker } from "../components/DocumentPicker";
import { Button, EmptyState, ErrorBanner, Spinner, Tag } from "../components/ui";
import { formatScore, sourceLocationLabel, SOURCE_LABELS } from "../utils";

export function SearchPage({ documents, folders }: { documents: DocumentItem[]; folders: FolderItem[] }) {
  const [query, setQuery] = useState("");
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  const [folderId, setFolderId] = useState("");
  const [language, setLanguage] = useState("");
  const [sourceType, setSourceType] = useState<SourceType | "">("");
  const [topK, setTopK] = useState(10);
  const [candidateK, setCandidateK] = useState(30);
  const [useReranker, setUseReranker] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<SearchResponse | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setLoading(true); setError(null);
    try {
      setResponse(await api.search({
        query: query.trim(), top_k: topK, candidate_k: Math.max(candidateK, topK), use_reranker: useReranker,
        filters: {
          ...(selectedDocuments.length ? { document_ids: selectedDocuments } : {}),
          ...(folderId ? { folder_ids: [folderId] } : {}),
          ...(language.trim() ? { language: language.trim() } : {}),
          ...(sourceType ? { source_types: [sourceType] } : {}),
        },
      }));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Поиск завершился с ошибкой"); }
    finally { setLoading(false); }
  }

  return <div className="page-stack">
    <section className="page-heading"><div><span className="eyebrow">Retrieval</span><h1>Поиск по материалам</h1><p>Поиск можно ограничить папкой, конкретными материалами или типом источника.</p></div></section>
    <div className="split-layout split-layout--search">
      <aside className="panel filter-panel"><form onSubmit={(event) => void handleSubmit(event)}>
        <label className="field"><span>Поисковый запрос</span><textarea required minLength={2} rows={5} value={query} onChange={(e) => setQuery(e.target.value)} /></label>
        <div className="filter-section"><div className="filter-section__heading"><strong>Документы</strong>{selectedDocuments.length > 0 && <button type="button" onClick={() => setSelectedDocuments([])}>Сбросить</button>}</div><DocumentPicker documents={documents} selected={selectedDocuments} onChange={setSelectedDocuments} /></div>
        <button className="advanced-toggle" type="button" onClick={() => setShowAdvanced((value) => !value)}><span>Дополнительные параметры</span><span>{showAdvanced ? "−" : "+"}</span></button>
        {showAdvanced && <div className="advanced-fields">
          <label className="field"><span>Папка</span><select value={folderId} onChange={(e) => setFolderId(e.target.value)}><option value="">Любая</option>{folders.map((folder) => <option value={folder.id} key={folder.id}>{folder.name}</option>)}</select></label>
          <div className="form-grid form-grid--two"><label className="field"><span>Язык</span><input value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="ru" /></label><label className="field"><span>Тип источника</span><select value={sourceType} onChange={(e) => setSourceType(e.target.value as SourceType | "")}><option value="">Любой</option><option value="pdf">PDF</option><option value="video">Видео</option><option value="url">URL</option><option value="text">Текст</option></select></label></div>
          <div className="form-grid form-grid--two"><label className="field"><span>Результатов top_k</span><input type="number" min={1} max={100} value={topK} onChange={(e) => setTopK(Number(e.target.value))} /></label><label className="field"><span>Кандидатов candidate_k</span><input type="number" min={1} max={300} value={candidateK} onChange={(e) => setCandidateK(Number(e.target.value))} /></label></div>
          <label className="check-field check-field--compact"><input type="checkbox" checked={useReranker} onChange={(e) => setUseReranker(e.target.checked)} /><span><strong>Использовать reranker</strong><small>Требует RERANKER_ENABLED=true.</small></span></label>
        </div>}
        <Button className="full-width" type="submit" loading={loading} disabled={!query.trim()}>Найти фрагменты</Button>
      </form></aside>
      <section className="search-results">{error && <ErrorBanner message={error} />}{loading ? <div className="panel center-loader center-loader--large"><Spinner /><p>Ищем релевантные фрагменты...</p></div> : !response ? <div className="panel"><EmptyState icon="⌕" title="Введите вопрос для поиска" text="Здесь появятся chunks, scores, страницы и тайм-коды." /></div> : response.results.length === 0 ? <div className="panel"><EmptyState icon="∅" title="Результатов нет" text="Попробуйте изменить запрос или фильтры." /></div> : <div className="result-list">{response.results.map((result) => <article className="result-card" key={result.chunk_id}><div className="result-card__rank">#{result.rank}</div><div className="result-card__content"><div className="result-card__header"><div><h3>{result.document_title}</h3><div className="tag-row"><Tag>{SOURCE_LABELS[result.source_type]}</Tag><Tag tone="info">{result.folder_name}</Tag><Tag>{sourceLocationLabel(result.page_start, result.page_end, result.time_start_seconds, result.time_end_seconds)}</Tag></div></div><div className="score-stack"><span>Итоговый score</span><strong>{formatScore(result.final_score)}</strong></div></div><p className="result-text">{result.text}</p></div></article>)}</div>}</section>
    </div>
  </div>;
}
