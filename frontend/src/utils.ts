import { SHARE_TARGETS } from "./constants";

export function parentPath(path: string) {
  const parts = path.split("/").filter(Boolean);
  parts.pop();
  return parts.join("/");
}

export function firstPathSegment(path: string) {
  return path.split("/").filter(Boolean)[0] || "";
}

export function shareLabel(target: string) {
  const option = SHARE_TARGETS.find(([value]) => value === target);
  return option ? `${option[1]}로 이동` : "팀 공유공간으로 이동";
}
