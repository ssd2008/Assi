import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { AnswerResponse, ChatMessage, VideoWorkspace } from "../api/types";
import { Button, EmptyState, ErrorBanner, Spinner, Tag } from "../components/ui";

function timecode(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.floor(seconds || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}` : `${minutes}:${String(secs).padStart(2, "0")}`;
}

export function VideoPage({ documentId, onBack }: { documentId: string; onBack: () => void }) {
  const [workspace, setWorkspace] = useState<VideoWorkspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"chapters" | "highlights" | "transcript">("chapters");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [answers, setAnswers] = useState<AnswerResponse[]>([]);
  const [asking, setAsking] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const playerShellRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.getVideo(documentId)
      .then((result) => { if (active) { setWorkspace(result); setError(null); } })
      .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "Не удалось открыть видео"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [documentId]);

  function seek(seconds: number) {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = seconds;
    void video.play();
  }

  async function fullscreen() {
    const element = playerShellRef.current;
    if (element?.requestFullscreen) await element.requestFullscreen();
  }

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = question.trim();
    if (!message || asking) return;
    const history = [...messages];
    setMessages((current) => [...current, { role: "user", content: message }]);
    setQuestion("");
    setAsking(true);
    try {
      const response = await api.askVideo(documentId, message, history);
      setAnswers((current) => [...current, response]);
      setMessages((current) => [...current, { role: "assistant", content: response.answer }]);
    } catch (caught) {
      setMessages((current) => [...current, { role: "assistant", content: caught instanceof Error ? caught.message : "Не удалось получить ответ" }]);
      setAnswers((current) => [...current, { answer: "", citations: [], confidence: 0, limitations: [], safety_notes: [], used_chunks: 0, took_ms: 0 }]);
    } finally {
      setAsking(false);
    }
  }

  if (loading) return <div className="panel center-loader center-loader--large"><Spinner /><p>Открываем видео...</p></div>;
  if (error || !workspace) return <div className="page-stack"><Button variant="ghost" onClick={onBack}>← К папке</Button><ErrorBanner message={error || "Видео не найдено"} /></div>;

  const assistantAnswers = answers;
  let answerCursor = 0;

  return (
    <div className="page-stack video-page">
      <section className="video-page__heading">
        <button className="back-link" type="button" onClick={onBack}>← Назад к папке</button>
        <div><span className="eyebrow">Видео</span><h1>{workspace.document.title}</h1><div className="tag-row"><Tag>{workspace.analysis_status === "generated" ? "AI-разметка" : workspace.analysis_status === "local" ? "Локальная разметка" : "Разметка готовится"}</Tag>{!workspace.generative_features_enabled && <Tag>GPT отключён</Tag>}</div></div>
      </section>

      <div className="video-player-shell" ref={playerShellRef}>
        <video ref={videoRef} className="video-player" controls preload="metadata" src={api.videoStreamUrl(documentId)} />
        <button className="video-fullscreen" type="button" onClick={() => void fullscreen()}>⛶ На весь экран</button>
      </div>

      <div className="video-detail-grid">
        <section className="panel video-notes">
          <div className="video-tabs">
            <button className={tab === "chapters" ? "active" : ""} onClick={() => setTab("chapters")}>Главы</button>
            <button className={tab === "highlights" ? "active" : ""} onClick={() => setTab("highlights")}>Хайлайты</button>
            <button className={tab === "transcript" ? "active" : ""} onClick={() => setTab("transcript")}>Транскрипт</button>
          </div>
          {tab === "chapters" && (workspace.chapters.length ? <div className="timeline-list">{workspace.chapters.map((chapter) => <button key={chapter.index} className="timeline-item" type="button" onClick={() => seek(chapter.start_seconds)}><span>{timecode(chapter.start_seconds)}</span><div><strong>{chapter.title}</strong><small>{timecode(chapter.start_seconds)}–{timecode(chapter.end_seconds)}</small></div></button>)}</div> : <EmptyState icon="§" title="Глав пока нет" text="Они появятся после индексации видео." />)}
          {tab === "highlights" && (workspace.highlights.length ? <div className="timeline-list">{workspace.highlights.map((highlight) => <button key={highlight.index} className="timeline-item timeline-item--highlight" type="button" onClick={() => seek(highlight.start_seconds)}><span>{timecode(highlight.start_seconds)}</span><div><strong>{highlight.title}</strong><small>{highlight.reason || `Важность ${highlight.importance}/5`}</small></div></button>)}</div> : <EmptyState icon="✦" title="Хайлайтов пока нет" text={workspace.generative_features_enabled ? "Хайлайты появятся после повторной индексации видео." : "Для смысловых хайлайтов подключите OpenAI-compatible генеративную модель и переиндексируйте видео."} />)}
          {tab === "transcript" && (workspace.transcript.length ? <div className="transcript-list">{workspace.transcript.map((segment) => <button key={segment.index} className="transcript-item" type="button" onClick={() => seek(segment.start_seconds)}><span>{timecode(segment.start_seconds)}</span><p>{segment.text}</p></button>)}</div> : <EmptyState icon="T" title="Транскрипта пока нет" text="Видео должно пройти распознавание речи." />)}
        </section>

        <aside className="panel video-ask">
          <div className="video-ask__tab">Спросить</div>
          <div className="video-chat">
            {messages.length === 0 && <div className="video-chat__intro"><strong>Помощник по этому видео</strong><p>Поиск ограничен только текущим видео. Цитаты с таймкодами можно нажимать для перехода к фрагменту.</p></div>}
            {messages.map((message, index) => {
              const answer = message.role === "assistant" ? assistantAnswers[answerCursor++] : null;
              return <div className={`chat-message chat-message--${message.role}`} key={`${message.role}-${index}`}><span>{message.role === "user" ? "Вы" : "AI"}</span><p>{message.content}</p>{answer && answer.citations.length > 0 && <div className="chat-citations">{answer.citations.map((citation) => <button type="button" key={citation.chunk_id} onClick={() => seek(citation.time_start_seconds || 0)}>{timecode(citation.time_start_seconds)}–{timecode(citation.time_end_seconds)}</button>)}</div>}</div>;
            })}
            {asking && <div className="chat-message chat-message--assistant"><span>AI</span><Spinner small /></div>}
          </div>
          <form className="video-ask__form" onSubmit={(event) => void ask(event)}><textarea required minLength={2} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Спросить по содержанию видео..." rows={3} /><Button type="submit" loading={asking} disabled={!question.trim()}>Спросить</Button></form>
        </aside>
      </div>
    </div>
  );
}
