import type {
  AdminActivityFilters,
  AdminActivityPayload,
  AdminArchivePayload,
  AdminSearchFilters,
  AdminSearchPayload,
  AdminSummaryPayload,
  AdminUserPayload,
  AgentJob,
  AgentJobsPayload,
  FilePayload,
  FolderFilters,
  FolderPayload,
  SessionPayload,
} from "./types";

async function requestJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal,
  });
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("로그인이 필요합니다.");
  }
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload?.message || payload?.error || "요청을 처리하지 못했습니다.");
  }
  return payload as T;
}

export function fetchSession() {
  return requestJson<SessionPayload>("/api/session");
}

export function changeOwnPassword(csrfToken: string, currentPassword: string, newPassword: string, confirmPassword: string) {
  return postJson<{ ok: true; action: string }>("/api/account/password", csrfToken, {
    current_password: currentPassword,
    new_password: newPassword,
    confirm_password: confirmPassword,
  });
}

export function fetchFolder(
  root: string,
  path: string,
  filters?: FolderFilters,
  paging?: { offset?: number; limit?: number },
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ root });
  if (path) params.set("path", path);
  if (filters) {
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
  }
  if (paging?.offset) params.set("offset", String(paging.offset));
  if (paging?.limit) params.set("limit", String(paging.limit));
  return requestJson<FolderPayload>(`/api/folder?${params.toString()}`, signal);
}

export function fetchFile(root: string, path: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ root, path });
  return requestJson<FilePayload>(`/api/file?${params.toString()}`, signal);
}

export function fetchAdminSummary() {
  return requestJson<AdminSummaryPayload>("/api/admin/summary");
}

export function fetchAdminSearch(filters: AdminSearchFilters, options?: { limit?: number }) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  if (typeof options?.limit === "number") params.set("limit", String(options.limit));
  return requestJson<AdminSearchPayload>(`/api/admin/search?${params.toString()}`);
}

export function fetchAdminActivity(filters: AdminActivityFilters) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  return requestJson<AdminActivityPayload>(`/api/admin/activity?${params.toString()}`);
}

export function fetchAdminArchive() {
  return requestJson<AdminArchivePayload>("/api/admin/archive");
}

export function fetchAdminUser(username: string) {
  const params = new URLSearchParams({ username });
  return requestJson<AdminUserPayload>(`/api/admin/user?${params.toString()}`);
}

export function createPortalUser(csrfToken: string, username: string, name: string, team: string) {
  return postJson<{ ok: true; user: { username: string; name: string; team: string; disabled?: boolean }; password: string }>("/api/admin/users/create", csrfToken, {
    username,
    name,
    team,
  });
}

export function cleanupAdminActivity(csrfToken: string) {
  return postJson<{ ok: true; removed: number; kept: number; backup_path: string }>("/api/admin/activity/cleanup", csrfToken, {});
}

export function resetPortalUserPassword(csrfToken: string, username: string) {
  return postJson<{ ok: true; username: string; password: string }>("/api/admin/users/reset-password", csrfToken, {
    username,
  });
}

export function setPortalUserDisabled(csrfToken: string, username: string, disabled: boolean) {
  return postJson<{ ok: true; user: { username: string; name: string; team: string; disabled?: boolean } }>("/api/admin/users/status", csrfToken, {
    username,
    disabled: disabled ? "1" : "",
  });
}

export function fetchAgentJobs(options?: { limit?: number }) {
  const params = new URLSearchParams();
  if (typeof options?.limit === "number") params.set("limit", String(options.limit));
  const query = params.toString();
  return requestJson<AgentJobsPayload>(query ? `/api/agent/jobs?${query}` : "/api/agent/jobs");
}

async function postJson<T>(url: string, csrfToken: string, payload: Record<string, unknown>) {
  const response = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result?.message || result?.error || "요청을 처리하지 못했습니다.");
  }
  return result as T;
}

export function uploadFile(csrfToken: string, root: string, path: string, file: File) {
  const form = new FormData();
  form.set("csrf_token", csrfToken);
  form.set("root", root);
  form.set("path", path);
  form.set("file", file);
  return fetch("/api/upload", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: form,
  }).then(async (response) => {
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload?.message || payload?.error || "업로드하지 못했습니다.");
    }
    return payload as { ok: true; path: string; view_url: string };
  });
}

export function updateStatus(csrfToken: string, root: string, path: string, fileStatus: string) {
  return postJson<{ ok: true; status: string; status_label: string }>("/api/actions/status", csrfToken, {
    root,
    path,
    file_status: fileStatus,
  });
}

export function renameItem(csrfToken: string, root: string, path: string, newName: string) {
  return postJson<{ ok: true; root: string; path: string; name: string; url: string }>("/api/actions/rename", csrfToken, {
    root,
    path,
    new_name: newName,
  });
}

export function shareItem(csrfToken: string, root: string, path: string, sharedTarget: string) {
  return postJson<{ ok: true; root: string; path: string; url: string }>("/api/actions/share", csrfToken, {
    root,
    path,
    shared_target: sharedTarget,
  });
}

export function copyToPersonal(csrfToken: string, root: string, path: string, targetFolder: string) {
  return postJson<{ ok: true; root: string; path: string; url: string }>("/api/actions/copy-to-personal", csrfToken, {
    root,
    path,
    target_folder: targetFolder,
  });
}

export function createAgentJob(
  csrfToken: string,
  role: string,
  prompt: string,
  references?: Array<{ root: string; path: string }>,
  session?: { id?: string; title?: string },
) {
  const cleanReferences = references?.map((reference) => ({ root: reference.root, path: reference.path })) || [];
  const primaryReference = cleanReferences[0];
  return postJson<{ ok: true; job: AgentJob }>("/api/agent/jobs", csrfToken, {
    role,
    prompt,
    reference_root: primaryReference?.root || "",
    reference_path: primaryReference?.path || "",
    references: cleanReferences,
    session_id: session?.id || "",
    session_title: session?.title || "",
  });
}

export function cancelAgentJob(csrfToken: string, jobId: string) {
  return postJson<{ ok: true; job: AgentJob }>("/api/agent/jobs/cancel", csrfToken, {
    job_id: jobId,
  });
}

export function hideAgentSession(csrfToken: string, sessionId: string) {
  return postJson<{ ok: true; session_id: string; hidden_count: number }>("/api/agent/sessions/hide", csrfToken, {
    session_id: sessionId,
  });
}

export function archiveItem(csrfToken: string, root: string, path: string) {
  return postJson<{ ok: true; folder_url: string }>("/api/actions/archive", csrfToken, { root, path });
}

export function restoreArchiveItem(csrfToken: string, owner: string, archivePath: string) {
  return postJson<{ ok: true; action: string; owner: string; path: string; name: string; view_url: string }>("/api/actions/restore", csrfToken, {
    owner,
    archive_path: archivePath,
  });
}

export function purgeArchiveItem(csrfToken: string, owner: string, archivePath: string) {
  return postJson<{ ok: true; action: string; owner: string; archive_path: string; name: string; size: number }>("/api/actions/purge-archive", csrfToken, {
    owner,
    archive_path: archivePath,
  });
}

export function purgeOldArchiveItems(csrfToken: string, minDays: number) {
  return postJson<{ ok: true; action: string; purged: number; reclaimed_bytes: number; reclaimed_label: string }>("/api/admin/archive/purge-old", csrfToken, {
    min_days: minDays,
  });
}
