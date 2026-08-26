import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties, type ChangeEvent, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Archive, CheckCircle2, Clock, Download, Eye, FileText, FolderOpen, Maximize2, Minimize2, Share2, ShieldCheck } from "lucide-react";
import { archiveItem, copyToPersonal, createAgentJob, fetchFolder, hideAgentSession, renameItem, shareItem, updateStatus, uploadFile } from "../../api";
import { DEFAULT_FILTERS, SHARE_TARGETS, SORT_OPTIONS, STATUS_OPTIONS, TYPE_OPTIONS } from "../../constants";
import type { AgentJob, AgentJobsPayload, FilePayload, FolderEntry, FolderFilters, FolderPayload, RootInfo } from "../../types";
import { firstPathSegment, parentPath, shareLabel } from "../../utils";
import { LoadingState } from "../Feedback";
import { MarkdownMessage } from "./MarkdownMessage";

const FALLBACK_AGENT_ROLES: AgentJobsPayload["roles"] = [
  {
    role: "research",
    label: "리서치 요청",
    profile: "researchbot",
    description: "자료 조사와 비교",
    folder: "research",
    placeholder: "예: 이 주제의 자료를 조사하고 결론, 근거, 출처, 다음 액션으로 정리해줘.",
    output_hint: "짧은 질문은 대화로 답하고, 조사 요청은 리서치 문서로 저장합니다.",
    templates: ["이 주제에 대해 핵심 결론, 비교표, 출처, 다음 액션을 정리해줘."],
  },
  {
    role: "dev",
    label: "개발 요청",
    profile: "devbot",
    description: "구현과 테스트",
    folder: "dev",
    placeholder: "예: 선택한 참고자료를 기준으로 구현 계획과 필요한 코드, 테스트 방법을 만들어줘.",
    output_hint: "짧은 질문은 대화로 답하고, 구현 요청은 개발 산출물로 저장합니다.",
    templates: ["구현 범위를 작게 나누고 필요한 코드와 실행 방법을 만들어줘."],
  },
  {
    role: "summary",
    label: "요약/보고 요청",
    profile: "summarybot",
    description: "정리와 보고서",
    folder: "summary",
    placeholder: "예: 참고자료를 1페이지 보고서와 액션아이템으로 정리해줘.",
    output_hint: "짧은 질문은 대화로 답하고, 정리 요청은 요약 보고서로 저장합니다.",
    templates: ["핵심 요약, 결정사항, 액션아이템, 리스크를 정리해줘."],
  },
  {
    role: "admin",
    label: "Adminbot 요청",
    profile: "adminbot",
    description: "Hermes 운영과 권한 점검",
    folder: "admin",
    placeholder: "예: Hermes 봇 역할, 웹 계정 권한, 개인 작업공간 흐름을 점검하고 운영 변경안을 정리해줘.",
    output_hint: "짧은 질문은 대화로 답하고, 운영 요청은 관리자 점검 문서로 저장합니다.",
    templates: ["현재 포털과 Hermes 봇 운영 흐름을 점검하고, 권한/개인 작업공간/폴더 기준으로 개선안을 정리해줘."],
  },
];

const PERSONAL_COPY_TARGETS = [
  { value: "research", label: "리서치" },
  { value: "dev", label: "개발 산출물" },
  { value: "summary", label: "요약/보고" },
];

const AGENT_REFERENCE_FOLDERS = [
  { value: "research", label: "내 리서치" },
  { value: "dev", label: "내 개발 산출물" },
  { value: "summary", label: "내 요약·보고" },
] as const;
const MAX_AGENT_REFERENCES = 5;

type AgentReference = {
  root: string;
  path: string;
  label: string;
};

type ReferenceSource = {
  id: string;
  root: string;
  basePath: string;
  label: string;
  description: string;
};

const NEW_AGENT_SESSION_ID = "__new_agent_session__";
const OUTPUT_MIN_WIDTH = 34;
const DEFAULT_OUTPUT_WIDTH = 40;
const WIDE_OUTPUT_WIDTH = 54;
const OUTPUT_MAX_WIDTH = 58;
const OUTPUT_WIDTH_STORAGE_KEY = "workroom.agent.outputWidth";

function clampNumber(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function kindClass(kind: string): string {
  if (["image", "img", "png", "jpg", "jpeg", "gif", "svg", "webp"].includes(kind)) return "image";
  if (["code", "py", "ts", "tsx", "js", "jsx", "html", "json", "yaml", "yml"].includes(kind)) return "code";
  if (["document", "doc", "docx", "pdf", "md", "txt", "csv", "xlsx"].includes(kind)) return "doc";
  if (["video", "mp4", "mov", "webm"].includes(kind)) return "video";
  if (["archive", "zip", "tar", "gz"].includes(kind)) return "archive";
  if (kind === "folder") return "folder";
  return "";
}

function statusClass(status: string) {
  return status || "";
}

function firstFolder(path: string) {
  return path.split("/").filter(Boolean)[0] || "";
}

function workspaceTitle(activeRoot: RootInfo, folder: FolderPayload | null) {
  const first = firstFolder(folder?.path || "");
  if (activeRoot.id === "team_shared") {
    return SHARE_TARGETS.find(([value]) => value === first)?.[1] || activeRoot.label;
  }
  if (activeRoot.id !== "personal") return activeRoot.label;
  if (first === "research") return "리서치";
  if (first === "dev") return "개발 산출물";
  if (first === "summary") return "요약·보고";
  if (first === "admin") return "Adminbot";
  return "내 작업공간";
}

function workspaceDescription(folder: FolderPayload | null) {
  const first = firstFolder(folder?.path || "");
  if (first === "research") return "조사 자료와 수집 파일";
  if (first === "dev") return "코드, 스크립트, 자동화 결과";
  if (first === "summary") return "요약본과 보고 자료";
  if (first === "admin") return "Hermes 운영, 웹 권한, 봇 설정 점검";
  return "에이전트가 만든 파일";
}

function teamSharedDescription(path: string) {
  const first = firstFolder(path);
  if (first === "research") return "팀원이 함께 보는 조사 자료와 수집 파일";
  if (first === "dev") return "팀원이 함께 보는 코드, 스크립트, 자동화 결과";
  if (first === "summary") return "팀원이 함께 보는 요약본과 보고 자료";
  if (first === "handoff") return "팀원이 함께 보는 인수인계 자료";
  return "개인 작업공간에서 팀 공유로 이동한 산출물";
}

function conversationTabLabel(folder: FolderPayload | null) {
  const first = firstFolder(folder?.path || "");
  if (first === "research") return "리서치봇과 대화";
  if (first === "dev") return "개발봇과 대화";
  if (first === "summary") return "요약봇과 대화";
  if (first === "admin") return "Adminbot과 대화";
  return "에이전트와 대화";
}

function agentDisplayName(role: AgentJobsPayload["roles"][number] | undefined) {
  if (!role) return "에이전트";
  if (role.role === "research") return "리서치봇";
  if (role.role === "dev") return "개발봇";
  if (role.role === "summary") return "요약봇";
  if (role.role === "admin") return "Adminbot";
  return role.label.replace(" 요청", "봇");
}

function sessionTitle(prompt: string) {
  const title = prompt.trim().replace(/\s+/g, " ");
  return title ? `${title.slice(0, 32)}${title.length > 32 ? "..." : ""}` : "새 작업";
}

function jobTime(job: AgentJob) {
  return job.created_at || job.started_at || job.updated_at || "";
}

function fileNameFromPath(path: string) {
  return path.split("/").filter(Boolean).pop() || path || "산출물";
}

function extensionFromPath(path: string) {
  const name = fileNameFromPath(path);
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index + 1).toLowerCase() : "";
}

function outputKind(path: string) {
  const ext = extensionFromPath(path);
  if (["md", "markdown", "txt"].includes(ext)) return { label: ext === "txt" ? "TXT" : "MD", kind: "doc", previewable: true };
  if (["json", "csv", "html", "htm", "js", "ts", "tsx", "jsx", "py", "yml", "yaml"].includes(ext)) return { label: ext.toUpperCase(), kind: "code", previewable: true };
  if (["png", "jpg", "jpeg", "gif", "svg", "webp"].includes(ext)) return { label: "IMG", kind: "image", previewable: true };
  if (ext === "pdf") return { label: "PDF", kind: "doc", previewable: true };
  if (["zip", "tar", "gz", "7z"].includes(ext)) return { label: "ZIP", kind: "archive", previewable: false };
  return { label: ext ? ext.toUpperCase().slice(0, 4) : "FILE", kind: "doc", previewable: false };
}

function portalAssetUrl(pathname: "/preview" | "/download", root: string, path: string) {
  const params = new URLSearchParams({ root, path });
  return `${pathname}?${params.toString()}`;
}

function agentReferenceSources(roots: RootInfo[]): ReferenceSource[] {
  const sources: ReferenceSource[] = [];
  if (roots.some((root) => root.id === "personal")) {
    AGENT_REFERENCE_FOLDERS.forEach((folder) => {
      sources.push({
        id: `personal:${folder.value}`,
        root: "personal",
        basePath: folder.value,
        label: folder.label,
        description: "내 개인 작업공간",
      });
    });
  }
  if (roots.some((root) => root.id === "team_shared")) {
    sources.push({
      id: "team_shared:",
      root: "team_shared",
      basePath: "",
      label: "팀 공유",
      description: "같은 팀원과 공유된 자료",
    });
  }
  return sources;
}

function referenceKey(reference: Pick<AgentReference, "root" | "path">) {
  return `${reference.root}:${reference.path}`;
}

function sourceForReferences(sources: ReferenceSource[], references: AgentReference[]) {
  const reference = references[0];
  if (!reference) return sources[0];
  return sources.find((source) => (
    source.root === reference.root
    && (!source.basePath || reference.path === source.basePath || reference.path.startsWith(`${source.basePath}/`))
  )) || sources[0];
}

function referencesFromFile(file: FilePayload | null): AgentReference[] {
  if (!file) return [];
  if (file.root.id === "team_shared") {
    return [{ root: file.root.id, path: file.path, label: `팀 공유 · ${file.name}` }];
  }
  if (file.root.id !== "personal") return [];
  const first = firstFolder(file.path);
  const folder = AGENT_REFERENCE_FOLDERS.find((item) => item.value === first);
  if (!folder) return [];
  return [{ root: file.root.id, path: file.path, label: `${folder.label} · ${file.name}` }];
}

export function FolderView({
  csrfToken,
  folder,
  file,
  loading,
  detailLoading,
  selectedPath,
  activeRoot,
  roots,
  filters,
  onFiltersChange,
  onOpenFolder,
  onOpenFile,
  onUploaded,
  onFileChanged,
  onFileMoved,
  onFileArchived,
  agentJobs,
  onAgentJobsChanged,
  onLoadMore,
  loadingMore,
}: {
  csrfToken: string;
  folder: FolderPayload | null;
  file: FilePayload | null;
  loading: boolean;
  detailLoading: boolean;
  selectedPath: string;
  activeRoot: RootInfo;
  roots: RootInfo[];
  filters: FolderFilters;
  onFiltersChange: (filters: FolderFilters) => void;
  onOpenFolder: (path: string) => void;
  onOpenFile: (path: string) => void;
  onUploaded: (path: string) => void;
  onFileChanged: (message: string) => void;
  onFileMoved: (root: string, path: string, message: string) => void;
  onFileArchived: (message: string) => void;
  agentJobs: AgentJobsPayload | null;
  onAgentJobsChanged: (message: string) => void;
  onLoadMore: () => void;
  loadingMore: boolean;
}) {
  const [mobilePane, setMobilePane] = useState<"list" | "detail">("list");
  const [activeTab, setActiveTab] = useState<"conversation" | "files">("files");
  const [agentDialogOpen, setAgentDialogOpen] = useState(false);
  const previewPaneRef = useRef<HTMLElement | null>(null);
  const previousConversationFolderRef = useRef("");
  const isRootOverview = Boolean(folder && !folder.path && !file);
  const title = workspaceTitle(activeRoot, folder);
  const description = activeRoot.id === "team_shared" ? teamSharedDescription(folder?.path || "") : workspaceDescription(folder);
  const subtitle = activeRoot.id === "personal"
    ? `${description} · ${folder ? `${folder.entry_count.toLocaleString()}개 산출물` : "불러오는 중"}`
    : `${folder?.title_path || "/"} · ${description} · ${folder ? `${folder.entry_count.toLocaleString()}개 산출물` : "불러오는 중"}`;
  const currentFolder = firstFolder(file?.path || folder?.path || "");
  const canUseAgentConversation = activeRoot.id === "personal";
  const currentRole = suggestedRole(folder, file);
  const conversationCount = canUseAgentConversation
    ? new Set((agentJobs?.jobs || []).filter((job) => job.role === currentRole).map((job) => job.session_id || job.id)).size
    : 0;

  useEffect(() => {
    if (file) setMobilePane("detail");
  }, [file?.path]);

  useEffect(() => {
    if (!canUseAgentConversation && activeTab === "conversation") {
      setActiveTab("files");
    }
  }, [activeTab, canUseAgentConversation]);

  useEffect(() => {
    const key = `${activeRoot.id}:${currentFolder}:${file?.path || ""}`;
    if (previousConversationFolderRef.current === key) return;
    previousConversationFolderRef.current = key;
    if (canUseAgentConversation && currentFolder === "admin" && !file) {
      setActiveTab("conversation");
    }
  }, [activeRoot.id, canUseAgentConversation, currentFolder, file?.path]);

  useEffect(() => {
    if (!file || !previewPaneRef.current || window.innerWidth > 920) return;
    window.requestAnimationFrame(() => {
      previewPaneRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  }, [file?.path]);

  if (isRootOverview && folder) {
    return <RootOverview root={activeRoot} folder={folder} onOpenFolder={onOpenFolder} />;
  }

  return (
    <>
      {canUseAgentConversation ? (
        <div className="page-tabs" role="tablist" aria-label="작업공간 보기">
          <button
            type="button"
            className={`page-tab ${activeTab === "conversation" ? "active" : ""}`}
            role="tab"
            aria-selected={activeTab === "conversation"}
            onClick={() => setActiveTab("conversation")}
          >
            {conversationTabLabel(folder)}
            <span className="count">{conversationCount}</span>
          </button>
          <button
            type="button"
            className={`page-tab ${activeTab === "files" ? "active" : ""}`}
            role="tab"
            aria-selected={activeTab === "files"}
            onClick={() => setActiveTab("files")}
          >
            파일 보기
            <span className="count">{folder?.entry_count.toLocaleString() || 0}</span>
          </button>
        </div>
      ) : null}
      {canUseAgentConversation && activeTab === "conversation" ? (
        <AgentConversationPanel
          csrfToken={csrfToken}
          folder={folder}
          file={file}
          activeRoot={activeRoot}
          roots={roots}
          jobs={agentJobs}
          onCreated={onAgentJobsChanged}
          onOpenFile={onOpenFile}
        />
      ) : (
        <>
      <div className="page-head">
        <div>
          <p className="eyebrow">{activeRoot.kind_label}</p>
          <h1>{title}</h1>
          <p className="sub">{subtitle}</p>
        </div>
        <div className="actions">
          {folder?.path ? (
            <button className="btn" onClick={() => onOpenFolder(parentPath(folder.path))}>상위 폴더</button>
          ) : null}
          {folder ? <a className="btn" href={folder.download_url}>ZIP 다운로드</a> : null}
          {folder?.can_upload ? <UploadAction csrfToken={csrfToken} folder={folder} onUploaded={onUploaded} /> : null}
        </div>
      </div>
      {activeRoot.id === "team_shared" ? (
        <TeamSharedSwitcher
          currentPath={folder?.path || file?.path || ""}
          onOpenFolder={onOpenFolder}
        />
      ) : null}

      <div className="mobile-pane-switch" role="tablist">
        <button type="button" className={mobilePane === "list" ? "active" : ""} onClick={() => setMobilePane("list")}>목록</button>
        <button type="button" className={mobilePane === "detail" ? "active" : ""} onClick={() => setMobilePane("detail")} disabled={!file}>상세</button>
      </div>

      <div className={`workspace ${mobilePane}-active`}>
        <section className="list-pane" aria-busy={loading}>
          {folder ? (
            <FilterBar
              filters={filters}
              onFiltersChange={onFiltersChange}
              entryCount={folder.entry_count}
            />
          ) : null}
          {folder ? (
            <EntryBrowser
              entries={folder.entries}
              selectedPath={selectedPath || file?.path || ""}
              totalCount={folder.entry_count}
              hasMore={folder.has_more}
              onLoadMore={onLoadMore}
              loadingMore={loadingMore}
              onOpenFolder={(path) => { setMobilePane("list"); onOpenFolder(path); }}
              onOpenFile={(path) => { setMobilePane("detail"); onOpenFile(path); }}
              emptyText={activeRoot.id === "team_shared" ? "개인 작업공간에서 팀 공유로 이동한 파일이 여기에 표시됩니다." : undefined}
            />
          ) : (
            <LoadingState />
          )}
        </section>
        <aside className="preview-pane" ref={previewPaneRef}>
          {detailLoading ? (
            <LoadingState />
          ) : file ? (
            <FileDetail
              csrfToken={csrfToken}
              file={file}
              onChanged={onFileChanged}
              onMoved={onFileMoved}
              onArchived={onFileArchived}
            />
          ) : (
            <EmptyDetail activeRoot={activeRoot} />
          )}
        </aside>
      </div>
        </>
      )}
      {agentDialogOpen ? (
        <AgentRequestDialog
          csrfToken={csrfToken}
          folder={folder}
          file={file}
          roots={roots}
          roles={agentJobs?.roles || []}
          onClose={() => setAgentDialogOpen(false)}
          onCreated={(message) => {
            setAgentDialogOpen(false);
            onAgentJobsChanged(message);
          }}
        />
      ) : null}
    </>
  );
}

function suggestedRole(folder: FolderPayload | null, file: FilePayload | null) {
  const first = firstFolder(file?.path || folder?.path || "");
  if (first === "dev" || first === "research" || first === "summary" || first === "admin") return first;
  return "research";
}

function AgentConversationPanel({
  csrfToken,
  folder,
  file,
  activeRoot,
  roots,
  jobs,
  onCreated,
  onOpenFile,
}: {
  csrfToken: string;
  folder: FolderPayload | null;
  file: FilePayload | null;
  activeRoot: RootInfo;
  roots: RootInfo[];
  jobs: AgentJobsPayload | null;
  onCreated: (message: string) => void;
  onOpenFile: (path: string) => void;
}) {
  const roles = jobs?.roles.length ? jobs.roles : FALLBACK_AGENT_ROLES;
  const role = suggestedRole(folder, file);
  const [prompt, setPrompt] = useState("");
  const [references, setReferences] = useState<AgentReference[]>(() => referencesFromFile(file));
  const [referencePickerOpen, setReferencePickerOpen] = useState(false);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [selectedOutputId, setSelectedOutputId] = useState("");
  const [confirmSessionDelete, setConfirmSessionDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [outputWidth, setOutputWidth] = useState(() => {
    const saved = window.localStorage.getItem(OUTPUT_WIDTH_STORAGE_KEY);
    const value = saved ? Number(saved) : DEFAULT_OUTPUT_WIDTH;
    return Number.isFinite(value) ? clampNumber(value, OUTPUT_MIN_WIDTH, OUTPUT_MAX_WIDTH) : DEFAULT_OUTPUT_WIDTH;
  });
  const agentPageRef = useRef<HTMLDivElement>(null);
  const chatStreamRef = useRef<HTMLDivElement>(null);
  const selectedRole = roles.find((item) => item.role === role) || roles[0];
  const roleJobs = useMemo(() => (jobs?.jobs || []).filter((job) => job.role === selectedRole?.role), [jobs?.jobs, selectedRole?.role]);
  const sessions = useMemo(() => roleJobs.reduce<Array<{ id: string; title: string; jobs: AgentJob[] }>>((items, job) => {
    const id = job.session_id || job.id;
    const found = items.find((item) => item.id === id);
    if (found) {
      found.jobs.push(job);
    } else {
      items.push({ id, title: job.session_title || sessionTitle(job.prompt), jobs: [job] });
    }
    return items;
  }, []), [roleJobs]);
  const activeSession = activeSessionId === NEW_AGENT_SESSION_ID ? null : sessions.find((item) => item.id === activeSessionId) || null;
  const activeSessionJobs = useMemo(
    () => [...(activeSession?.jobs || [])].sort((a, b) => jobTime(a).localeCompare(jobTime(b))),
    [activeSession],
  );
  const chatScrollKey = useMemo(
    () => activeSessionJobs.map((job) => `${job.id}:${job.status}:${job.assistant_reply?.length || 0}:${job.output_path || ""}`).join("|"),
    [activeSessionJobs],
  );
  const sessionOutputs = useMemo(() => activeSessionJobs.filter((job) => job.output_path), [activeSessionJobs]);
  const selectedOutput = sessionOutputs.find((job) => job.id === selectedOutputId) || sessionOutputs[0] || null;
  const canRequest = activeRoot.id === "personal";
  const outputExpanded = outputWidth >= 55;
  const agentLayoutStyle = { "--outputs-width": `${outputWidth}%` } as CSSProperties;

  useEffect(() => {
    window.localStorage.setItem(OUTPUT_WIDTH_STORAGE_KEY, String(Math.round(outputWidth)));
  }, [outputWidth]);

  useEffect(() => {
    setPrompt("");
    setError("");
    setReferences(referencesFromFile(file));
    setReferencePickerOpen(false);
    setActiveSessionId("");
    setSelectedOutputId("");
  }, [folder?.root.id, folder?.path, file?.path]);

  useEffect(() => {
    if (activeSessionId === NEW_AGENT_SESSION_ID) {
      return;
    }
    if (!activeSessionId && sessions.length) {
      setActiveSessionId(sessions[0].id);
      return;
    }
    if (activeSessionId && sessions.length && !sessions.some((item) => item.id === activeSessionId)) {
      setActiveSessionId(sessions[0].id);
    }
  }, [activeSessionId, sessions]);

  useEffect(() => {
    if (!sessionOutputs.length) {
      setSelectedOutputId("");
      return;
    }
    if (!selectedOutputId || !sessionOutputs.some((job) => job.id === selectedOutputId)) {
      setSelectedOutputId(sessionOutputs[0].id);
    }
  }, [selectedOutputId, sessionOutputs]);

  useEffect(() => {
    const stream = chatStreamRef.current;
    if (!stream) return;
    const frame = window.requestAnimationFrame(() => {
      stream.scrollTop = stream.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeSessionId, chatScrollKey, busy]);

  function applyTemplate(template: string) {
    setPrompt((current) => {
      const trimmed = current.trim();
      return trimmed ? `${trimmed}\n\n${template}` : template;
    });
    setError("");
  }

  async function submit() {
    if (!canRequest) {
      setError("봇 요청은 개인 작업공간에서만 만들 수 있습니다.");
      return;
    }
    if (!prompt.trim()) {
      setError("요청 내용을 입력해주세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await createAgentJob(
        csrfToken,
        selectedRole.role,
        prompt.trim(),
        references.map((reference) => ({ root: reference.root, path: reference.path })),
        activeSession ? { id: activeSession.id, title: activeSession.title } : { title: sessionTitle(prompt) },
      );
      setPrompt("");
      setActiveSessionId(result.job.session_id);
      onCreated(`${selectedRole.label}을 큐에 등록했습니다.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "봇 요청을 만들지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (busy || !canRequest || !prompt.trim()) return;
    void submit();
  }

  async function hideCurrentSession() {
    if (!activeSession || busy) return;
    setBusy(true);
    setError("");
    try {
      await hideAgentSession(csrfToken, activeSession.id);
      setActiveSessionId("");
      setConfirmSessionDelete(false);
      onCreated("대화 기록을 삭제했습니다.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "대화를 삭제하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  function updateOutputWidthFromPointer(clientX: number) {
    const rect = agentPageRef.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0) return;
    const next = ((rect.right - clientX) / rect.width) * 100;
    setOutputWidth(clampNumber(next, OUTPUT_MIN_WIDTH, OUTPUT_MAX_WIDTH));
  }

  function startOutputResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    event.preventDefault();
    document.body.classList.add("is-resizing-output");
    updateOutputWidthFromPointer(event.clientX);
    const handleMove = (moveEvent: PointerEvent) => updateOutputWidthFromPointer(moveEvent.clientX);
    const handleUp = () => {
      document.body.classList.remove("is-resizing-output");
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      window.removeEventListener("pointercancel", handleUp);
    };
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    window.addEventListener("pointercancel", handleUp);
  }

  function handleOutputResizeKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setOutputWidth((current) => clampNumber(current + 4, OUTPUT_MIN_WIDTH, OUTPUT_MAX_WIDTH));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setOutputWidth((current) => clampNumber(current - 4, OUTPUT_MIN_WIDTH, OUTPUT_MAX_WIDTH));
    } else if (event.key === "Home") {
      event.preventDefault();
      setOutputWidth(DEFAULT_OUTPUT_WIDTH);
    } else if (event.key === "End") {
      event.preventDefault();
      setOutputWidth(WIDE_OUTPUT_WIDTH);
    }
  }

  return (
    <div className="agent-page live-agent-page" ref={agentPageRef} style={agentLayoutStyle}>
      <section className="chat-pane">
        <header className="chat-head">
          <div className="bot-avatar">e.</div>
          <div className="meta">
            <strong>{agentDisplayName(selectedRole)}</strong>
            <small><span className="bot-dot running" /> {selectedRole.description} · 오늘 작업 {roleJobs.length.toLocaleString()}건</small>
          </div>
          <div className="actions">
            {activeSession ? (
              <button type="button" className="btn ghost sm" onClick={() => setConfirmSessionDelete(true)} disabled={busy}>대화 삭제</button>
            ) : null}
          </div>
        </header>

        <div className="session-tabs" role="tablist" aria-label="대화 세션">
          {sessions.map((session) => {
            const latest = session.jobs[0];
            return (
              <button
                type="button"
                className={`session-tab ${session.id === activeSessionId ? "active" : ""}`}
                key={session.id}
                onClick={() => setActiveSessionId(session.id)}
                title={session.title}
              >
                <span className={`dot ${latest?.status === "done" ? "completed" : latest?.status || ""}`} />
                <span className="title">{session.title}</span>
              </button>
            );
          })}
          <button type="button" className={`session-tab new-session ${activeSessionId === NEW_AGENT_SESSION_ID || !activeSession ? "active" : ""}`} onClick={() => { setActiveSessionId(NEW_AGENT_SESSION_ID); setPrompt(""); setError(""); }}>
            <span className="title">+ 새 작업</span>
          </button>
        </div>

        {!activeSession && !prompt ? (
          <div className="agent-empty inline">
            <div className="illu">e.</div>
            <h2>{agentDisplayName(selectedRole)}에게 새 작업을 맡겨보세요</h2>
            <p>{selectedRole.output_hint}</p>
            <div className="prompts">
              {(selectedRole.templates || []).map((template, index) => (
                <button type="button" key={`${selectedRole.role}-prompt-${index}`} onClick={() => applyTemplate(template)} disabled={busy}>
                  <strong>예시 {index + 1}</strong>
                  <span>{template}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="chat-stream" ref={chatStreamRef}>
            <div className="chat-day">{activeSession ? activeSession.title : "새 작업"}</div>
            <div className="msg agent">
              <div className="avatar">e.</div>
              <div className="bubble">
                <div className="top">
                  <strong>{selectedRole.profile}</strong>
                  <span>준비됨</span>
                </div>
                <div className="body">
                  {selectedRole.output_hint || "요청을 보내면 작업이 큐에 등록되고 완료 후 산출물 파일로 저장됩니다."}
                </div>
              </div>
            </div>
            {activeSessionJobs.length ? activeSessionJobs.map((job) => {
              const pending = job.status === "running" || job.status === "queued";
              const agentBody = pending
                ? "요청을 처리하고 있어요. 잠시 뒤 답변이나 산출물이 이 대화에 붙습니다."
                : job.assistant_reply || job.error || "처리 결과가 비어 있습니다. 작업 기록을 확인해주세요.";
              return (
                <Fragment key={job.id}>
                  <div className="msg user">
                    <div className="avatar">{(job.user_name || job.username || "U").slice(0, 1)}</div>
                    <div className="bubble">
                      <div className="top">
                        <span>{job.status_label}</span>
                        <strong>{job.role_label}</strong>
                      </div>
                      <div className="body">
                        {job.prompt}
                      </div>
                    </div>
                  </div>
                  <div className="msg agent">
                    <div className="avatar">e.</div>
                    <div className="bubble">
                      <div className="top">
                        <strong>{selectedRole.profile}</strong>
                        <span>{job.status_label}</span>
                      </div>
                      <div className={`body ${pending ? "thinking" : "markdown-body"}`}>
                        {pending ? agentBody : <MarkdownMessage text={agentBody} />}
                      </div>
                      {job.output_path ? (
                        <div className="msg-outputs">
                          <button type="button" className="msg-output" onClick={() => setSelectedOutputId(job.id)}>
                            <span className={`kind-token ${kindClass(outputKind(job.output_path).kind)}`}>{outputKind(job.output_path).label}</span>
                            <div className="info">
                              <strong>{fileNameFromPath(job.output_path)}</strong>
                              <small>{job.status_label} · 오른쪽에서 바로 확인</small>
                            </div>
                            <span className="open">미리보기</span>
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                </Fragment>
              );
            }) : null}
          </div>
        )}

        <div className="composer">
          <div className="composer-dropzone">
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder={selectedRole.placeholder || "봇에게 작업을 시키거나 질문해보세요."}
              rows={3}
              disabled={busy || !canRequest}
            />
          </div>
          <div className="composer-actions">
            <div className="left">
              {references.length ? (
                <ReferenceChipList
                  references={references}
                  disabled={busy}
                  onRemove={(target) => setReferences((current) => current.filter((item) => referenceKey(item) !== referenceKey(target)))}
                />
              ) : (
                <span className="hint">내 산출물 또는 우리 팀 공유자료만 참고할 수 있습니다.</span>
              )}
              <button type="button" className="reference-button" onClick={() => setReferencePickerOpen(true)} disabled={busy}>
                참고자료 선택
              </button>
            </div>
            <button type="button" className="send" onClick={submit} disabled={busy || !canRequest || !prompt.trim()}>
              {busy ? "등록 중" : "전송"}
            </button>
          </div>
          {error ? <p className="err" role="alert">{error}</p> : null}
        </div>
      </section>

      <div
        className="pane-resizer"
        role="separator"
        aria-label="산출물 패널 너비 조절"
        aria-orientation="vertical"
        aria-valuemin={OUTPUT_MIN_WIDTH}
        aria-valuemax={OUTPUT_MAX_WIDTH}
        aria-valuenow={Math.round(outputWidth)}
        tabIndex={0}
        onPointerDown={startOutputResize}
        onKeyDown={handleOutputResizeKey}
      >
        <span className="resizer-line" aria-hidden="true" />
      </div>

      <aside className="outputs-pane">
        <div className="outputs-head">
          <h3>이 세션의 산출물 <span className="count">{sessionOutputs.length}</span></h3>
          <div className="actions">
            <button
              type="button"
              className="btn sm"
              onClick={() => setOutputWidth(outputExpanded ? DEFAULT_OUTPUT_WIDTH : WIDE_OUTPUT_WIDTH)}
              aria-pressed={outputExpanded}
            >
              {outputExpanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
              <span>{outputExpanded ? "기본 보기" : "크게 보기"}</span>
            </button>
          </div>
        </div>
        {sessionOutputs.length ? (
          <>
            <div className="outputs-list">
              {sessionOutputs.map((job) => {
                const kind = outputKind(job.output_path);
                return (
                  <button
                    type="button"
                    key={job.id}
                    className={`output-row ${selectedOutput?.id === job.id ? "selected" : ""}`}
                    onClick={() => setSelectedOutputId(job.id)}
                  >
                    <span className={`kind-token ${kindClass(kind.kind)}`}>{kind.label}</span>
                    <div className="info">
                      <strong>{fileNameFromPath(job.output_path)}</strong>
                      <small>{job.status_label} · {job.summary || "작업 결과"}</small>
                    </div>
                    <span className="size">보기</span>
                  </button>
                );
              })}
            </div>
            {selectedOutput ? (
              <>
                <div className="outputs-preview">
                  {outputKind(selectedOutput.output_path).previewable ? (
                    <iframe
                      className="output-preview-frame"
                      title={`${fileNameFromPath(selectedOutput.output_path)} 미리보기`}
                      src={portalAssetUrl("/preview", selectedOutput.output_root || activeRoot.id, selectedOutput.output_path)}
                      loading="lazy"
                    />
                  ) : (
                    <div className="card-doc output-fallback">
                      <h3>{fileNameFromPath(selectedOutput.output_path)}</h3>
                      <p>이 파일은 인라인 미리보기를 지원하지 않습니다.</p>
                      <p>다운로드하거나 파일 보기에서 상세 작업을 이어가세요.</p>
                    </div>
                  )}
                </div>
                <div className="outputs-foot">
                  <span className="filename">{selectedOutput.output_path}</span>
                  <div className="actions">
                    <button type="button" className="btn sm" onClick={() => onOpenFile(selectedOutput.output_path)}>파일 보기</button>
                    <a className="btn sm primary" href={portalAssetUrl("/download", selectedOutput.output_root || activeRoot.id, selectedOutput.output_path)}>다운로드</a>
                  </div>
                </div>
              </>
            ) : null}
          </>
        ) : (
          <div className="outputs-empty">
            <div className="illu">e.</div>
            <h3>아직 산출물이 없어요</h3>
            <p>이 대화의 작업이 완료되면 여기에서 결과 파일을 바로 열 수 있습니다.</p>
          </div>
        )}
      </aside>
      {confirmSessionDelete ? (
        <ConfirmDialog
          title="대화를 삭제할까요?"
          description="대화 기록만 숨겨지고, 이미 만들어진 결과 파일은 작업공간에 그대로 남습니다."
          confirmLabel={busy ? "삭제 중" : "삭제"}
          cancelLabel="취소"
          busy={busy}
          onCancel={() => setConfirmSessionDelete(false)}
          onConfirm={hideCurrentSession}
        />
      ) : null}
      {referencePickerOpen ? (
        <AgentReferenceDialog
          roots={roots}
          selectedReferences={references}
          onClose={() => setReferencePickerOpen(false)}
          onApply={(nextReferences) => {
            setReferences(nextReferences);
            setReferencePickerOpen(false);
          }}
        />
      ) : null}
    </div>
  );
}

function ReferenceChipList({
  references,
  disabled = false,
  onRemove,
}: {
  references: AgentReference[];
  disabled?: boolean;
  onRemove: (reference: AgentReference) => void;
}) {
  return (
    <div className="reference-chip-list" aria-label="선택한 참고자료">
      {references.map((reference) => (
        <span className="reference-chip" key={referenceKey(reference)}>
          <FileText size={13} />
          <span>{reference.label}</span>
          <button
            type="button"
            onClick={() => onRemove(reference)}
            disabled={disabled}
            aria-label={`${reference.label} 참고자료 해제`}
          >
            ×
          </button>
        </span>
      ))}
    </div>
  );
}

function AgentReferenceDialog({
  roots,
  selectedReferences,
  onClose,
  onApply,
}: {
  roots: RootInfo[];
  selectedReferences: AgentReference[];
  onClose: () => void;
  onApply: (references: AgentReference[]) => void;
}) {
  const sources = useMemo(() => agentReferenceSources(roots), [roots]);
  const initialSource = sourceForReferences(sources, selectedReferences);
  const [sourceId, setSourceId] = useState(initialSource?.id || "");
  const activeSource = sources.find((source) => source.id === sourceId) || sources[0];
  const [currentPath, setCurrentPath] = useState(activeSource?.basePath || "");
  const [query, setQuery] = useState("");
  const [folder, setFolder] = useState<FolderPayload | null>(null);
  const [draftReferences, setDraftReferences] = useState<AgentReference[]>(selectedReferences);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectionError, setSelectionError] = useState("");
  const canGoUp = Boolean(activeSource && currentPath && currentPath !== activeSource.basePath);

  useEffect(() => {
    if (!activeSource) return;
    setCurrentPath(activeSource.basePath);
    setQuery("");
  }, [activeSource?.id]);

  useEffect(() => {
    if (!activeSource) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    fetchFolder(
      activeSource.root,
      currentPath,
      { q: query, type: "", status: "", sort: "modified" },
      { limit: 100 },
      controller.signal,
    ).then((payload) => {
      setFolder(payload);
    }).catch((err: Error) => {
      if (controller.signal.aborted) return;
      setFolder(null);
      setError(err.message || "참고자료 목록을 불러오지 못했습니다.");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [activeSource?.root, activeSource?.id, currentPath, query]);

  function selectSource(nextSource: ReferenceSource) {
    setSourceId(nextSource.id);
    setCurrentPath(nextSource.basePath);
    setQuery("");
  }

  function openParent() {
    if (!activeSource || !canGoUp) return;
    const next = parentPath(currentPath);
    setCurrentPath(next && next.startsWith(activeSource.basePath) ? next : activeSource.basePath);
  }

  function referenceLabel(entry: FolderEntry) {
    if (!activeSource) return entry.name;
    return `${activeSource.label} · ${entry.name}`;
  }

  function toggleReference(entry: FolderEntry) {
    if (!activeSource || entry.is_dir) return;
    const nextReference = { root: activeSource.root, path: entry.path, label: referenceLabel(entry) };
    const key = referenceKey(nextReference);
    setSelectionError("");
    if (draftReferences.some((item) => referenceKey(item) === key)) {
      setDraftReferences((current) => current.filter((item) => referenceKey(item) !== key));
      return;
    }
    if (draftReferences.length >= MAX_AGENT_REFERENCES) {
      setSelectionError(`참고자료는 최대 ${MAX_AGENT_REFERENCES}개까지 선택할 수 있습니다.`);
      return;
    }
    setDraftReferences((current) => [...current, nextReference]);
  }

  return (
    <ConfirmDialogFrame onClose={onClose} labelledBy="agent-reference-title">
      <div className="reference-dialog">
        <div className="dialog-head">
          <div>
            <p className="eyebrow">참고자료</p>
            <h2 id="agent-reference-title">봇이 참고할 파일 선택</h2>
            <p className="sub">내 개인 산출물과 우리 팀 공유공간 안의 파일만 최대 {MAX_AGENT_REFERENCES}개까지 선택할 수 있습니다.</p>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="닫기">×</button>
        </div>

        <div className="reference-sources" role="tablist" aria-label="참고자료 위치">
          {sources.map((source) => (
            <button
              type="button"
              key={source.id}
              className={source.id === activeSource?.id ? "active" : ""}
              onClick={() => selectSource(source)}
            >
              <strong>{source.label}</strong>
              <span>{source.description}</span>
            </button>
          ))}
        </div>

        {activeSource ? (
          <>
            <div className="reference-toolbar">
              <button type="button" className="btn sm" onClick={openParent} disabled={!canGoUp}>상위 폴더</button>
              <label className="reference-search">
                <span>검색</span>
                <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="파일명 검색" />
              </label>
            </div>
            <div className="reference-path">
              <FolderOpen size={14} />
              <span>{activeSource.label} / {currentPath || "전체"}</span>
            </div>
            <div className="reference-list" aria-busy={loading}>
              {loading ? <LoadingState /> : null}
              {!loading && error ? <p className="err" role="alert">{error}</p> : null}
              {!loading && !error && folder?.entries.length ? folder.entries.map((entry) => (
                <button
                  type="button"
                  key={entry.path}
                  className={`reference-row ${entry.is_dir ? "folder" : "file"} ${draftReferences.some((item) => item.root === activeSource.root && item.path === entry.path) ? "selected" : ""}`}
                  onClick={() => {
                    if (entry.is_dir) {
                      setCurrentPath(entry.path);
                      setQuery("");
                      return;
                    }
                    toggleReference(entry);
                  }}
                >
                  <span className={`kind-token ${entry.is_dir ? "folder" : kindClass(entry.kind)}`}>{entry.is_dir ? "DIR" : entry.kind_token}</span>
                  <span className="info">
                    <strong>{entry.name}</strong>
                    <small>{entry.is_dir ? "폴더 열기" : `${entry.kind_label} · ${entry.modified}`}</small>
                  </span>
                  <span className="action">{entry.is_dir ? "열기" : draftReferences.some((item) => item.root === activeSource.root && item.path === entry.path) ? "해제" : "추가"}</span>
                </button>
              )) : null}
              {!loading && !error && folder && !folder.entries.length ? (
                <div className="reference-empty">선택할 파일이 없습니다.</div>
              ) : null}
            </div>
          </>
        ) : (
          <div className="reference-empty">참고자료를 선택할 수 있는 작업공간이 없습니다.</div>
        )}

        <div className="reference-selected">
          <strong>{draftReferences.length}/{MAX_AGENT_REFERENCES}개 선택됨</strong>
          {draftReferences.length ? (
            <ReferenceChipList
              references={draftReferences}
              onRemove={(target) => setDraftReferences((current) => current.filter((item) => referenceKey(item) !== referenceKey(target)))}
            />
          ) : (
            <span className="hint">선택된 참고자료가 없습니다.</span>
          )}
        </div>
        {selectionError ? <p className="err" role="alert">{selectionError}</p> : null}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={() => onApply([])}>참고 안 함</button>
          <button type="button" className="btn" onClick={onClose}>취소</button>
          <button type="button" className="btn ink" onClick={() => onApply(draftReferences)}>선택 완료</button>
        </div>
      </div>
    </ConfirmDialogFrame>
  );
}

function AgentJobStrip({
  jobs,
  onOpen,
  onOpenFile,
}: {
  jobs: AgentJobsPayload["jobs"];
  onOpen: () => void;
  onOpenFile: (path: string) => void;
}) {
  const visible = jobs.slice(0, 3);
  return (
    <section className="agent-strip" aria-label="최근 봇 요청">
      <div>
        <strong>최근 봇 요청</strong>
        <span>{jobs.length ? `${jobs.length.toLocaleString()}개 기록` : "웹에서 바로 요청할 수 있습니다."}</span>
      </div>
      <div className="agent-strip-list">
        {visible.length ? visible.map((job) => (
          <button
            type="button"
            key={job.id}
            className={`agent-job-chip ${job.status}`}
            onClick={() => job.output_path ? onOpenFile(job.output_path) : onOpen()}
          >
            <span>{job.role_label}</span>
            <strong>{job.status_label}</strong>
          </button>
        )) : null}
        <button type="button" className="btn sm" onClick={onOpen}>새 요청</button>
      </div>
    </section>
  );
}

function AgentRequestDialog({
  csrfToken,
  folder,
  file,
  roots,
  roles,
  onClose,
  onCreated,
}: {
  csrfToken: string;
  folder: FolderPayload | null;
  file: FilePayload | null;
  roots: RootInfo[];
  roles: AgentJobsPayload["roles"];
  onClose: () => void;
  onCreated: (message: string) => void;
}) {
  const [role, setRole] = useState(suggestedRole(folder, file));
  const [prompt, setPrompt] = useState("");
  const [references, setReferences] = useState<AgentReference[]>(() => referencesFromFile(file));
  const [referencePickerOpen, setReferencePickerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const availableRoles = roles.length ? roles : FALLBACK_AGENT_ROLES;
  const selectedRole = availableRoles.find((item) => item.role === role) || availableRoles[0];
  const roleTemplates = selectedRole?.templates || [];

  function applyTemplate(template: string) {
    setPrompt((current) => {
      const trimmed = current.trim();
      return trimmed ? `${trimmed}\n\n${template}` : template;
    });
    setError("");
  }

  async function submit() {
    if (!prompt.trim()) {
      setError("요청 내용을 입력해주세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await createAgentJob(
        csrfToken,
        role,
        prompt.trim(),
        references.map((reference) => ({ root: reference.root, path: reference.path })),
      );
      onCreated("봇 요청을 큐에 등록했습니다.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "봇 요청을 만들지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ConfirmDialogFrame onClose={onClose} labelledBy="agent-request-title">
      <div className="agent-dialog">
        <div className="dialog-head">
          <div>
            <p className="eyebrow">Hermes Agent</p>
            <h2 id="agent-request-title">봇에게 작업 요청</h2>
            <p className="sub">요청은 현재 사용자 작업공간에서 실행되고, 결과 파일은 해당 봇 폴더에 저장됩니다.</p>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="닫기">×</button>
        </div>
        <label className="field">
          <span>작업 종류</span>
          <select value={role} onChange={(event) => setRole(event.target.value)} disabled={busy}>
            {availableRoles.map((item) => (
              <option key={item.role} value={item.role}>{item.label} · {item.profile}</option>
            ))}
          </select>
        </label>
        {selectedRole ? (
          <div className="role-help">
            <strong>{selectedRole.description}</strong>
            <span>{selectedRole.output_hint}</span>
          </div>
        ) : null}
        {roleTemplates.length ? (
          <div className="template-row" aria-label="요청 예시">
            {roleTemplates.map((template, index) => (
              <button type="button" className="template-chip" key={`${selectedRole.role}-${index}`} onClick={() => applyTemplate(template)} disabled={busy}>
                예시 {index + 1}
              </button>
            ))}
          </div>
        ) : null}
        <label className="field">
          <span>요청 내용</span>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            disabled={busy}
            rows={7}
            placeholder={selectedRole?.placeholder || "예: 이 자료를 기준으로 핵심 내용과 다음 개발 액션을 정리해줘."}
          />
        </label>
        <div className="dialog-reference">
          {references.length ? (
            <ReferenceChipList
              references={references}
              disabled={busy}
              onRemove={(target) => setReferences((current) => current.filter((item) => referenceKey(item) !== referenceKey(target)))}
            />
          ) : (
            <span className="hint">참고자료 없이 요청합니다.</span>
          )}
          <button type="button" className="btn sm" onClick={() => setReferencePickerOpen(true)} disabled={busy}>참고자료 선택</button>
        </div>
        {error ? <p className="err" role="alert">{error}</p> : null}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>취소</button>
          <button type="button" className="btn ink" onClick={submit} disabled={busy}>{busy ? "등록 중" : "요청 등록"}</button>
        </div>
        {referencePickerOpen ? (
          <AgentReferenceDialog
            roots={roots}
            selectedReferences={references}
            onClose={() => setReferencePickerOpen(false)}
            onApply={(nextReferences) => {
              setReferences(nextReferences);
              setReferencePickerOpen(false);
            }}
          />
        ) : null}
      </div>
    </ConfirmDialogFrame>
  );
}

function optionLabel(options: readonly (readonly [string, string])[], value: string) {
  return options.find(([item]) => item === value)?.[1] || value;
}

function FilterBar({
  filters,
  entryCount,
  onFiltersChange,
}: {
  filters: FolderFilters;
  entryCount: number;
  onFiltersChange: (filters: FolderFilters) => void;
}) {
  const [open, setOpen] = useState(false);
  function update(key: keyof FolderFilters, value: string) {
    onFiltersChange({ ...filters, [key]: value });
  }
  const active = filters.type || filters.status || (filters.sort && filters.sort !== DEFAULT_FILTERS.sort);
  const applied = [
    filters.q ? { key: "q" as const, label: `검색: ${filters.q}` } : null,
    filters.type ? { key: "type" as const, label: `유형: ${optionLabel(TYPE_OPTIONS, filters.type)}` } : null,
    filters.status ? { key: "status" as const, label: `상태: ${optionLabel(STATUS_OPTIONS, filters.status)}` } : null,
    filters.sort !== DEFAULT_FILTERS.sort ? { key: "sort" as const, label: `정렬: ${optionLabel(SORT_OPTIONS, filters.sort)}` } : null,
  ].filter(Boolean) as Array<{ key: keyof FolderFilters; label: string }>;

  return (
    <>
      <div className="list-toolbar">
        <label className="search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
          </svg>
          <input type="search" placeholder="이 폴더 안에서 검색" value={filters.q} onChange={(e) => update("q", e.target.value)} />
        </label>
        <button className={`filter-toggle ${open || active ? "active" : ""}`} onClick={() => setOpen((v) => !v)}>
          필터
        </button>
        <span className="count tnum">{entryCount.toLocaleString()}개</span>
      </div>
      {open ? (
        <div className="list-filters">
          <label>
            <span>유형</span>
            <select value={filters.type} onChange={(e) => update("type", e.target.value)}>
              {TYPE_OPTIONS.map(([value, label]) => (<option key={value} value={value}>{label}</option>))}
            </select>
          </label>
          <label>
            <span>상태</span>
            <select value={filters.status} onChange={(e) => update("status", e.target.value)}>
              <option value="">전체 상태</option>
              {STATUS_OPTIONS.map(([value, label]) => (<option key={value} value={value}>{label}</option>))}
            </select>
          </label>
          <label>
            <span>정렬</span>
            <select value={filters.sort} onChange={(e) => update("sort", e.target.value)}>
              {SORT_OPTIONS.map(([value, label]) => (<option key={value} value={value}>{label}</option>))}
            </select>
          </label>
        </div>
      ) : null}
      {applied.length ? (
        <div className="applied-chips" aria-label="적용된 필터">
          {applied.map((item) => (
            <span key={item.key} className="chip">
              {item.label}
              <button type="button" onClick={() => update(item.key, DEFAULT_FILTERS[item.key])}>×</button>
            </span>
          ))}
          <button type="button" className="chip reset" onClick={() => onFiltersChange(DEFAULT_FILTERS)}>모두 해제</button>
        </div>
      ) : null}
    </>
  );
}

function UploadAction({
  csrfToken,
  folder,
  onUploaded,
}: {
  csrfToken: string;
  folder: FolderPayload;
  onUploaded: (path: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function uploadSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    if (!file) return;
    setBusy(true); setMessage("");
    try {
      const result = await uploadFile(csrfToken, folder.root.id, folder.path, file);
      onUploaded(result.path);
      event.currentTarget.value = "";
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "업로드하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="upload-action">
      <label className={`btn primary ${busy ? "busy" : ""}`}>
        <span aria-hidden="true">+</span>
        <span>{busy ? "업로드 중" : "업로드"}</span>
        <input name="file" type="file" disabled={busy} onChange={uploadSelected} />
      </label>
      {message ? <span className="err upload-action-error" role="alert">{message}</span> : null}
    </span>
  );
}

function EntryBrowser({
  entries,
  selectedPath,
  totalCount,
  hasMore,
  onLoadMore,
  loadingMore,
  onOpenFolder,
  onOpenFile,
  emptyText,
}: {
  entries: FolderEntry[];
  selectedPath: string;
  totalCount: number;
  hasMore: boolean;
  onLoadMore: () => void;
  loadingMore: boolean;
  onOpenFolder: (path: string) => void;
  onOpenFile: (path: string) => void;
  emptyText?: string;
}) {
  const selectedRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "nearest" });
  }, [selectedPath]);

  if (entries.length === 0) {
    return (
      <div className="empty-state" role="status">
        <h2>표시할 산출물이 없습니다.</h2>
        <p>{emptyText || "웹에서 에이전트에게 요청하거나 직접 업로드하면 여기에 표시됩니다."}</p>
      </div>
    );
  }

  const hiddenCount = Math.max(totalCount - entries.length, 0);

  return (
    <div className="entry-list">
      <div className="entry-list-head">
        <span />
        <span>이름</span>
        <span>상태</span>
      </div>
      {entries.map((entry) => {
        const isSelected = !entry.is_dir && entry.path === selectedPath;
        const details = [
          entry.kind_label,
          entry.modified,
          entry.is_dir ? null : entry.size_label,
        ].filter(Boolean).join(" · ");
        return (
          <button
            key={entry.path}
            ref={isSelected ? selectedRef : undefined}
            type="button"
            className={`entry ${isSelected ? "selected" : ""}`}
            aria-current={isSelected ? "true" : undefined}
            onClick={() => (entry.is_dir ? onOpenFolder(entry.path) : onOpenFile(entry.path))}
          >
            <span className={`kind-token ${kindClass(entry.kind)}`}>{entry.kind_token}</span>
            <span className="name">
              <strong>{entry.name}</strong>
              <small>{details}</small>
            </span>
            <span className="meta-cell status-cell">
              {entry.status_label ? (
                <span className={`pill ${statusClass(entry.status)}`}><span className="dot" />{entry.status_label}</span>
              ) : "—"}
            </span>
          </button>
        );
      })}
      {hiddenCount ? (
        <button type="button" className="load-more" onClick={onLoadMore} disabled={!hasMore || loadingMore}>
          {loadingMore ? "불러오는 중" : `${Math.min(60, hiddenCount).toLocaleString()}개 더 보기`}
        </button>
      ) : null}
    </div>
  );
}

function RootOverview({
  root,
  folder,
  onOpenFolder,
}: {
  root: RootInfo;
  folder: FolderPayload;
  onOpenFolder: (path: string) => void;
}) {
  const folderEntries = folder.entries.filter((e) => e.is_dir);
  const summary = folder.summary;
  const folderCount = summary?.dirs ?? folderEntries.length;
  const fileCount = summary?.files ?? Math.max(folder.entry_count - folderEntries.length, 0);
  const totalCount = folderCount + fileCount;
  const isAdminAll = root.id === "all";
  const isTeamShared = root.id === "team_shared";
  const guideSteps = isAdminAll
    ? [
        { title: "전체 작업공간 확인", body: "사용자별 개인 산출물과 팀 공유 위치를 함께 보고, 문제 파일은 바로 열어 내용을 확인합니다.", icon: <ShieldCheck size={16} /> },
        { title: "작업 기록 점검", body: "업로드, 공유, 이름 변경, 삭제, 차단 기록을 사용자·팀 기준으로 좁혀서 봅니다.", icon: <Clock size={16} /> },
        { title: "보관함 확인", body: "삭제된 파일은 즉시 제거되지 않으므로 보관함에서 원위치와 복구 필요 여부를 확인합니다.", icon: <Archive size={16} /> },
      ]
    : isTeamShared
      ? [
          { title: "최종본만 모으기", body: "개인 작업공간에서 검토가 끝난 파일만 팀 공유로 이동합니다.", icon: <CheckCircle2 size={16} /> },
          { title: "폴더별 확인", body: "팀 리서치, 팀 개발, 팀 요약 공유를 목적에 맞게 바로 엽니다.", icon: <FolderOpen size={16} /> },
          { title: "필요 시 복사", body: "다시 작업해야 하는 파일은 내 작업공간으로 복사해 이어갑니다.", icon: <Download size={16} /> },
        ]
    : [
        { title: "폴더 열기", body: "왼쪽 메뉴나 아래 폴더 카드에서 리서치, 개발 산출물, 요약·보고를 엽니다.", icon: <FolderOpen size={16} /> },
        { title: "미리보기", body: "파일을 클릭하면 오른쪽에서 내용을 바로 확인합니다. 검토가 끝난 파일만 다운로드하거나 공유하세요.", icon: <Eye size={16} /> },
        { title: "다운로드·공유", body: "개인 확인용은 다운로드, 팀원이 함께 봐야 하는 결과물은 팀 공유로 이동합니다.", icon: <Download size={16} /> },
      ];
  const guideFolders = isAdminAll
    ? [
        ["전체 작업공간", "모든 사용자와 팀 공유 폴더를 루트 기준으로 확인합니다."],
        ["전체 산출물", "파일명, 사용자, 팀, 공간, 유형, 상태로 산출물을 검색합니다."],
        ["사용자 리포트", "사용자별 개인 파일, 공유 파일, 최근 작업 기록을 확인합니다."],
        ["Adminbot", "운영 규칙, 권한, Hermes 설정 점검 요청을 남깁니다."],
      ]
    : isTeamShared
      ? [
          ["팀 리서치 공유", "팀원이 함께 볼 조사 결과, 비교 자료, 출처 정리 문서를 모읍니다."],
          ["팀 개발 공유", "공유가 필요한 코드, 스크립트, 실행 결과, 압축 파일을 모읍니다."],
          ["팀 요약 공유", "회의록, 보고서, 액션아이템처럼 같이 확인할 정리본을 모읍니다."],
          ["팀 인수인계 공유", "다음 담당자가 이어받아야 하는 자료를 모읍니다."],
        ]
    : [
        ["리서치", "researchbot 조사 결과, 비교 자료, 출처 정리 문서가 저장됩니다."],
        ["개발 산출물", "devbot 코드, 스크립트, 실행 결과, 압축 파일이 저장됩니다."],
        ["요약·보고", "summarybot 회의록, 보고서, 액션아이템 정리가 저장됩니다."],
      ];
  const guideRules = isAdminAll
    ? [
        "관리자는 전체를 볼 수 있지만, 개인 작업공간 화면은 로그인한 관리자 본인 파일만 보여야 합니다.",
        "외부 공유 전에는 파일 소유자, 팀, 저장 위치, 상태를 함께 확인합니다.",
        "문제 파일은 바로 삭제하지 않고 보관함으로 이동해 복구 여지를 남깁니다.",
        "운영 이슈는 작업 기록과 Adminbot 결과 파일을 함께 남겨 추적합니다.",
      ]
    : isTeamShared
      ? [
          "팀원이 함께 봐야 하는 최종본만 팀 공유로 이동합니다.",
          "초안과 개인 참고자료는 개인 작업공간에 그대로 둡니다.",
          "팀 공유에는 직접 업로드하지 않고 개인 파일에서 공유로 이동합니다.",
          "헷갈리는 파일은 열어본 뒤 이름을 바꿔 용도를 알 수 있게 정리합니다.",
        ]
    : [
        "봇이 만든 결과는 봇 역할에 맞는 개인 폴더에 먼저 저장됩니다.",
        "봇이 참고해야 하는 자료는 요청창에서 내 산출물이나 우리 팀 공유자료 중에서 직접 선택합니다.",
        "팀 전체가 봐야 하는 최종본만 팀 공유로 이동하고, 초안은 개인 폴더에 둡니다.",
        "삭제한 파일은 보관함으로 이동되며, 필요하면 관리자에게 복구를 요청할 수 있습니다.",
        "파일명이 헷갈리면 미리보기 후 이름 변경으로 용도를 알 수 있게 정리하세요.",
      ];
  return (
    <div className="workspace-home">
      <section className="hero">
        <div>
          <span className="pill-lg">{root.kind_label}</span>
          <h1>
            {isAdminAll
              ? "전체 작업공간 관리"
              : isTeamShared
                ? `${root.label} 허브`
              : `${root.label}을 정리할 시간이에요`}
          </h1>
          <p>
            {isAdminAll
              ? "사용자별 산출물과 팀 공유 상태를 빠르게 확인하세요."
              : isTeamShared
                ? "팀원이 함께 볼 최종본을 모아둔 공간입니다. 아래 폴더 카드나 왼쪽 메뉴에서 목적별 공유 폴더로 바로 이동하세요."
              : "에이전트가 만든 파일을 폴더별로 열어 미리보고, 필요한 파일만 다운로드하거나 팀에 공유하세요."}
          </p>
        </div>
        <div className="hero-stats">
          <div className="hero-stat">
            <strong className="tnum">{totalCount.toLocaleString()}</strong>
            <span>{summary?.truncated ? "표시 항목" : "전체 항목"}</span>
            {summary ? <em>하위 포함</em> : null}
          </div>
          <div className="hero-stat">
            <strong className="tnum">{folderCount.toLocaleString()}</strong>
            <span>폴더</span>
            {summary ? <em>하위 포함</em> : null}
          </div>
          <div className="hero-stat share">
            <strong className="tnum">{fileCount.toLocaleString()}</strong>
            <span>파일</span>
            {summary ? <em>하위 포함</em> : null}
          </div>
        </div>
      </section>

      <section className="notice-board" aria-labelledby="workspace-guide-title">
        <div className="notice-intro">
          <span className="eyebrow">공지</span>
          <h2 id="workspace-guide-title">{isAdminAll ? "관리 기본 흐름" : isTeamShared ? "팀 공유 기준" : "기본 사용법"}</h2>
          <p>
            {isAdminAll
              ? "팀별 산출물, 공유 상태, 보관함과 작업 기록을 같은 기준으로 점검하세요."
              : isTeamShared
                ? "팀 공유는 결과물을 새로 만드는 곳이 아니라, 개인 작업공간에서 확정한 파일을 팀원이 함께 확인하는 곳입니다."
              : "처음에는 폴더를 열고, 파일을 미리 본 뒤, 필요한 산출물만 다운로드하거나 공유하면 됩니다."}
          </p>
        </div>
        <div className="guide-panel">
          <div className="guide-card">
            <div className="guide-card-head">
              <FileText size={16} />
              <strong>{isAdminAll ? "확인 순서" : isTeamShared ? "공유 흐름" : "사용 순서"}</strong>
            </div>
            <ol className="guide-steps">
              {guideSteps.map((step) => (
                <li key={step.title}>
                  <span className="step-icon">{step.icon}</span>
                  <div>
                    <strong>{step.title}</strong>
                    <span>{step.body}</span>
                  </div>
                </li>
              ))}
            </ol>
          </div>
          <div className="guide-card folder-guide">
            <div className="guide-card-head">
              <FolderOpen size={16} />
              <strong>{isAdminAll ? "관리 메뉴 기준" : isTeamShared ? "공유 폴더" : "폴더 기준"}</strong>
            </div>
            <dl className="guide-folders">
              {guideFolders.map(([title, body]) => (
                <div key={title}>
                  <dt>{title}</dt>
                  <dd>{body}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="guide-card rule">
            <div className="guide-card-head">
              <Share2 size={16} />
              <strong>{isAdminAll ? "관리 규칙" : isTeamShared ? "운영 기준" : "작업 규칙"}</strong>
            </div>
            <ul className="guide-rules">
              {guideRules.map((rule) => (
                <li key={rule}>
                  <CheckCircle2 size={15} />
                  <span>{rule}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {folderEntries.length ? (
        <div className="folder-grid">
          {folderEntries.map((entry) => (
            <button key={entry.path} className="folder-card" onClick={() => onOpenFolder(entry.path)}>
              <div className="folder-head">
                <div className="ico">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                  </svg>
                </div>
                <strong>{folderDisplayName(entry.name, root)}</strong>
              </div>
              <p>{folderPurpose(entry.name, root)}</p>
              <div className="folder-meta">
                {entry.size_label !== "-" ? (
                  <>
                    <span><strong className="tnum">{entry.size_label}</strong></span>
                    <span>·</span>
                  </>
                ) : null}
                <span>{entry.modified} 갱신</span>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <h2>표시할 폴더가 없습니다.</h2>
          <p>웹 에이전트가 산출물을 만들면 역할별 폴더에 자동으로 정리됩니다.</p>
        </div>
      )}
    </div>
  );
}

function folderDisplayName(name: string, root: RootInfo) {
  if (root.id === "team_shared") {
    const shared = SHARE_TARGETS.find(([value]) => value === name);
    if (shared) return shared[1];
  }
  if (name === "research") return "리서치";
  if (name === "dev") return "개발 산출물";
  if (name === "summary") return "요약·보고";
  return name;
}

function TeamSharedSwitcher({
  currentPath,
  onOpenFolder,
}: {
  currentPath: string;
  onOpenFolder: (path: string) => void;
}) {
  const active = firstFolder(currentPath) || "research";
  return (
    <nav className="shared-folder-switcher" aria-label="팀 공유 폴더 이동">
      <span>팀 공유 폴더</span>
      <div>
        {SHARE_TARGETS.map(([path, label]) => (
          <button
            key={path}
            type="button"
            className={active === path ? "active" : ""}
            onClick={() => onOpenFolder(path)}
          >
            {label}
          </button>
        ))}
      </div>
    </nav>
  );
}

function folderPurpose(name: string, root?: RootInfo) {
  if (root?.id === "team_shared") {
    if (name === "research") return "팀원이 함께 보는 조사 자료와 최종 리서치";
    if (name === "dev") return "팀원이 함께 보는 코드, 스크립트, 자동화 결과";
    if (name === "summary") return "팀원이 함께 보는 요약본, 보고서, 액션아이템";
    if (name === "handoff") return "다음 담당자가 이어받을 팀 인수인계 자료";
  }
  if (name === "research") return "조사 자료와 수집 파일";
  if (name === "dev") return "코드, 스크립트, 자동화 결과";
  if (name === "summary") return "요약본, 보고서, 발표 자료";
  if (name === "handoff") return "팀 인수인계 자료";
  return "폴더 열기";
}

function defaultPersonalCopyTarget(path: string) {
  const first = firstPathSegment(path);
  return PERSONAL_COPY_TARGETS.some((target) => target.value === first) ? first : "research";
}

function FileDetail({
  csrfToken,
  file,
  onChanged,
  onMoved,
  onArchived,
}: {
  csrfToken: string;
  file: FilePayload;
  onChanged: (message: string) => void;
  onMoved: (root: string, path: string, message: string) => void;
  onArchived: (message: string) => void;
}) {
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState("");
  const [newName, setNewName] = useState(file.name);
  const [previewReady, setPreviewReady] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [copyDialogOpen, setCopyDialogOpen] = useState(false);
  const [copyTarget, setCopyTarget] = useState(defaultPersonalCopyTarget(file.path));
  const shareTarget = file.share_plan?.target || firstPathSegment(file.path) || "research";

  useEffect(() => {
    setNewName(file.name);
    setPreviewReady(false);
    setConfirmDelete(false);
    setCopyDialogOpen(false);
    setCopyTarget(defaultPersonalCopyTarget(file.path));
    const t = window.setTimeout(() => setPreviewReady(true), 80);
    return () => window.clearTimeout(t);
  }, [file.name, file.path]);

  async function runAction<T>(name: string, action: () => Promise<T>, after: (result: T) => void) {
    setBusy(name); setActionError("");
    try {
      const result = await action();
      after(result);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "작업을 처리하지 못했습니다.");
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <header className="preview-head">
        <div className="preview-title">
          <h2>{file.name}</h2>
          <div className="preview-subline">
            <p className="crumb">{file.root.label} · {file.path}</p>
            {file.status_label ? <span className={`pill ${statusClass(file.status)}`}><span className="dot" />{file.status_label}</span> : null}
          </div>
        </div>
        <div className="actions">
          <a className="btn sm" href={file.download_url}>
            다운로드
          </a>
          {file.can_copy_to_personal ? (
            <button
              type="button"
              className="btn ink sm"
              disabled={Boolean(busy)}
              onClick={() => setCopyDialogOpen(true)}
            >
              내 작업공간으로 복사
            </button>
          ) : null}
          {file.can_share ? (
            <button
              type="button"
              className="btn ink sm"
              disabled={Boolean(busy)}
              onClick={() => runAction(
                "share",
                () => shareItem(csrfToken, file.root.id, file.path, shareTarget),
                (result) => onMoved(result.root, result.path, "팀 공유공간으로 이동했습니다."),
              )}
            >
              {busy === "share" ? "공유 중" : shareLabel(shareTarget)}
            </button>
          ) : null}
          {file.can_archive ? (
            <button
              type="button"
              className="btn danger sm"
              disabled={Boolean(busy)}
              onClick={() => setConfirmDelete(true)}
            >
              {busy === "archive" ? "삭제 중" : "삭제"}
            </button>
          ) : null}
        </div>
      </header>

      <div className="preview-meta">
        <div className="cell"><small>유형</small><strong>{file.kind_label}</strong></div>
        <div className="cell"><small>상태</small><strong>{file.status_label || "—"}</strong></div>
        <div className="cell"><small>크기</small><strong className="tnum">{file.size_label}</strong></div>
        <div className="cell"><small>수정</small><strong className="tnum">{file.modified}</strong></div>
      </div>
      {actionError ? <p className="err preview-error" role="alert">{actionError}</p> : null}

      <div className="preview-frame">
        {previewReady ? (
          <iframe className="preview-embed" title={`${file.name} 미리보기`} src={file.preview_url} loading="lazy" />
        ) : (
          <div className="preview-loading" role="status">미리보기 준비 중</div>
        )}
      </div>

      <details className="action-panel">
        <summary>검토 후 처리</summary>
        <div className="action-panel-body">
          <form className="rename-form" onSubmit={(event) => {
            event.preventDefault();
            if (!newName.trim() || newName.trim() === file.name) return;
            runAction("rename",
              () => renameItem(csrfToken, file.root.id, file.path, newName.trim()),
              (result) => onMoved(file.root.id, result.path, "이름을 바꿨습니다."),
            );
          }}>
            <label>
              <span>파일명</span>
              <input value={newName} disabled={Boolean(busy)} onChange={(e) => setNewName(e.target.value)} />
            </label>
            <button className="btn ink sm" type="submit" disabled={Boolean(busy) || !newName.trim() || newName.trim() === file.name}>
              {busy === "rename" ? "변경 중" : "이름 변경"}
            </button>
          </form>
          <label>
            <span>검토 상태</span>
            <select
              value={file.status || "active"}
              disabled={Boolean(busy)}
              onChange={(e) => runAction(
                "status",
                () => updateStatus(csrfToken, file.root.id, file.path, e.target.value),
                (result) => onChanged(`상태를 ${result.status_label}(으)로 바꿨습니다.`),
              )}
            >
              {STATUS_OPTIONS.map(([value, label]) => (<option key={value} value={value}>{label}</option>))}
            </select>
          </label>
        </div>
      </details>

      {file.events.length ? (
        <div className="preview-events">
          <h3>최근 기록</h3>
          <ul>
            {file.events.map((ev, idx) => (
              <li key={`${ev.time}-${ev.action}-${idx}`} className={idx === 0 ? "now" : ""}>
                <span />
                <span className="what">{ev.action_label} <em>· {ev.actor}</em></span>
                <time>{ev.time}</time>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {confirmDelete ? (
        <ConfirmDialog
          title="파일을 삭제할까요?"
          description={file.root.id === "team_shared" ? "팀 공유 목록에서 내려가고, 공유한 본인의 보관함으로 이동합니다. 관리자가 필요할 때 복구할 수 있습니다." : "파일은 보관함으로 이동되며, 관리자가 필요할 때 복구할 수 있습니다."}
          confirmLabel={busy === "archive" ? "삭제 중" : "삭제"}
          cancelLabel="취소"
          busy={busy === "archive"}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={() => runAction(
            "archive",
            () => archiveItem(csrfToken, file.root.id, file.path),
            () => {
              setConfirmDelete(false);
              onArchived(file.root.id === "team_shared" ? "팀 공유에서 내렸습니다. 보관함에서 복구할 수 있습니다." : "삭제 처리했습니다. 보관함에서 복구할 수 있습니다.");
            },
          )}
        />
      ) : null}

      {copyDialogOpen ? (
        <CopyToPersonalDialog
          fileName={file.name}
          target={copyTarget}
          busy={busy === "copy-personal"}
          onTargetChange={setCopyTarget}
          onCancel={() => setCopyDialogOpen(false)}
          onConfirm={() => runAction(
            "copy-personal",
            () => copyToPersonal(csrfToken, file.root.id, file.path, copyTarget),
            (result) => {
              setCopyDialogOpen(false);
              onMoved(result.root, result.path, "내 작업공간으로 복사했습니다.");
            },
          )}
        />
      ) : null}
    </>
  );
}

function CopyToPersonalDialog({
  fileName,
  target,
  busy,
  onTargetChange,
  onCancel,
  onConfirm,
}: {
  fileName: string;
  target: string;
  busy: boolean;
  onTargetChange: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    cancelRef.current?.focus();
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onCancel]);

  return createPortal(
    <div className="modal-backdrop" role="presentation" onMouseDown={() => { if (!busy) onCancel(); }}>
      <section
        className="confirm-modal copy-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="copy-title"
        aria-describedby="copy-description"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="confirm-icon" aria-hidden="true">↘</div>
        <div className="confirm-copy">
          <h2 id="copy-title">내 작업공간으로 복사</h2>
          <p id="copy-description">{fileName} 원본은 팀 공유에 그대로 두고, 선택한 개인 폴더에 사본을 만듭니다.</p>
          <label className="copy-target-field">
            <span>복사 위치</span>
            <select value={target} disabled={busy} onChange={(event) => onTargetChange(event.target.value)}>
              {PERSONAL_COPY_TARGETS.map((item) => (
                <option key={item.value} value={item.value}>{item.label}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="confirm-actions">
          <button ref={cancelRef} type="button" className="btn" disabled={busy} onClick={onCancel}>
            취소
          </button>
          <button type="button" className="btn ink solid" disabled={busy} onClick={onConfirm}>
            {busy ? "복사 중" : "복사"}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  );
}

function ConfirmDialog({
  title,
  description,
  confirmLabel,
  cancelLabel,
  busy,
  onCancel,
  onConfirm,
}: {
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    cancelRef.current?.focus();
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onCancel]);

  return createPortal(
    <div className="modal-backdrop" role="presentation" onMouseDown={() => { if (!busy) onCancel(); }}>
      <section
        className="confirm-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-description"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="confirm-icon" aria-hidden="true">!</div>
        <div className="confirm-copy">
          <h2 id="confirm-title">{title}</h2>
          <p id="confirm-description">{description}</p>
        </div>
        <div className="confirm-actions">
          <button ref={cancelRef} type="button" className="btn" disabled={busy} onClick={onCancel}>
            {cancelLabel}
          </button>
          <button type="button" className="btn danger solid" disabled={busy} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  );
}

function ConfirmDialogFrame({
  children,
  labelledBy,
  onClose,
}: {
  children: ReactNode;
  labelledBy: string;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    panelRef.current?.focus();
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);
  return createPortal(
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        ref={panelRef}
        className="confirm-modal agent-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        {children}
      </section>
    </div>,
    document.body,
  );
}

function EmptyDetail({ activeRoot }: { activeRoot: RootInfo }) {
  const isAdminAll = activeRoot.id === "all";
  return (
    <div className="preview-empty">
      <div className="illu">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
          <path d="M14 3v5h5M9 13h6M9 17h4" />
        </svg>
      </div>
      <h3>{isAdminAll ? "전체 작업공간을 빠르게 점검하세요" : "파일을 선택하세요"}</h3>
      <p>
        {isAdminAll
          ? "왼쪽에서 사용자와 팀 공유 위치를 훑어볼 수 있어요."
          : "왼쪽 목록에서 파일을 고르면 여기서 미리보고, 다운로드하거나 팀 공유공간으로 보낼 수 있어요."}
      </p>
    </div>
  );
}
