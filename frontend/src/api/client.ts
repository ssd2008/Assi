import type {
  AnswerRequest, AnswerResponse, ApiErrorShape, ChatMessage, CreateDocumentPayload, DocumentItem,
  DocumentsListResponse, DocumentStatus, FolderItem, HealthResponse, IndexDocumentResponse, JobItem,
  SearchRequest, SearchResponse, SourceType, VideoWorkspace,
} from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly context: Record<string, unknown>;
  constructor(status: number, payload: ApiErrorShape) {
    super(payload.detail || `Ошибка API (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.code = payload.code || "api_error";
    this.context = payload.context || {};
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let payload: ApiErrorShape = { detail: response.statusText };
    try { payload = (await response.json()) as ApiErrorShape; } catch { /* empty proxy body */ }
    throw new ApiError(response.status, payload);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface DocumentListParams {
  limit?: number;
  offset?: number;
  status?: DocumentStatus | "";
  sourceType?: SourceType | "";
  folderId?: string;
}

export const api = {
  getHealth: () => request<HealthResponse>("/health"),
  listFolders: () => request<FolderItem[]>("/folders"),
  createFolder: (name: string) => request<FolderItem>("/folders", { method: "POST", body: JSON.stringify({ name }) }),
  renameFolder: (folderId: string, name: string) => request<FolderItem>(`/folders/${folderId}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  deleteFolder: (folderId: string) => request<void>(`/folders/${folderId}`, { method: "DELETE" }),

  async listDocuments(params: DocumentListParams = {}): Promise<DocumentsListResponse> {
    const search = new URLSearchParams();
    search.set("limit", String(params.limit ?? 100));
    search.set("offset", String(params.offset ?? 0));
    if (params.status) search.set("status", params.status);
    if (params.sourceType) search.set("source_type", params.sourceType);
    if (params.folderId) search.set("folder_id", params.folderId);
    return request<DocumentsListResponse>(`/documents?${search.toString()}`);
  },
  createDocument: (payload: CreateDocumentPayload) => request<DocumentItem>("/documents", { method: "POST", body: JSON.stringify(payload) }),
  uploadPdf: (formData: FormData) => request<DocumentItem>("/documents/upload", { method: "POST", body: formData }),
  uploadVideo: (formData: FormData) => request<DocumentItem>("/documents/upload/video", { method: "POST", body: formData }),
  deleteDocument: (documentId: string) => request<void>(`/documents/${documentId}`, { method: "DELETE" }),
  indexDocument: (documentId: string, options: { chunk_size?: number; chunk_overlap?: number } = {}) => request<IndexDocumentResponse>(`/documents/${documentId}/index`, { method: "POST", body: JSON.stringify(options) }),
  getJob: (jobId: string) => request<JobItem>(`/jobs/${jobId}`),
  search: (payload: SearchRequest) => request<SearchResponse>("/search", { method: "POST", body: JSON.stringify(payload) }),
  answer: (payload: AnswerRequest) => request<AnswerResponse>("/answer", { method: "POST", body: JSON.stringify(payload) }),
  getVideo: (documentId: string) => request<VideoWorkspace>(`/videos/${documentId}`),
  askVideo: (documentId: string, message: string, history: ChatMessage[]) => request<AnswerResponse>(`/videos/${documentId}/ask`, { method: "POST", body: JSON.stringify({ message, history }) }),
  videoStreamUrl: (documentId: string) => `${API_BASE_URL}/videos/${documentId}/stream`,
};
