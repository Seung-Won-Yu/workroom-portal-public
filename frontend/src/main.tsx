import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  changeOwnPassword,
  fetchAdminActivity,
  fetchAdminArchive,
  fetchAdminSearch,
  fetchAdminSummary,
  fetchAdminUser,
  fetchAgentJobs,
  fetchFile,
  fetchFolder,
  fetchSession,
} from "./api";
import type { AppView, Selection } from "./appTypes";
import { ErrorState, LoadingState, NoticeState } from "./components/Feedback";
import { AppShell, AdminSummaryPanel, AgentOutputBanner } from "./components/Shell";
import { FolderView } from "./components/Workspace";
import { DEFAULT_ADMIN_ACTIVITY, DEFAULT_ADMIN_SEARCH, DEFAULT_FILTERS, DEFAULT_TEAM_SHARED_FOLDER } from "./constants";
import type {
  AdminActivityFilters,
  AdminActivityPayload,
  AdminArchivePayload,
  AdminSearchFilters,
  AdminSearchPayload,
  AdminSummaryPayload,
  AdminUserPayload,
  AgentJobsPayload,
  FilePayload,
  FolderFilters,
  FolderPayload,
  SessionPayload,
} from "./types";
import { parentPath } from "./utils";
import "./styles.css";

const FOLDER_PAGE_SIZE = 60;
const ADMIN_OVERVIEW_OUTPUT_LIMIT = 6;

function isAbortError(err: unknown) {
  return err instanceof Error && err.name === "AbortError";
}

const AdminOverviewPanel = lazy(() => import("./components/Admin").then((module) => ({ default: module.AdminOverviewPanel })));
const AdminSearchPanel = lazy(() => import("./components/Admin").then((module) => ({ default: module.AdminSearchPanel })));
const AdminActivityPanel = lazy(() => import("./components/Admin").then((module) => ({ default: module.AdminActivityPanel })));
const AdminArchivePanel = lazy(() => import("./components/Admin").then((module) => ({ default: module.AdminArchivePanel })));
const AdminUserPanel = lazy(() => import("./components/Admin").then((module) => ({ default: module.AdminUserPanel })));

function App() {
  const [session, setSession] = useState<SessionPayload | null>(null);
  const [folder, setFolder] = useState<FolderPayload | null>(null);
  const [file, setFile] = useState<FilePayload | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [folderFilters, setFolderFilters] = useState<FolderFilters>(DEFAULT_FILTERS);
  const [adminSummary, setAdminSummary] = useState<AdminSummaryPayload | null>(null);
  const [adminSearch, setAdminSearch] = useState<AdminSearchPayload | null>(null);
  const [adminSearchFilters, setAdminSearchFilters] = useState<AdminSearchFilters>(DEFAULT_ADMIN_SEARCH);
  const [adminActivity, setAdminActivity] = useState<AdminActivityPayload | null>(null);
  const [adminActivityFilters, setAdminActivityFilters] = useState<AdminActivityFilters>(DEFAULT_ADMIN_ACTIVITY);
  const [adminArchive, setAdminArchive] = useState<AdminArchivePayload | null>(null);
  const [adminUser, setAdminUser] = useState<AdminUserPayload | null>(null);
  const [agentJobs, setAgentJobs] = useState<AgentJobsPayload | null>(null);
  const [adminUserName, setAdminUserName] = useState("");
  const [view, setView] = useState<AppView>("files");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [loadingMoreFolder, setLoadingMoreFolder] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false);

  useEffect(() => {
    let mounted = true;
    fetchSession()
      .then((payload) => {
        if (!mounted) return;
        setSession(payload);
        const firstRoot = payload.roots[0];
        const route = readInitialRoute(payload);
        if (firstRoot) {
          setFolderFilters(route.filters);
          setAdminSearchFilters(route.adminSearchFilters);
          setAdminActivityFilters(route.adminActivityFilters);
          setAdminUserName(route.adminUserName);
          setView(route.view);
          setSelection(route.selection);
        }
        if (payload.user.is_admin) {
          fetchAdminSummary().then(setAdminSummary).catch(() => undefined);
          if (route.view === "admin-search") {
            fetchAdminSearch(route.adminSearchFilters).then(setAdminSearch).catch(() => undefined);
          }
          if (route.view === "admin-activity") {
            fetchAdminActivity(route.adminActivityFilters).then(setAdminActivity).catch(() => undefined);
          }
          if (route.view === "admin-archive") {
            fetchAdminArchive().then(setAdminArchive).catch(() => undefined);
          }
          if (route.view === "admin-user" && route.adminUserName) {
            fetchAdminSearch(DEFAULT_ADMIN_SEARCH, { limit: 0 }).then(setAdminSearch).catch(() => undefined);
            fetchAdminUser(route.adminUserName).then(setAdminUser).catch(() => undefined);
          }
        }
        fetchAgentJobs({ limit: 20 }).then(setAgentJobs).catch(() => undefined);
      })
      .catch((err: Error) => mounted && setError(err.message))
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, []);

  const adminUsers = adminSearch?.users.length ? adminSearch.users : adminActivity?.users || [];

  useEffect(() => {
    if (!session || !agentJobs?.jobs.some((job) => job.status === "queued" || job.status === "running")) return;
    const timer = window.setInterval(() => {
      fetchAgentJobs({ limit: 20 }).then(setAgentJobs).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [agentJobs, session]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 2600);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    if (!session?.user.is_admin) return;
    if (view === "admin-overview") {
      const loadOverview = () => {
        if (!adminSearch) fetchAdminSearch(DEFAULT_ADMIN_SEARCH, { limit: ADMIN_OVERVIEW_OUTPUT_LIMIT }).then(setAdminSearch).catch(() => undefined);
        if (!adminActivity) fetchAdminActivity(DEFAULT_ADMIN_ACTIVITY).then(setAdminActivity).catch(() => undefined);
        if (!adminArchive) fetchAdminArchive().then(setAdminArchive).catch(() => undefined);
      };
      const scheduler = window as typeof window & {
        requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
        cancelIdleCallback?: (handle: number) => void;
      };
      const idle = scheduler.requestIdleCallback?.(loadOverview, { timeout: 1200 });
      if (!scheduler.requestIdleCallback) window.setTimeout(loadOverview, 100);
      return () => {
        if (idle) scheduler.cancelIdleCallback?.(idle);
      };
    }
    if (view === "admin-search" && (!adminSearch || adminSearch.entry_limit < 60)) {
      fetchAdminSearch(adminSearchFilters).then(setAdminSearch).catch((err: Error) => setError(err.message));
    }
    if (view === "admin-activity" && !adminActivity) {
      fetchAdminActivity(adminActivityFilters).then(setAdminActivity).catch((err: Error) => setError(err.message));
    }
    if (view === "admin-archive" && !adminArchive) {
      fetchAdminArchive().then(setAdminArchive).catch((err: Error) => setError(err.message));
    }
    if (view === "admin-user" && !adminUsers.length) {
      fetchAdminSearch(DEFAULT_ADMIN_SEARCH, { limit: 0 }).then(setAdminSearch).catch((err: Error) => setError(err.message));
    }
  }, [adminActivity, adminArchive, adminSearch, adminSearchFilters, adminActivityFilters, adminUsers.length, session, view]);

  useEffect(() => {
    if (!selection || view !== "files") return;
    let mounted = true;
    const controller = new AbortController();
    setError("");
    if (selection.type === "folder") {
      setLoading(true);
      setDetailLoading(false);
      fetchFolder(selection.root, selection.path, folderFilters, selection.path ? { limit: FOLDER_PAGE_SIZE } : undefined, controller.signal)
        .then((payload) => {
          if (!mounted) return;
          setFolder(payload);
          setFile(null);
        })
        .catch((err: Error) => {
          if (!mounted || isAbortError(err)) return;
          setError(err.message);
        })
        .finally(() => mounted && setLoading(false));
    } else {
      const nextParentPath = parentPath(selection.path);
      const canReuseFolder =
        folder?.root.id === selection.root &&
        folder.path === nextParentPath &&
        folder.filters.q === folderFilters.q &&
        folder.filters.type === folderFilters.type &&
        folder.filters.status === folderFilters.status &&
        folder.filters.sort === folderFilters.sort;
      setDetailLoading(true);
      setFile(null);
      if (canReuseFolder) {
        setLoading(false);
        fetchFile(selection.root, selection.path, controller.signal)
          .then((filePayload) => {
            if (!mounted) return;
            setFile(filePayload);
          })
          .catch((err: Error) => {
            if (!mounted || isAbortError(err)) return;
            setError(err.message);
          })
          .finally(() => mounted && setDetailLoading(false));
      } else {
        setLoading(true);
        Promise.all([
          fetchFile(selection.root, selection.path, controller.signal),
          fetchFolder(selection.root, nextParentPath, folderFilters, { limit: FOLDER_PAGE_SIZE }, controller.signal),
        ])
          .then(([filePayload, folderPayload]) => {
            if (!mounted) return;
            setFile(filePayload);
            setFolder(folderPayload);
          })
          .catch((err: Error) => {
            if (!mounted || isAbortError(err)) return;
            setError(err.message);
          })
          .finally(() => {
            if (!mounted) return;
            setLoading(false);
            setDetailLoading(false);
          });
      }
    }
    return () => {
      mounted = false;
      controller.abort();
    };
  }, [selection, folderFilters, refreshKey, view]);

  useEffect(() => {
    if (!selection || !session) return;
    const nextUrl = buildAppUrl(view, selection, folderFilters, adminSearchFilters, adminActivityFilters, adminUserName);
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (nextUrl !== currentUrl) {
      window.history.replaceState(null, "", nextUrl);
    }
  }, [selection, folderFilters, adminSearchFilters, adminActivityFilters, adminUserName, session, view]);

  const activeRoot = useMemo(() => {
    if (!session || !selection) return null;
    return session.roots.find((root) => root.id === selection.root) || session.roots[0] || null;
  }, [session, selection]);

  const globalSearchValue = view === "admin-search" ? adminSearchFilters.q : view === "files" ? folderFilters.q : "";

  function runGlobalSearch(query: string) {
    const q = query.trim();
    if (session?.user.is_admin) {
      const nextFilters = { ...DEFAULT_ADMIN_SEARCH, q };
      setView("admin-search");
      setAdminSearchFilters(nextFilters);
      fetchAdminSearch(nextFilters).then(setAdminSearch).catch((err: Error) => setError(err.message));
      return;
    }

    const targetRoot = activeRoot || session?.roots.find((root) => root.id === "personal") || session?.roots[0] || null;
    if (!targetRoot) return;
    const targetPath = view === "files" && selection?.type === "folder"
      ? selection.path
      : view === "files" && selection
        ? parentPath(selection.path)
        : "";
    setView("files");
    setSelection({ type: "folder", root: targetRoot.id, path: targetPath });
    setFolderFilters({ ...folderFilters, q });
  }

  function updateAdminSearch(filters: AdminSearchFilters) {
    setAdminSearchFilters(filters);
    fetchAdminSearch(filters).then(setAdminSearch).catch((err: Error) => setError(err.message));
  }

  function updateAdminActivity(filters: AdminActivityFilters) {
    setAdminActivityFilters(filters);
    fetchAdminActivity(filters).then(setAdminActivity).catch((err: Error) => setError(err.message));
  }

  function openAdminUser(username: string) {
    setAdminUserName(username);
    setAdminUser(null);
    setView("admin-user");
    fetchAdminUser(username).then(setAdminUser).catch((err: Error) => setError(err.message));
  }

  function refreshAdminUserData(message: string, username?: string) {
    setNotice(message);
    fetchAdminSummary().then(setAdminSummary).catch((err: Error) => setError(err.message));
    fetchAdminSearch(DEFAULT_ADMIN_SEARCH, { limit: 0 }).then(setAdminSearch).catch((err: Error) => setError(err.message));
    if (username) {
      setAdminUserName(username);
      fetchAdminUser(username).then(setAdminUser).catch((err: Error) => setError(err.message));
    }
  }

  function openAdminbotWorkspace() {
    const personalRoot = session?.roots.find((root) => root.id === "personal");
    if (!personalRoot) return;
    setView("files");
    setSelection({ type: "folder", root: personalRoot.id, path: "admin" });
  }

  function loadMoreFolder() {
    if (!folder || !selection || view !== "files" || loadingMoreFolder) return;
    setLoadingMoreFolder(true);
    fetchFolder(folder.root.id, folder.path, folderFilters, { offset: folder.entries.length, limit: FOLDER_PAGE_SIZE })
      .then((payload) =>
        setFolder({
          ...payload,
          entries: [...folder.entries, ...payload.entries],
        }),
      )
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoadingMoreFolder(false));
  }

  return (
    <AppShell
      session={session}
      activeRoot={activeRoot}
      currentPath={selection?.type === "folder" ? selection.path : selection ? parentPath(selection.path) : ""}
      view={view}
      globalSearchValue={globalSearchValue}
      onGlobalSearch={runGlobalSearch}
      onSelectRoot={(root) => {
        setView("files");
        setSelection({ type: "folder", root: root.id, path: defaultFolderPath(root.id, "") });
      }}
      onOpenFolder={(root, path) => {
        setView("files");
        setSelection({ type: "folder", root: root.id, path });
      }}
      onSelectAdminOverview={() => setView("admin-overview")}
      onSelectAdminSearch={() => setView("admin-search")}
      onSelectAdminActivity={() => setView("admin-activity")}
      onSelectAdminArchive={() => setView("admin-archive")}
      onSelectAdminUser={() => {
        setView("admin-user");
        if (!adminUserName && adminUsers[0]) openAdminUser(adminUsers[0].username);
      }}
      onOpenPasswordChange={() => setPasswordDialogOpen(true)}
    >
      {loading && !session ? <LoadingState /> : null}
      {error ? <ErrorState message={error} /> : null}
      {notice ? (
        <div className="notice-layer">
          <NoticeState message={notice} />
        </div>
      ) : null}
      {session && activeRoot && view === "files" ? <AgentOutputBanner activeRoot={activeRoot} folder={folder} file={file} /> : null}
      <Suspense fallback={<LoadingState />}>
        {session?.user.is_admin && view === "admin-overview" ? (
          <AdminOverviewPanel
            summary={adminSummary}
            search={adminSearch}
            activity={adminActivity}
            archive={adminArchive}
            onOpenSearch={() => setView("admin-search")}
            onOpenActivity={() => setView("admin-activity")}
            onOpenArchive={() => setView("admin-archive")}
            onOpenUserReport={(username?: string) => {
              if (username) {
                openAdminUser(username);
                return;
              }
              setView("admin-user");
              if (!adminUserName && adminUsers[0]) openAdminUser(adminUsers[0].username);
            }}
            onOpenAdminbot={openAdminbotWorkspace}
          />
        ) : null}
        {adminSummary && view !== "admin-overview" ? <AdminSummaryPanel summary={adminSummary} /> : null}
        {session?.user.is_admin && view === "admin-search" ? (
          <AdminSearchPanel search={adminSearch} filters={adminSearchFilters} onFiltersChange={updateAdminSearch} />
        ) : null}
        {session?.user.is_admin && view === "admin-activity" ? (
          <AdminActivityPanel
            csrfToken={session.csrf_token}
            activity={adminActivity}
            filters={adminActivityFilters}
            onFiltersChange={updateAdminActivity}
            onCleaned={(message) => {
              setNotice(message);
              fetchAdminActivity(adminActivityFilters).then(setAdminActivity).catch((err: Error) => setError(err.message));
              fetchAdminSummary().then(setAdminSummary).catch((err: Error) => setError(err.message));
            }}
          />
        ) : null}
        {session?.user.is_admin && view === "admin-archive" ? (
          <AdminArchivePanel
            csrfToken={session.csrf_token}
            archive={adminArchive}
            onRestored={(message) => {
              setNotice(message);
              fetchAdminArchive().then(setAdminArchive).catch((err: Error) => setError(err.message));
            }}
          />
        ) : null}
        {session?.user.is_admin && view === "admin-user" ? (
          <AdminUserPanel
            report={adminUser}
            selectedUsername={adminUserName}
            users={adminUsers}
            csrfToken={session.csrf_token}
            onSelectUser={openAdminUser}
            onUserChanged={refreshAdminUserData}
            onOpenActivity={(username) => {
              setView("admin-activity");
              updateAdminActivity({ ...DEFAULT_ADMIN_ACTIVITY, actor: username });
            }}
          />
        ) : null}
      </Suspense>
      {session && activeRoot && view === "files" ? (
        <FolderView
          csrfToken={session.csrf_token}
          folder={folder}
          file={file}
          loading={loading}
          detailLoading={detailLoading}
          selectedPath={selection?.type === "file" ? selection.path : ""}
          activeRoot={activeRoot}
          roots={session.roots}
          filters={folderFilters}
          onFiltersChange={setFolderFilters}
          onOpenFolder={(path) => setSelection({ type: "folder", root: activeRoot.id, path })}
          onOpenFile={(path) => setSelection({ type: "file", root: activeRoot.id, path })}
          onUploaded={(path) => {
            setNotice("업로드했습니다.");
            setSelection({ type: "file", root: activeRoot.id, path });
          }}
          onFileChanged={(message) => {
            setNotice(message);
            setRefreshKey((key) => key + 1);
          }}
          onFileMoved={(root, path, message) => {
            setNotice(message);
            setSelection({ type: "file", root, path });
          }}
          onFileArchived={(message) => {
            setNotice(message);
            setSelection({ type: "folder", root: activeRoot.id, path: folder?.path || "" });
          }}
          agentJobs={agentJobs}
          onAgentJobsChanged={(message) => {
            setNotice(message);
            fetchAgentJobs({ limit: 20 }).then(setAgentJobs).catch((err: Error) => setError(err.message));
            setRefreshKey((key) => key + 1);
          }}
          onLoadMore={loadMoreFolder}
          loadingMore={loadingMoreFolder}
        />
      ) : null}
      {session && (session.user.must_change_password || passwordDialogOpen) ? (
        <PasswordChangeDialog
          csrfToken={session.csrf_token}
          forced={session.user.must_change_password}
          onClose={() => setPasswordDialogOpen(false)}
          onChanged={() => {
            setSession({ ...session, user: { ...session.user, must_change_password: false } });
            setPasswordDialogOpen(false);
            setNotice("비밀번호를 변경했습니다.");
          }}
        />
      ) : null}
    </AppShell>
  );
}

function PasswordChangeDialog({
  csrfToken,
  forced,
  onChanged,
  onClose,
}: {
  csrfToken: string;
  forced: boolean;
  onChanged: () => void;
  onClose: () => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (newPassword.length < 10) {
      setError("새 비밀번호는 10자 이상으로 입력하세요.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("새 비밀번호 확인이 일치하지 않습니다.");
      return;
    }
    if (currentPassword === newPassword) {
      setError("현재 비밀번호와 다른 새 비밀번호를 입력하세요.");
      return;
    }
    setBusy(true);
    changeOwnPassword(csrfToken, currentPassword, newPassword, confirmPassword)
      .then(onChanged)
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false));
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form className="password-change-card" role="dialog" aria-modal="true" aria-labelledby="password-change-title" onSubmit={submit}>
        <div className="dialog-head">
          <div>
            <p className="eyebrow">{forced ? "첫 로그인 보안 설정" : "계정 보안"}</p>
            <h2 id="password-change-title">비밀번호 변경</h2>
            <p className="sub">{forced ? "관리자가 발급한 임시 비밀번호로 로그인했습니다. 계속하려면 본인만 아는 새 비밀번호로 바꾸세요." : "현재 비밀번호를 확인한 뒤 새 비밀번호로 변경합니다."}</p>
          </div>
          {!forced ? <button type="button" className="icon-btn" onClick={onClose} aria-label="닫기">×</button> : null}
        </div>
        <label className="field">
          <span>현재 비밀번호</span>
          <input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoComplete="current-password" autoFocus />
        </label>
        <label className="field">
          <span>새 비밀번호</span>
          <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" minLength={10} />
        </label>
        <label className="field">
          <span>새 비밀번호 확인</span>
          <input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" minLength={10} />
        </label>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <div className="dialog-actions">
          {!forced ? <button type="button" className="btn" onClick={onClose} disabled={busy}>취소</button> : null}
          <button type="submit" className="btn ink" disabled={busy}>{busy ? "변경 중" : "비밀번호 변경"}</button>
        </div>
      </form>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);

function readInitialRoute(session: SessionPayload): {
  selection: Selection;
  view: AppView;
  filters: FolderFilters;
  adminSearchFilters: AdminSearchFilters;
  adminActivityFilters: AdminActivityFilters;
  adminUserName: string;
} {
  const params = new URLSearchParams(window.location.search);
  const firstRoot = session.roots[0];
  const requestedRoot = params.get("root") || firstRoot?.id || "";
  const root = session.roots.some((item) => item.id === requestedRoot) ? requestedRoot : firstRoot?.id || "";
  const filePath = params.get("file") || "";
  const folderPath = params.get("path") || "";
  const deprecatedPersonalSharedPath = root === "personal" && isDeprecatedPersonalSharedPath(filePath || folderPath);
  const hasFileRoute = params.has("root") || params.has("path") || params.has("file");
  const requestedView = params.get("view") || (session.user.is_admin && !hasFileRoute ? "admin-overview" : "files");
  const view = session.user.is_admin && isAppView(requestedView) ? requestedView : "files";
  return {
    view,
    selection: deprecatedPersonalSharedPath
      ? { type: "folder", root, path: "" }
      : filePath
        ? { type: "file", root, path: filePath }
        : { type: "folder", root, path: defaultFolderPath(root, folderPath) },
    filters: view === "files" ? {
      q: params.get("q") || DEFAULT_FILTERS.q,
      type: params.get("type") || DEFAULT_FILTERS.type,
      status: params.get("status") || DEFAULT_FILTERS.status,
      sort: params.get("sort") || DEFAULT_FILTERS.sort,
    } : DEFAULT_FILTERS,
    adminSearchFilters: {
      q: view === "admin-search" ? params.get("q") || DEFAULT_ADMIN_SEARCH.q : DEFAULT_ADMIN_SEARCH.q,
      type: view === "admin-search" ? params.get("type") || DEFAULT_ADMIN_SEARCH.type : DEFAULT_ADMIN_SEARCH.type,
      status: view === "admin-search" ? params.get("status") || DEFAULT_ADMIN_SEARCH.status : DEFAULT_ADMIN_SEARCH.status,
      owner: view === "admin-search" ? params.get("owner") || DEFAULT_ADMIN_SEARCH.owner : DEFAULT_ADMIN_SEARCH.owner,
      team: view === "admin-search" ? params.get("team") || DEFAULT_ADMIN_SEARCH.team : DEFAULT_ADMIN_SEARCH.team,
      scope: view === "admin-search" ? params.get("scope") || DEFAULT_ADMIN_SEARCH.scope : DEFAULT_ADMIN_SEARCH.scope,
      sort: view === "admin-search" ? params.get("sort") || DEFAULT_ADMIN_SEARCH.sort : DEFAULT_ADMIN_SEARCH.sort,
    },
    adminActivityFilters: {
      actor: view === "admin-activity" ? params.get("actor") || DEFAULT_ADMIN_ACTIVITY.actor : DEFAULT_ADMIN_ACTIVITY.actor,
      action: view === "admin-activity" ? params.get("action") || DEFAULT_ADMIN_ACTIVITY.action : DEFAULT_ADMIN_ACTIVITY.action,
      team: view === "admin-activity" ? params.get("team") || DEFAULT_ADMIN_ACTIVITY.team : DEFAULT_ADMIN_ACTIVITY.team,
      q: view === "admin-activity" ? params.get("q") || DEFAULT_ADMIN_ACTIVITY.q : DEFAULT_ADMIN_ACTIVITY.q,
      include_tests: view === "admin-activity" ? params.get("include_tests") || DEFAULT_ADMIN_ACTIVITY.include_tests : DEFAULT_ADMIN_ACTIVITY.include_tests,
    },
    adminUserName: view === "admin-user" ? params.get("username") || "" : "",
  };
}

function defaultFolderPath(root: string, path: string) {
  if (root === "team_shared" && !path) return DEFAULT_TEAM_SHARED_FOLDER;
  return path;
}

function isDeprecatedPersonalSharedPath(path: string) {
  return path.split("/").filter(Boolean)[0] === "shared";
}

function buildAppUrl(
  view: AppView,
  selection: Selection,
  filters: FolderFilters,
  adminSearchFilters: AdminSearchFilters,
  adminActivityFilters: AdminActivityFilters,
  adminUserName: string,
) {
  const params = new URLSearchParams();
  if (view !== "files") {
    params.set("view", view);
  }
  if (view === "files" && selection.type === "file") {
    params.set("root", selection.root);
    params.set("file", selection.path);
  } else if (view === "files" && selection.path) {
    params.set("root", selection.root);
    params.set("path", selection.path);
  } else if (view === "files") {
    params.set("root", selection.root);
  }
  if (view === "files") {
    appendChangedParams(params, filters, DEFAULT_FILTERS);
  } else if (view === "admin-search") {
    appendChangedParams(params, adminSearchFilters, DEFAULT_ADMIN_SEARCH);
  } else if (view === "admin-activity") {
    appendChangedParams(params, adminActivityFilters, DEFAULT_ADMIN_ACTIVITY);
  } else if (view === "admin-user" && adminUserName) {
    params.set("username", adminUserName);
  }
  const query = params.toString();
  return query ? `/app?${query}` : "/app";
}

function appendChangedParams<T extends Record<string, string>>(params: URLSearchParams, values: T, defaults: T) {
  Object.entries(values).forEach(([key, value]) => {
    if (value && value !== defaults[key]) {
      params.set(key, value);
    }
  });
}

function isAppView(value: string): value is AppView {
  return value === "files" || value === "admin-overview" || value === "admin-search" || value === "admin-activity" || value === "admin-archive" || value === "admin-user";
}
