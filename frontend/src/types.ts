export type RootInfo = {
  id: string;
  label: string;
  kind: string;
  kind_label: string;
  description: string;
  url: string;
};

export type SessionPayload = {
  user: {
    username: string;
    name: string;
    is_admin: boolean;
    team: string;
    must_change_password: boolean;
  };
  csrf_token: string;
  roots: RootInfo[];
};

export type FolderFilters = {
  q: string;
  type: string;
  status: string;
  sort: string;
};

export type FolderEntry = {
  name: string;
  path: string;
  is_dir: boolean;
  kind: string;
  kind_label: string;
  kind_token: string;
  status: string;
  status_label: string;
  size: number;
  size_label: string;
  modified: string;
  url: string;
  download_url: string;
  can_archive: boolean;
  can_share: boolean;
  can_agent_share: boolean;
  can_copy_to_personal: boolean;
  share_plan?: { target: string; target_label: string };
};

export type FolderPayload = {
  root: RootInfo;
  path: string;
  title_path: string;
  parent_url: string;
  download_url: string;
  can_upload: boolean;
  upload_targets: Array<{ path: string; label: string; url: string }>;
  filters: Record<string, string>;
  entries: FolderEntry[];
  entry_count: number;
  entry_offset: number;
  entry_limit: number;
  has_more: boolean;
  summary?: {
    files: number;
    dirs: number;
    bytes: number;
    truncated: boolean;
    last_activity: string;
  };
};

export type FilePayload = {
  root: RootInfo;
  path: string;
  name: string;
  kind_label: string;
  kind_token: string;
  status: string;
  status_label: string;
  size_label: string;
  modified: string;
  folder_url: string;
  view_url: string;
  preview_url: string;
  download_url: string;
  can_archive: boolean;
  can_share: boolean;
  can_agent_share: boolean;
  can_copy_to_personal: boolean;
  share_plan?: { target: string; target_label: string };
  events: Array<{ time: string; action: string; action_label: string; actor: string }>;
};

export type AgentRoleOption = {
  role: string;
  profile: string;
  label: string;
  description: string;
  folder: string;
  placeholder: string;
  output_hint: string;
  templates: string[];
};

export type AgentJob = {
  id: string;
  session_id: string;
  session_title: string;
  hidden: boolean;
  status: string;
  status_label: string;
  role: string;
  role_label: string;
  profile: string;
  prompt: string;
  created_at: string;
  updated_at: string;
  started_at: string;
  finished_at: string;
  username: string;
  user_name: string;
  team: string;
  output_root: string;
  output_path: string;
  reference_root: string;
  reference_path: string;
  references: Array<{ root: string; path: string }>;
  summary: string;
  assistant_reply: string;
  hermes_session_id: string;
  error: string;
  log_path: string;
};

export type AgentJobsPayload = {
  jobs: AgentJob[];
  roles: AgentRoleOption[];
};

export type AdminSummaryPayload = {
  member_count: number;
  active_member_count: number;
  disabled_member_count: number;
  team_count: number;
  teams: string[];
  member_summaries: Array<{
    username: string;
    name: string;
    team: string;
    disabled?: boolean;
    files: number;
    bytes: number;
    bytes_label: string;
    last_activity: string;
  }>;
  recent_events: Array<{
    time: string;
    action: string;
    action_label: string;
    actor: string;
    team: string;
    path: string;
  }>;
  maintenance: Record<string, unknown>;
};

export type AdminSearchFilters = {
  q: string;
  type: string;
  status: string;
  owner: string;
  team: string;
  scope: string;
  sort: string;
};

export type AdminSearchEntry = {
  name: string;
  path: string;
  owner: string;
  owner_username: string;
  team: string;
  scope: string;
  kind: string;
  kind_label: string;
  kind_token: string;
  status: string;
  status_label: string;
  size: number;
  size_label: string;
  modified: string;
  view_url: string;
  folder_url: string;
  download_url: string;
};

export type AdminSearchPayload = {
  filters: AdminSearchFilters & { date_from: string; date_to: string };
  users: Array<{ username: string; name: string; team: string; disabled?: boolean }>;
  teams: string[];
  entries: AdminSearchEntry[];
  total: number;
  scanned: number;
  truncated: boolean;
  entry_limit: number;
};

export type AdminActivityFilters = {
  actor: string;
  action: string;
  team: string;
  q: string;
  include_tests: string;
};

export type AdminActivityEntry = {
  time: string;
  action: string;
  action_label: string;
  actor: string;
  actor_name: string;
  team: string;
  status: string;
  path: string;
  root_label: string;
  reason: string;
  file_status_label: string;
};

export type AdminActivityPayload = {
  filters: AdminActivityFilters;
  users: Array<{ username: string; name: string; team: string; disabled?: boolean }>;
  teams: string[];
  actions: Array<{ value: string; label: string }>;
  summary: { total: number; denied: number; latest: string };
  entries: AdminActivityEntry[];
  limit_note: string;
};

export type AdminArchiveEntry = {
  owner: string;
  owner_name: string;
  team: string;
  archive_path: string;
  original_path: string;
  name: string;
  kind: string;
  kind_label: string;
  size: number;
  size_label: string;
  archived_at: string;
  actor: string;
  view_url: string;
  preview_url: string;
  download_url: string;
};

export type AdminArchiveOwnerSummary = {
  owner: string;
  owner_name: string;
  team: string;
  count: number;
  bytes: number;
  bytes_label: string;
};

export type AdminArchivePayload = {
  entries: AdminArchiveEntry[];
  total: number;
  limit: number;
  total_bytes: number;
  total_bytes_label: string;
  owners: AdminArchiveOwnerSummary[];
};

export type AdminUserPayload = {
  user: { username: string; name: string; team: string; disabled?: boolean };
  credentials: {
    username: string;
    name: string;
    password: string;
    status: string;
    status_label: string;
    must_change_password: boolean;
    changed_at: string;
    issued_at: string;
  };
  personal: { exists: boolean; files: number; bytes: number; bytes_label: string; last_activity: string; url: string };
  shared: { exists: boolean; files: number; bytes: number; bytes_label: string; last_activity: string; url: string };
  actions: { upload: number; preview_open: number; move_to_shared: number; status_update: number };
  recent_files: Array<{ path: string; name: string; size: number; size_label: string; modified: string; url: string }>;
  recent_events: Array<{ time: string; action: string; action_label: string; path: string; status: string }>;
};
