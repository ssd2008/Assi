import { ChangeEvent, FormEvent, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { DocumentItem, FolderItem, JobItem, SourceType } from "../api/types";
import { Button, EmptyState, ErrorBanner, Modal, Spinner, Tag } from "../components/ui";
import { formatBytes, formatDate, formatTimecode, sleep, SOURCE_LABELS, STATUS_LABELS } from "../utils";

type UploadMode = "pdf" | "video" | "url" | "text";

export function FolderMaterialsPage({
  folder, documents, loading, error, refreshDocuments, notify, onOpenVideo,
}: {
  folder: FolderItem;
  documents: DocumentItem[];
  loading: boolean;
  error: string | null;
  refreshDocuments: () => Promise<void>;
  notify: (message: string, tone?: "success" | "error") => void;
  onOpenVideo: (document: DocumentItem) => void;
}) {
  const [showUpload, setShowUpload] = useState(false);
  const [mode, setMode] = useState<UploadMode>("video");
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("ru");
  const [lectureDate, setLectureDate] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [rawText, setRawText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [query, setQuery] = useState("");
  const [sourceType, setSourceType] = useState<SourceType | "">("");
  const [activeJobs, setActiveJobs] = useState<Record<string, JobItem>>({});
  const deleting = useRef(new Set<string>());

  const folderDocuments = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ru-RU");
    return documents.filter((document) => {
      if (document.folder_id !== folder.id) return false;
      if (sourceType && document.source_type !== sourceType) return false;
      return !normalized || document.title.toLocaleLowerCase("ru-RU").includes(normalized) || (document.original_filename || "").toLocaleLowerCase("ru-RU").includes(normalized);
    });
  }, [documents, folder.id, query, sourceType]);

  async function pollJob(document: DocumentItem, jobId: string) {
    for (let attempt = 0; attempt < 3600; attempt += 1) {
      if (deleting.current.has(document.id)) return;
      const job = await api.getJob(jobId);
      setActiveJobs((current) => ({ ...current, [document.id]: job }));
      if (["completed", "cancelled", "failed"].includes(job.status)) {
        setActiveJobs((current) => { const next = { ...current }; delete next[document.id]; return next; });
        await refreshDocuments();
        if (job.status === "completed") notify(`«${document.title}» проиндексирован`);
        if (job.status === "failed") notify(job.error_message || "Ошибка индексации", "error");
        return;
      }
      await sleep(2000);
    }
  }

  async function indexDocument(document: DocumentItem) {
    try {
      const result = await api.indexDocument(document.id);
      void pollJob(document, result.job_id);
      await refreshDocuments();
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "Не удалось начать индексацию", "error");
    }
  }

  function resetForm() {
    setTitle(""); setLanguage("ru"); setLectureDate(""); setSourceUrl(""); setRawText(""); setFile(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      let document: DocumentItem;
      if (mode === "pdf" || mode === "video") {
        if (!file) throw new Error("Выберите файл");
        const form = new FormData();
        form.append("file", file);
        form.append("title", title.trim());
        form.append("folder_id", folder.id);
        form.append("language", language.trim());
        if (lectureDate) form.append("lecture_date", lectureDate);
        document = mode === "video" ? await api.uploadVideo(form) : await api.uploadPdf(form);
      } else {
        document = await api.createDocument({
          title: title.trim(), source_type: mode, folder_id: folder.id, language: language.trim(),
          lecture_date: lectureDate || undefined,
          source_url: mode === "url" ? sourceUrl.trim() : undefined,
          raw_text: mode === "text" ? rawText.trim() : undefined,
        });
      }
      notify(`«${document.title}» добавлен`);
      setShowUpload(false);
      resetForm();
      await refreshDocuments();
      void indexDocument(document);
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : "Ошибка загрузки", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(document: DocumentItem) {
    if (!window.confirm(`Удалить «${document.title}» и все его фрагменты из индекса?`)) return;
    deleting.current.add(document.id);
    try {
      await api.deleteDocument(document.id);
      notify(`«${document.title}» удалён`);
      await refreshDocuments();
    } catch (caught) {
      deleting.current.delete(document.id);
      notify(caught instanceof Error ? caught.message : "Не удалось удалить материал", "error");
    }
  }

  function handleFile(event: ChangeEvent<HTMLInputElement>) { setFile(event.target.files?.[0] || null); }

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div><span className="eyebrow">Папка</span><h1>{folder.name}</h1><p>{folder.document_count} материалов. Видео, документы, ссылки и текстовые источники.</p></div>
        <Button icon={<span>＋</span>} onClick={() => setShowUpload(true)}>Добавить материал</Button>
      </section>
      <section className="panel">
        <div className="toolbar">
          <div className="search-control"><span>⌕</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Найти в папке" /></div>
          <select value={sourceType} onChange={(e) => setSourceType(e.target.value as SourceType | "")}><option value="">Все типы</option><option value="video">Видео</option><option value="pdf">PDF</option><option value="url">URL</option><option value="text">Текст</option></select>
          <Button variant="ghost" onClick={() => void refreshDocuments()} loading={loading}>Обновить</Button>
        </div>
        {error && <ErrorBanner message={error} onRetry={() => void refreshDocuments()} />}
        {loading && documents.length === 0 ? <div className="center-loader"><Spinner /></div> : folderDocuments.length === 0 ? (
          <EmptyState icon="▤" title="В папке пока нет материалов" text="Добавьте первое видео, PDF, ссылку или текст." action={<Button onClick={() => setShowUpload(true)}>Добавить материал</Button>} />
        ) : <div className="documents-grid">{folderDocuments.map((document) => {
          const job = activeJobs[document.id];
          const duration = typeof document.metadata.duration_seconds === "number" ? document.metadata.duration_seconds : null;
          return <article className={`document-card${document.source_type === "video" ? " document-card--clickable" : ""}`} key={document.id} onClick={() => document.source_type === "video" && onOpenVideo(document)}>
            <div className="document-card__top">
              <div className={`source-icon source-icon--${document.source_type}`}>{document.source_type === "video" ? "▶" : document.source_type === "pdf" ? "PDF" : document.source_type === "url" ? "↗" : "TXT"}</div>
              <div className="document-card__title"><h3>{document.title}</h3><div className="tag-row"><Tag>{SOURCE_LABELS[document.source_type]}</Tag><Tag>{STATUS_LABELS[document.status]}</Tag></div></div>
              <button className="icon-button" type="button" onClick={(e) => { e.stopPropagation(); void handleDelete(document); }} aria-label="Удалить">×</button>
            </div>
            <dl className="document-meta">
              <div><dt>Язык</dt><dd>{document.language.toUpperCase()}</dd></div><div><dt>Фрагменты</dt><dd>{document.chunk_count}</dd></div>
              <div><dt>Размер</dt><dd>{formatBytes(document.size_bytes)}</dd></div><div><dt>{document.source_type === "video" ? "Длительность" : "Дата лекции"}</dt><dd>{document.source_type === "video" ? formatTimecode(duration) : formatDate(document.lecture_date)}</dd></div>
            </dl>
            {job && <div className="job-progress"><div><span>{String(job.result.stage_detail || "Индексация")}</span><strong>{job.progress}%</strong></div><div className="job-progress__track"><span style={{ width: `${job.progress}%` }} /></div></div>}
            <div className="document-card__actions"><span className="document-id">{document.id.slice(0, 8)}</span>{document.status !== "processing" && <Button variant="secondary" onClick={(e) => { e.stopPropagation(); void indexDocument(document); }}>{document.source_type === "video" ? "Обновить анализ" : "Переиндексировать"}</Button>}</div>
          </article>;
        })}</div>}
      </section>
      {showUpload && <Modal title={`Добавить в «${folder.name}»`} subtitle="Папка назначается автоматически." onClose={() => setShowUpload(false)}>
        <form className="upload-form" onSubmit={(e) => void handleSubmit(e)}>
          <div className="segmented-control segmented-control--four">{(["video", "pdf", "url", "text"] as UploadMode[]).map((item) => <button type="button" key={item} className={mode === item ? "active" : ""} onClick={() => { setMode(item); setFile(null); }}>{item === "video" ? "Видео" : item === "pdf" ? "PDF" : item === "url" ? "URL" : "Текст"}</button>)}</div>
          <label className="field"><span>Название <b>*</b></span><input required maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
          {(mode === "video" || mode === "pdf") && <label className="file-drop"><input required type="file" accept={mode === "video" ? "video/*" : "application/pdf"} onChange={handleFile} /><span className="file-drop__icon">↑</span><strong>{file?.name || "Выберите файл"}</strong><small>{mode === "video" ? "MP4, MOV, MKV, WebM, M4V" : "PDF до настроенного лимита"}</small></label>}
          {mode === "url" && <label className="field"><span>URL <b>*</b></span><input required type="url" value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} /></label>}
          {mode === "text" && <label className="field"><span>Текст <b>*</b></span><textarea required rows={9} value={rawText} onChange={(e) => setRawText(e.target.value)} /></label>}
          <div className="form-grid form-grid--two"><label className="field"><span>Язык</span><input required value={language} onChange={(e) => setLanguage(e.target.value)} /></label><label className="field"><span>Дата лекции</span><input type="date" value={lectureDate} onChange={(e) => setLectureDate(e.target.value)} /></label></div>
          <div className="modal__actions"><Button type="button" variant="ghost" onClick={() => setShowUpload(false)}>Отмена</Button><Button type="submit" loading={submitting}>Добавить и индексировать</Button></div>
        </form>
      </Modal>}
    </div>
  );
}
