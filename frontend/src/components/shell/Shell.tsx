import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { AppView } from "../../appTypes";
import { DEFAULT_TEAM_SHARED_FOLDER, SHARE_TARGETS } from "../../constants";
import type { AdminSummaryPayload, RootInfo, SessionPayload } from "../../types";

// Icons
const I = {
  home: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 11 12 4l9 7" /><path d="M5 10v9h14v-9" />
    </svg>
  ),
  folder: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  ),
  dashboard: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="8" height="9" rx="1.5" /><rect x="13" y="3" width="8" height="5" rx="1.5" />
      <rect x="13" y="10" width="8" height="11" rx="1.5" /><rect x="3" y="14" width="8" height="7" rx="1.5" />
    </svg>
  ),
  inbox: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 13V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v7M3 13h5l2 3h4l2-3h5M3 13v5a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5" />
    </svg>
  ),
  activity: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 12h4l3-7 4 14 3-7h4" />
    </svg>
  ),
  archive: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="4" rx="1" />
      <path d="M5 8v11a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8M10 13h4" />
    </svg>
  ),
  users: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.7-3.4 3.3-5 6.5-5s5.8 1.6 6.5 5" />
      <circle cx="17" cy="9" r="2.5" /><path d="M15 14c2.8 0 5 1.2 6 4" />
    </svg>
  ),
  share: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" />
      <path d="m8.6 13.6 6.8 3.9M15.4 6.5l-6.8 3.9" />
    </svg>
  ),
  search: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
    </svg>
  ),
  refresh: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12a9 9 0 0 1-15.5 6.2M3 12A9 9 0 0 1 18.5 5.8" /><path d="M18 3v4h4M6 21v-4H2" />
    </svg>
  ),
  bell: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" />
    </svg>
  ),
  key: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="7.5" cy="15.5" r="4.5" /><path d="M10.7 12.3 21 2M15 7l2 2M18 4l2 2" />
    </svg>
  ),
  logout: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M16 17l5-5-5-5M21 12H9M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
    </svg>
  ),
};

function rootIcon(root: RootInfo) {
  const id = root.id;
  if (id === "personal") return I.folder();
  if (id === "team_shared" || id === "shared") return I.share();
  if (id === "all") return I.users();
  return I.folder();
}

function folderIcon(path: string) {
  if (path === "admin") return I.dashboard();
  if (path === "research") return I.search();
  if (path === "dev") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="m8 9-4 3 4 3M16 9l4 3-4 3M14 5l-4 14" />
      </svg>
    );
  }
  if (path === "summary") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h4" />
      </svg>
    );
  }
  if (path === "shared") return I.share();
  return I.folder();
}

export function AppShell({
  session,
  activeRoot,
  currentPath,
  view,
  children,
  globalSearchValue,
  onGlobalSearch,
  onSelectRoot,
  onOpenFolder,
  onSelectAdminOverview,
  onSelectAdminSearch,
  onSelectAdminActivity,
  onSelectAdminArchive,
  onSelectAdminUser,
  onOpenPasswordChange,
}: {
  session: SessionPayload | null;
  activeRoot: RootInfo | null;
  currentPath: string;
  view: AppView;
  children: ReactNode;
  globalSearchValue: string;
  onGlobalSearch: (query: string) => void;
  onSelectRoot: (root: RootInfo) => void;
  onOpenFolder: (root: RootInfo, path: string) => void;
  onSelectAdminOverview: () => void;
  onSelectAdminSearch: () => void;
  onSelectAdminActivity: () => void;
  onSelectAdminArchive: () => void;
  onSelectAdminUser: () => void;
  onOpenPasswordChange: () => void;
}) {
  const crumbs = buildCrumbs(view, activeRoot, currentPath);
  const [collapsed, setCollapsed] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [searchDraft, setSearchDraft] = useState(globalSearchValue);
  const workspaceRoots = session?.roots.filter((root) => root.id !== "all") || [];
  const personalRoot = workspaceRoots.find((root) => root.id === "personal");
  const teamRoots = workspaceRoots.filter((root) => root.id !== "personal");
  const adminRoot = session?.roots.find((root) => root.id === "all");

  useEffect(() => {
    setSearchDraft(globalSearchValue);
  }, [globalSearchValue]);

  useEffect(() => {
    function focusSearch(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
      }
    }
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);

  function submitGlobalSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onGlobalSearch(searchDraft);
  }

  return (
    <div className="app" data-sidebar={collapsed ? "collapsed" : "expanded"}>
      <aside className="sidebar" aria-label="포털 내비게이션">
        <button
          type="button"
          className="sidebar-collapse-btn"
          onClick={() => setCollapsed((value) => !value)}
          aria-label={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
        >
          {collapsed ? "›" : "‹"}
        </button>
        <div className="sidebar-brand">
          <div className="brand-mark">e.</div>
          <div className="brand-name">
            <strong>Workroom Portal</strong>
            <span>에이전트 산출물 포털</span>
          </div>
        </div>
        <div className="sidebar-body">
          {workspaceRoots.length ? (
            <div className="nav-group">
              <div className="nav-group-label">내 작업공간</div>
              {personalRoot ? (
                <div className="nav-root-group">
                  <button
                    type="button"
                    className={`nav-item nav-parent ${view === "files" && personalRoot.id === activeRoot?.id && !currentPath ? "active" : ""}`}
                    onClick={() => onSelectRoot(personalRoot)}
                  >
                    <span className="nav-icon">{I.home()}</span>
                    <span>내 작업공간</span>
                    <span />
                  </button>
                  <div className="nav-subtree" aria-label="봇 산출물 폴더">
                    {BOT_OUTPUT_FOLDERS.map((folder) => (
                      <button
                        key={folder.path}
                        type="button"
                        className={`nav-item nav-subitem ${
                          view === "files" && personalRoot.id === activeRoot?.id && firstPath(currentPath) === folder.path ? "active" : ""
                        }`}
                        onClick={() => onOpenFolder(personalRoot, folder.path)}
                      >
                        <span className="nav-icon">{folderIcon(folder.path)}</span>
                        <span>{folder.label}</span>
                        <span />
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              {teamRoots.map((root) => {
                const active = view === "files" && root.id === activeRoot?.id;
                return (
                  <div key={root.id} className="nav-root-group">
                    <button
                      type="button"
                      className={`nav-item nav-parent ${active && (root.id === "team_shared" || !currentPath) ? "active" : ""}`}
                      onClick={() => {
                        if (root.id === "team_shared") {
                          onOpenFolder(root, DEFAULT_TEAM_SHARED_FOLDER);
                          return;
                        }
                        onSelectRoot(root);
                      }}
                    >
                      <span className="nav-icon">{rootIcon(root)}</span>
                      <span>{rootNavLabel(root)}</span>
                      <span />
                    </button>
                  </div>
                );
              })}
            </div>
          ) : null}

          {session?.user.is_admin ? (
            <div className="nav-group">
              <div className="nav-group-label">관리</div>
              {adminRoot ? (
                <button type="button" className={`nav-item ${view === "files" && activeRoot?.id === "all" ? "active" : ""}`} onClick={() => onSelectRoot(adminRoot)}>
                  <span className="nav-icon">{I.users()}</span><span>전체 작업공간</span><span />
                </button>
              ) : null}
              <button type="button" className={`nav-item ${view === "admin-overview" ? "active" : ""}`} onClick={onSelectAdminOverview}>
                <span className="nav-icon">{I.dashboard()}</span><span>관리자 대시보드</span><span />
              </button>
              {personalRoot ? (
                <button
                  type="button"
                  className={`nav-item ${view === "files" && activeRoot?.id === "personal" && firstPath(currentPath) === "admin" ? "active" : ""}`}
                  onClick={() => onOpenFolder(personalRoot, "admin")}
                >
                  <span className="nav-icon">{I.dashboard()}</span><span>Adminbot</span><span />
                </button>
              ) : null}
              <button type="button" className={`nav-item ${view === "admin-search" ? "active" : ""}`} onClick={onSelectAdminSearch}>
                <span className="nav-icon">{I.inbox()}</span><span>전체 산출물</span><span />
              </button>
              <button type="button" className={`nav-item ${view === "admin-activity" ? "active" : ""}`} onClick={onSelectAdminActivity}>
                <span className="nav-icon">{I.activity()}</span><span>작업 기록</span><span />
              </button>
              <button type="button" className={`nav-item ${view === "admin-archive" ? "active" : ""}`} onClick={onSelectAdminArchive}>
                <span className="nav-icon">{I.archive()}</span><span>보관함</span><span />
              </button>
              <button type="button" className={`nav-item ${view === "admin-user" ? "active" : ""}`} onClick={onSelectAdminUser}>
                <span className="nav-icon">{I.users()}</span><span>사용자 관리</span><span />
              </button>
            </div>
          ) : null}
        </div>
        <div className="sidebar-foot">
          <div className="avatar">{session?.user.name?.[0] || "?"}</div>
          <div className="who">
            <strong>{session?.user.name || "불러오는 중"}</strong>
            <span>{session?.user.team || ""}</span>
          </div>
          <div className="sidebar-foot-actions">
            <button className="logout" type="button" title="비밀번호 변경" onClick={onOpenPasswordChange}>{I.key()}</button>
            <a className="logout" href="/logout" title="로그아웃">{I.logout()}</a>
          </div>
        </div>
      </aside>
      <div className="main-area">
        <div className="topbar">
          <div className="crumbs">
            {crumbs.map((c, i) => (
              <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                {i > 0 ? <span className="sep">/</span> : null}
                {i === crumbs.length - 1 ? <strong className="ellipsize">{c}</strong> : <span className="ellipsize">{c}</span>}
              </span>
            ))}
          </div>
          <form className="search-box" role="search" aria-label="전체 검색" onSubmit={submitGlobalSearch}>
            {I.search()}
            <input
              ref={searchInputRef}
              type="search"
              placeholder="파일, 사용자, 폴더 검색..."
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
            />
            <kbd>⌘K</kbd>
          </form>
          <div className="topbar-actions">
          <button type="button" className="icon-button" aria-label="새로고침" onClick={() => window.location.reload()}>{I.refresh()}</button>
          <button type="button" className="icon-button" aria-label="알림">{I.bell()}<span className="dot" /></button>
          </div>
        </div>
        <main className="page">{children}</main>
      </div>
    </div>
  );
}

const BOT_OUTPUT_FOLDERS = [
  { path: "research", label: "리서치" },
  { path: "dev", label: "개발 산출물" },
  { path: "summary", label: "요약·보고" },
];

function firstPath(path: string) {
  return path.split("/").filter(Boolean)[0] || "";
}

function folderLabel(path: string) {
  const first = firstPath(path);
  if (first === "admin") return "Adminbot";
  return BOT_OUTPUT_FOLDERS.find((folder) => folder.path === first)?.label || "";
}

function rootNavLabel(root: RootInfo) {
  if (root.id === "team_shared") return "팀 공유";
  return root.label;
}

function sharedFolderLabel(path: string) {
  const first = firstPath(path);
  return SHARE_TARGETS.find(([value]) => value === first)?.[1] || "";
}

function buildCrumbs(view: AppView, activeRoot: RootInfo | null, currentPath: string) {
  if (view === "files") {
    if (activeRoot?.id === "personal") return folderLabel(currentPath) ? ["내 작업공간", folderLabel(currentPath)] : ["내 작업공간"];
    if (activeRoot?.id === "team_shared") {
      const label = sharedFolderLabel(currentPath);
      return label ? ["팀 공유", label] : ["팀 공유"];
    }
    return ["내 작업공간", activeRoot?.label || "파일"];
  }
  if (view === "admin-overview") return ["관리", "대시보드"];
  if (view === "admin-search") return ["관리", "전체 산출물"];
  if (view === "admin-activity") return ["관리", "작업 기록"];
  if (view === "admin-archive") return ["관리", "보관함"];
  if (view === "admin-user") return ["관리", "사용자 관리"];
  return ["Workroom Portal"];
}

// Banner kept for backwards compatibility — currently unused in shell.
export function AgentOutputBanner(_props: { activeRoot: RootInfo; folder: unknown; file: unknown }) {
  return null;
}

export function AdminSummaryPanel({ summary }: { summary: AdminSummaryPayload }) {
  const latest = summary.recent_events[0];
  return (
    <div className="priority-strip" aria-label="관리자 요약">
      <strong>관리자 요약</strong>
      <span className="alarm">팀 {summary.team_count}개</span>
      <span className="alarm">구성원 {summary.member_count}명</span>
      {latest ? (
        <span className="alarm">최근: {latest.action_label} · {latest.actor} · {latest.time}</span>
      ) : (
        <span className="alarm">최근 기록 없음</span>
      )}
    </div>
  );
}
