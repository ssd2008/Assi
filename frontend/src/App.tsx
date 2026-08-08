import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api/client";
import type { DocumentItem, FolderItem, HealthResponse } from "./api/types";
import { HealthIndicator } from "./components/HealthIndicator";
import { ErrorBanner } from "./components/ui";
import { AssistantPage } from "./pages/AssistantPage";
import { FolderMaterialsPage } from "./pages/FolderMaterialsPage";
import { SearchPage } from "./pages/SearchPage";
import { SystemPage } from "./pages/SystemPage";
import { VideoPage } from "./pages/VideoPage";

interface ToastState { id: number; message: string; tone: "success" | "error"; }
type Route =
  | { page: "home" }
  | { page: "folder"; folderId: string }
  | { page: "video"; folderId: string; videoId: string }
  | { page: "assistant" | "search" | "system" };

function parseRoute(): Route {
  const parts = window.location.pathname.split("/").filter(Boolean);
  if (parts[0] === "materials" && parts[1] && parts[2] === "video" && parts[3]) return { page: "video", folderId: parts[1], videoId: parts[3] };
  if (parts[0] === "materials" && parts[1]) return { page: "folder", folderId: parts[1] };
  if (["assistant", "search", "system"].includes(parts[0])) return { page: parts[0] as "assistant" | "search" | "system" };
  return { page: "home" };
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute());
  const [materialsOpen, setMaterialsOpen] = useState(true);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [folders, setFolders] = useState<FolderItem[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(true);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [toasts, setToasts] = useState<ToastState[]>([]);

  const notify = useCallback((message: string, tone: "success" | "error" = "success") => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((current) => [...current, { id, message, tone }]);
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 4500);
  }, []);

  const refreshWorkspace = useCallback(async () => {
    setDocumentsLoading(true);
    setDocumentsError(null);
    try {
      const [documentResponse, folderResponse] = await Promise.all([api.listDocuments({ limit: 500 }), api.listFolders()]);
      setDocuments(documentResponse.items);
      setFolders(folderResponse);
    } catch (caught) {
      setDocumentsError(caught instanceof Error ? caught.message : "Не удалось загрузить материалы");
    } finally {
      setDocumentsLoading(false);
    }
  }, []);

  const refreshHealth = useCallback(async () => {
    setHealthLoading(true);
    try { setHealth(await api.getHealth()); } catch { setHealth(null); } finally { setHealthLoading(false); }
  }, []);

  useEffect(() => {
    void refreshWorkspace();
    void refreshHealth();
    const interval = window.setInterval(() => void refreshHealth(), 30000);
    const onPopState = () => setRoute(parseRoute());
    window.addEventListener("popstate", onPopState);
    return () => { window.clearInterval(interval); window.removeEventListener("popstate", onPopState); };
  }, [refreshHealth, refreshWorkspace]);

  function navigate(path: string) {
    window.history.pushState({}, "", path);
    setRoute(parseRoute());
    setMobileMenuOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function createFolder() {
    const name = window.prompt("Название новой папки");
    if (!name?.trim()) return;
    try {
      const folder = await api.createFolder(name.trim());
      await refreshWorkspace();
      setMaterialsOpen(true);
      navigate(`/materials/${folder.id}`);
    } catch (caught) { notify(caught instanceof Error ? caught.message : "Не удалось создать папку", "error"); }
  }

  async function renameFolder(folder: FolderItem) {
    if (folder.is_system) return;
    const name = window.prompt("Новое название папки", folder.name);
    if (!name?.trim() || name.trim() === folder.name) return;
    try { await api.renameFolder(folder.id, name.trim()); await refreshWorkspace(); } catch (caught) { notify(caught instanceof Error ? caught.message : "Не удалось переименовать папку", "error"); }
  }

  async function deleteFolder(folder: FolderItem) {
    if (folder.is_system) return;
    if (!window.confirm(`Удалить папку «${folder.name}»? ${folder.document_count} материалов будут перемещены в «Без папки».`)) return;
    try {
      await api.deleteFolder(folder.id);
      await refreshWorkspace();
      if ((route.page === "folder" || route.page === "video") && route.folderId === folder.id) navigate("/");
    } catch (caught) { notify(caught instanceof Error ? caught.message : "Не удалось удалить папку", "error"); }
  }

  const activeFolder = useMemo(() => (route.page === "folder" || route.page === "video") ? folders.find((folder) => folder.id === route.folderId) || null : null, [folders, route]);

  return (
    <div className="app-shell">
      <aside className={`sidebar${mobileMenuOpen ? " sidebar--open" : ""}`}>
        <div className="brand"><div className="brand__mark">А</div><div><strong>Асси</strong><span>Medical Learning Assistant</span></div></div>
        <nav className="navigation" aria-label="Основная навигация">
          <span className="navigation__label">Рабочее пространство</span>
          <button type="button" className={route.page === "folder" || route.page === "video" ? "active" : ""} onClick={() => setMaterialsOpen((value) => !value)}>
            <span className="navigation__icon">▤</span><span><strong>Материалы</strong><small>{materialsOpen ? "Свернуть папки" : "Показать папки"}</small></span><span className="nav-chevron">{materialsOpen ? "⌄" : "›"}</span>
          </button>
          {materialsOpen && <div className="folder-navigation">
            <button className="folder-add" type="button" onClick={() => void createFolder()}>＋ Новая папка</button>
            {folders.map((folder) => <div className={`folder-nav-row${activeFolder?.id === folder.id ? " active" : ""}`} key={folder.id}>
              <button className="folder-nav-main" type="button" onClick={() => navigate(`/materials/${folder.id}`)}><span>📁</span><span><strong>{folder.name}</strong><small>{folder.document_count}</small></span></button>
              {!folder.is_system && <div className="folder-nav-actions"><button type="button" title="Переименовать" onClick={() => void renameFolder(folder)}>✎</button><button type="button" title="Удалить" onClick={() => void deleteFolder(folder)}>×</button></div>}
            </div>)}
          </div>}
          <button type="button" className={route.page === "assistant" ? "active" : ""} onClick={() => navigate("/assistant")}><span className="navigation__icon">✦</span><span><strong>Ассистент</strong><small>Ответы с цитатами</small></span></button>
          <button type="button" className={route.page === "search" ? "active" : ""} onClick={() => navigate("/search")}><span className="navigation__icon">⌕</span><span><strong>Поиск</strong><small>Dense retrieval</small></span></button>
          <button type="button" className={route.page === "system" ? "active" : ""} onClick={() => navigate("/system")}><span className="navigation__icon">◉</span><span><strong>Система</strong><small>Статус компонентов</small></span></button>
        </nav>
        <div className="sidebar__bottom"><div className="study-notice"><span>i</span><p><strong>Учебный проект</strong>Не используется для диагностики и назначения лечения.</p></div><HealthIndicator health={health} loading={healthLoading} onClick={() => navigate("/system")} /></div>
      </aside>

      {mobileMenuOpen && <button className="mobile-overlay" type="button" onClick={() => setMobileMenuOpen(false)} aria-label="Закрыть меню" />}
      <main className="main-content">
        <header className="mobile-header"><button className="menu-button" type="button" onClick={() => setMobileMenuOpen(true)}>☰</button><div className="brand brand--mobile"><div className="brand__mark">А</div><strong>Асси</strong></div><span className={`mobile-status mobile-status--${health?.status || "unknown"}`} /></header>
        <div className="content-container">
          {route.page === "home" && <section className="panel workspace-empty"><h1>Материалы</h1><p>Откройте «Материалы» слева и выберите папку.</p></section>}
          {route.page === "folder" && activeFolder && <FolderMaterialsPage folder={activeFolder} documents={documents} loading={documentsLoading} error={documentsError} refreshDocuments={refreshWorkspace} notify={notify} onOpenVideo={(document) => navigate(`/materials/${activeFolder.id}/video/${document.id}`)} />}
          {route.page === "folder" && !activeFolder && !documentsLoading && <ErrorBanner message="Папка не найдена" />}
          {route.page === "video" && <VideoPage documentId={route.videoId} onBack={() => navigate(`/materials/${route.folderId}`)} />}
          {route.page === "assistant" && <AssistantPage documents={documents} />}
          {route.page === "search" && <SearchPage documents={documents} folders={folders} />}
          {route.page === "system" && <SystemPage health={health} loading={healthLoading} refresh={refreshHealth} />}
        </div>
      </main>
      <div className="toast-region" aria-live="polite">{toasts.map((toast) => <div className={`toast toast--${toast.tone}`} key={toast.id}><span>{toast.tone === "success" ? "✓" : "!"}</span><p>{toast.message}</p><button type="button" onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))}>×</button></div>)}</div>
    </div>
  );
}
