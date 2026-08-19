export type SourceType = "pdf" | "url" | "text" | "video";
export type DocumentStatus = "uploaded" | "processing" | "ready" | "failed";
export type JobStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type ComponentStatus = "ok" | "error" | "disabled";

export interface FolderItem {
  id: string;
  name: string;
  is_system: boolean;
  document_count: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentItem {
  id: string;
  title: string;
  source_type: SourceType;
  status: DocumentStatus;
  folder_id: string;
  source_url: string | null;
  original_filename: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  lecture_date: string | null;
  language: string;
  metadata: Record<string, unknown>;
  chunk_count: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentsListResponse { items: DocumentItem[]; total: number; limit: number; offset: number; }
export interface CreateDocumentPayload {
  title: string;
  source_type: "url" | "text";
  folder_id: string;
  source_url?: string;
  raw_text?: string;
  lecture_date?: string;
  language: string;
  metadata?: Record<string, unknown>;
}

export interface IndexDocumentResponse { document_id: string; job_id: string; status: JobStatus; }
export interface JobItem {
  id: string; document_id: string; status: JobStatus; progress: number; chunk_size: number; chunk_overlap: number;
  result: Record<string, unknown>; error_message: string | null; created_at: string; started_at: string | null;
  finished_at: string | null; updated_at: string;
}

export interface SearchFilters {
  document_ids?: string[];
  folder_ids?: string[];
  source_types?: SourceType[];
  language?: string;
  lecture_date_from?: string;
  lecture_date_to?: string;
}
export interface SearchRequest {
  query: string; top_k: number; candidate_k: number; use_reranker: boolean; min_retrieval_score?: number; filters: SearchFilters;
}
export interface SearchResult {
  rank: number; chunk_id: string; document_id: string; document_title: string; folder_id: string; folder_name: string;
  chunk_index: number; text: string; source_type: SourceType; source_url: string | null; lecture_date: string | null;
  language: string; page_start: number | null; page_end: number | null; time_start_seconds: number | null;
  time_end_seconds: number | null; section_title: string | null; char_start: number; char_end: number;
  retrieval_score: number; rerank_score: number | null; final_score: number;
}
export interface SearchResponse { query: string; results: SearchResult[]; total_candidates: number; took_ms: number; }
export type ResponseStyle = "brief" | "detailed" | "study_notes";
export interface AnswerRequest extends SearchRequest { max_context_chunks: number; response_style: ResponseStyle; include_citations: boolean; }
export interface Citation {
  number: number; document_id: string; chunk_id: string; document_title: string; quote: string; page_start: number | null;
  page_end: number | null; time_start_seconds: number | null; time_end_seconds: number | null; section_title: string | null;
  char_start: number; char_end: number; retrieval_score: number; rerank_score: number | null;
}
export interface AnswerResponse {
  answer: string; citations: Citation[]; confidence: number; limitations: string[]; safety_notes: string[]; used_chunks: number; took_ms: number;
}

export interface TranscriptSegment { index: number; start_seconds: number; end_seconds: number; text: string; }
export interface VideoChapter { index: number; start_seconds: number; end_seconds: number; title: string; }
export interface VideoHighlight { index: number; start_seconds: number; end_seconds: number; title: string; reason: string; importance: number; }
export interface VideoWorkspace {
  document: DocumentItem;
  transcript: TranscriptSegment[];
  chapters: VideoChapter[];
  highlights: VideoHighlight[];
  analysis_status: "pending" | "local" | "generated" | "failed";
  generative_features_enabled: boolean;
}
export interface ChatMessage { role: "user" | "assistant"; content: string; }

export interface ComponentHealth { status: ComponentStatus; detail: string | null; }
export interface HealthResponse { status: "ok" | "degraded"; service: string; version: string; components: Record<string, ComponentHealth>; }
export interface ApiErrorShape { code?: string; detail?: string; context?: Record<string, unknown>; }
