import type { AdminActivityFilters, AdminSearchFilters, FolderFilters } from "./types";

export const STATUS_OPTIONS = [
  ["active", "작업중"],
  ["new", "새 작업물"],
  ["review_needed", "검토 필요"],
  ["revision_needed", "수정 필요"],
  ["organized", "정리됨"],
  ["shared", "팀 공유됨"],
] as const;

export const SHARE_TARGETS = [
  ["research", "팀 리서치 공유"],
  ["dev", "팀 개발 공유"],
  ["summary", "팀 요약 공유"],
  ["handoff", "팀 인수인계 공유"],
] as const;

export const DEFAULT_TEAM_SHARED_FOLDER = "research";

export const DEFAULT_FILTERS: FolderFilters = { q: "", type: "", status: "", sort: "name" };

export const DEFAULT_ADMIN_SEARCH: AdminSearchFilters = {
  q: "",
  type: "",
  status: "",
  owner: "",
  team: "",
  scope: "",
  sort: "modified",
};

export const DEFAULT_ADMIN_ACTIVITY: AdminActivityFilters = {
  actor: "",
  action: "",
  team: "",
  q: "",
  include_tests: "",
};

export const TYPE_OPTIONS = [
  ["", "전체 유형"],
  ["folder", "폴더"],
  ["document", "문서"],
  ["code", "코드"],
  ["image", "이미지"],
  ["archive", "압축"],
  ["other", "기타"],
] as const;

export const SORT_OPTIONS = [
  ["name", "이름순"],
  ["modified", "최근 수정순"],
  ["size", "크기순"],
  ["type", "유형순"],
] as const;
