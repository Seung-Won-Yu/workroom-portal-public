export type Selection =
  | { type: "folder"; root: string; path: string }
  | { type: "file"; root: string; path: string };

export type AppView = "files" | "admin-overview" | "admin-search" | "admin-activity" | "admin-archive" | "admin-user";
