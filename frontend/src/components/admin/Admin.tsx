import { type FormEvent, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cleanupAdminActivity, createPortalUser, purgeArchiveItem, purgeOldArchiveItems, resetPortalUserPassword, restoreArchiveItem, setPortalUserDisabled } from "../../api";
import { DEFAULT_ADMIN_ACTIVITY, DEFAULT_ADMIN_SEARCH, SORT_OPTIONS, STATUS_OPTIONS, TYPE_OPTIONS } from "../../constants";
import type {
  AdminActivityEntry,
  AdminActivityFilters,
  AdminActivityPayload,
  AdminArchiveEntry,
  AdminArchivePayload,
  AdminSearchEntry,
  AdminSearchFilters,
  AdminSearchPayload,
  AdminUserPayload,
  AdminSummaryPayload,
} from "../../types";
import { LoadingState } from "../Feedback";

function statusClass(status: string) { return status || ""; }

type AdminUserOption = { username: string; name: string; team: string; disabled?: boolean };

function optionLabel(options: readonly (readonly [string, string])[], value: string) {
  return options.find(([item]) => item === value)?.[1] || value;
}

/* ====================== Admin Overview ====================== */

export function AdminOverviewPanel({
  summary,
  search,
  activity,
  archive,
  onOpenSearch,
  onOpenActivity,
  onOpenArchive,
  onOpenUserReport,
  onOpenAdminbot,
}: {
  summary: AdminSummaryPayload | null;
  search: AdminSearchPayload | null;
  activity: AdminActivityPayload | null;
  archive: AdminArchivePayload | null;
  onOpenSearch: () => void;
  onOpenActivity: () => void;
  onOpenArchive: () => void;
  onOpenUserReport: (username?: string) => void;
  onOpenAdminbot: () => void;
}) {
  const latestEvent = summary?.recent_events[0];
  const recentOutputs = search?.entries.slice(0, 6) || [];
  const recentActivity = activity?.entries.slice(0, 6) || [];
  const memberSummaries = summary?.member_summaries?.slice(0, 5) || [];
  const deniedCount = activity?.summary.denied || 0;
  const archiveCount = archive?.total || 0;
  const activeMemberCount = summary?.active_member_count ?? summary?.member_count ?? 0;
  const disabledMemberCount = summary?.disabled_member_count ?? 0;

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">관리자</p>
          <h1>대시보드</h1>
          <p className="sub">팀 전체 산출물, 작업 흐름, 보관함 상태를 한 화면에서 점검합니다.</p>
        </div>
        <div className="actions">
          <button className="btn" onClick={onOpenSearch}>산출물 검색</button>
          <button className="btn ink" onClick={onOpenActivity}>작업 기록 열기</button>
        </div>
      </div>

      <div className="kpi-grid">
        <Kpi label="팀" value={summary ? summary.team_count.toLocaleString() : "—"} detail={summary?.teams.slice(0, 3).join(", ") || ""} />
        <Kpi
          label="구성원"
          value={summary ? `${activeMemberCount.toLocaleString()}명` : "—"}
          detail={summary ? `비활성 ${disabledMemberCount.toLocaleString()}명` : "활성 사용자"}
          tone={disabledMemberCount ? "warn" : undefined}
        />
        <Kpi label="전체 산출물" value={search ? search.total.toLocaleString() : "—"} detail={search?.truncated ? "스캔 제한 도달" : "검색 인덱스 기준"} />
        <Kpi label="보관함" value={archive ? archive.total.toLocaleString() : "—"} detail="복구 가능한 항목" tone={archive?.total ? "warn" : undefined} />
        <Kpi label="권한 차단" value={activity ? activity.summary.denied.toLocaleString() : "—"} detail={activity ? `전체 ${activity.summary.total.toLocaleString()}건` : "로딩 중"} tone={activity?.summary.denied ? "warn" : undefined} />
      </div>

      <div className="priority-strip">
        <strong>오늘 점검 항목</strong>
        {deniedCount ? <span className="alarm alert">권한 차단 {deniedCount.toLocaleString()}건</span> : <span className="alarm ok">권한 차단 없음</span>}
        {archiveCount ? <span className="alarm warn">보관함 {archiveCount.toLocaleString()}개</span> : <span className="alarm ok">보관함 정상</span>}
        {latestEvent ? <span className="alarm">최근: {latestEvent.action_label} · {latestEvent.actor}</span> : null}
      </div>

      <AdminOpsGuide
        outputTotal={search?.total || 0}
        deniedCount={deniedCount}
        archiveCount={archiveCount}
        latestEvent={latestEvent}
        onOpenSearch={onOpenSearch}
        onOpenActivity={onOpenActivity}
        onOpenArchive={onOpenArchive}
        onOpenUserReport={onOpenUserReport}
        onOpenAdminbot={onOpenAdminbot}
      />

      <div className="card admin-member-card">
        <div className="card-head">
          <h2>사용자 용량 상위</h2>
          <button className="btn ghost sm" onClick={() => onOpenUserReport()}>사용자 관리 →</button>
        </div>
        <div className="member-rank-list">
          {memberSummaries.length ? memberSummaries.map((member) => (
            <button key={member.username} type="button" className="member-rank-row" onClick={() => onOpenUserReport(member.username)}>
              <span>
                <strong>{member.name}</strong>
                <small>{member.username} · {member.team}{member.disabled ? " · 비활성" : ""}</small>
              </span>
              <span className="member-rank-metric">
                <strong>{member.bytes_label}</strong>
                <small>{member.files.toLocaleString()}개 · {member.last_activity}</small>
              </span>
            </button>
          )) : <p style={{ padding: 18, margin: 0, color: "var(--muted)" }}>사용자 용량 정보가 없습니다.</p>}
        </div>
      </div>

      <div className="dash-row">
        <div className="card">
          <div className="card-head">
            <h2>최근 작업 기록</h2>
            <button className="btn ghost sm" onClick={onOpenActivity}>전체 보기 →</button>
          </div>
          <div className="timeline">
            {recentActivity.length ? recentActivity.map((e, i) => (
              <div key={i} className={`timeline-item ${e.status !== "ok" ? "alert" : ""}`}>
                <div className="avatar">{(e.actor_name || e.actor || "?").charAt(0)}</div>
                <div className="what">
                  <strong>{e.action_label}</strong>
                  <small>{e.actor_name || e.actor} · {e.team || "-"}</small>
                  <span className="path">{e.path || e.reason || "-"}</span>
                </div>
                <time>{e.time}</time>
              </div>
            )) : <p style={{ padding: 18, margin: 0, color: "var(--muted)" }}>최근 작업 기록이 없습니다.</p>}
          </div>
        </div>
        <div className="card">
          <div className="card-head">
            <h2>최근 산출물</h2>
            <button className="btn ghost sm" onClick={onOpenSearch}>검색 열기 →</button>
          </div>
          <div className="recent-files">
            {recentOutputs.length ? recentOutputs.map((entry) => (
              <div key={entry.path} className="recent-file">
                <span className="kind-token">{entry.kind_token}</span>
                <div className="meta">
                  <strong>{entry.name}</strong>
                  <small>{entry.owner} · {entry.team} · <span className="tnum">{entry.size_label}</span></small>
                </div>
                {entry.status_label ? <span className={`pill ${statusClass(entry.status)}`}><span className="dot" />{entry.status_label}</span> : <span />}
              </div>
            )) : <p style={{ padding: 18, margin: 0, color: "var(--muted)" }}>표시할 산출물이 없습니다.</p>}
          </div>
        </div>
      </div>
    </>
  );
}

function AdminOpsGuide({
  outputTotal,
  deniedCount,
  archiveCount,
  latestEvent,
  onOpenSearch,
  onOpenActivity,
  onOpenArchive,
  onOpenUserReport,
  onOpenAdminbot,
}: {
  outputTotal: number;
  deniedCount: number;
  archiveCount: number;
  latestEvent?: AdminSummaryPayload["recent_events"][number];
  onOpenSearch: () => void;
  onOpenActivity: () => void;
  onOpenArchive: () => void;
  onOpenUserReport: (username?: string) => void;
  onOpenAdminbot: () => void;
}) {
  return (
    <section className="admin-ops" aria-label="관리자 운영 흐름">
      <div className="ops-head">
        <div>
          <p className="eyebrow">운영 흐름</p>
          <h2>관리자는 여기서 팀 산출물 상태를 정리합니다.</h2>
        </div>
        <button type="button" className="btn ink" onClick={onOpenAdminbot}>Adminbot 점검 요청</button>
      </div>
      <div className="ops-grid">
        <button type="button" className="ops-card" onClick={onOpenSearch}>
          <span className="ops-step">1</span>
          <strong>산출물 검토</strong>
          <small>전체 {outputTotal.toLocaleString()}개 중 소유자, 팀 공유 위치, 검토 상태를 확인합니다.</small>
        </button>
        <button type="button" className={`ops-card ${deniedCount ? "alert" : ""}`} onClick={onOpenActivity}>
          <span className="ops-step">2</span>
          <strong>이상 기록 확인</strong>
          <small>{deniedCount ? `권한 차단 ${deniedCount.toLocaleString()}건을 우선 확인하세요.` : "차단/실패 기록이 없으면 최근 작업 흐름만 훑습니다."}</small>
        </button>
        <button type="button" className={`ops-card ${archiveCount ? "warn" : ""}`} onClick={onOpenArchive}>
          <span className="ops-step">3</span>
          <strong>보관함 관리</strong>
          <small>{archiveCount ? `복구 가능한 보관 항목 ${archiveCount.toLocaleString()}개가 있습니다.` : "삭제 요청 파일은 보관함으로 이동되어 복구할 수 있습니다."}</small>
        </button>
        <button type="button" className="ops-card" onClick={() => onOpenUserReport()}>
          <span className="ops-step">4</span>
          <strong>사용자별 점검</strong>
          <small>개인 작업공간, 팀 공유, 최근 활동을 사용자 단위로 확인합니다.</small>
        </button>
      </div>
      <div className="ops-note">
        <strong>최근 신호</strong>
        <span>{latestEvent ? `${latestEvent.action_label} · ${latestEvent.actor} · ${latestEvent.time}` : "아직 최근 작업 기록이 없습니다."}</span>
      </div>
    </section>
  );
}

function Kpi({ label, value, detail, tone }: { label: string; value: string; detail?: string; tone?: "warn" }) {
  return (
    <div className={`kpi ${tone || ""}`}>
      <small>{label}</small>
      <strong className="tnum">{value}</strong>
      {detail ? <span className="delta">{detail}</span> : null}
    </div>
  );
}

/* ====================== Admin Search ====================== */

export function AdminSearchPanel({
  search,
  filters,
  onFiltersChange,
}: {
  search: AdminSearchPayload | null;
  filters: AdminSearchFilters;
  onFiltersChange: (filters: AdminSearchFilters) => void;
}) {
  function update(key: keyof AdminSearchFilters, value: string) {
    onFiltersChange({ ...filters, [key]: value });
  }
  const applied = [
    filters.q ? { key: "q" as const, label: `검색: ${filters.q}` } : null,
    filters.owner ? { key: "owner" as const, label: `사용자: ${filters.owner}` } : null,
    filters.team ? { key: "team" as const, label: `팀: ${filters.team}` } : null,
    filters.scope ? { key: "scope" as const, label: `공간: ${filters.scope}` } : null,
    filters.type ? { key: "type" as const, label: `유형: ${optionLabel(TYPE_OPTIONS, filters.type)}` } : null,
    filters.status ? { key: "status" as const, label: `상태: ${optionLabel(STATUS_OPTIONS, filters.status)}` } : null,
    filters.sort !== DEFAULT_ADMIN_SEARCH.sort ? { key: "sort" as const, label: `정렬: ${optionLabel(SORT_OPTIONS, filters.sort)}` } : null,
  ].filter(Boolean) as Array<{ key: keyof AdminSearchFilters; label: string }>;

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">관리자</p>
          <h1>전체 산출물 검색</h1>
          <p className="sub">웹 에이전트와 사용자가 만든 산출물을 팀, 사용자, 상태, 유형으로 찾습니다.</p>
        </div>
      </div>
      <div className="card" style={{ padding: 0 }}>
        <div className="filter-bar">
          <label>
            <span>검색</span>
            <input value={filters.q} type="search" placeholder="파일명, 경로, 사용자" onChange={(e) => update("q", e.target.value)} />
          </label>
          <label>
            <span>사용자</span>
            <select value={filters.owner} onChange={(e) => update("owner", e.target.value)}>
              <option value="">전체 사용자</option>
              {search?.users.map((u) => (<option key={u.username} value={u.username}>{u.name} ({u.username})</option>))}
            </select>
          </label>
          <label>
            <span>팀</span>
            <select value={filters.team} onChange={(e) => update("team", e.target.value)}>
              <option value="">전체 팀</option>
              {search?.teams.map((t) => (<option key={t} value={t}>{t}</option>))}
            </select>
          </label>
          <label>
            <span>공간</span>
            <select value={filters.scope} onChange={(e) => update("scope", e.target.value)}>
              <option value="">전체 공간</option>
              <option value="개인 작업공간">개인 작업공간</option>
              <option value="팀 공유">팀 공유</option>
            </select>
          </label>
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
          <button className="btn reset" onClick={() => onFiltersChange(DEFAULT_ADMIN_SEARCH)}>초기화</button>
        </div>
        {applied.length ? (
          <div className="applied-chips" style={{ borderBottom: "1px solid var(--line)" }}>
            {applied.map((item) => (
              <span key={item.key} className="chip">
                {item.label}
                <button type="button" onClick={() => update(item.key, DEFAULT_ADMIN_SEARCH[item.key])}>×</button>
              </span>
            ))}
            <button type="button" className="chip reset" onClick={() => onFiltersChange(DEFAULT_ADMIN_SEARCH)}>모두 해제</button>
          </div>
        ) : null}
        {search ? (
          <>
            <div className="stats-strip">
              <strong className="tnum">검색 결과 {search.total.toLocaleString()}개</strong>
              <span>표시 {search.entries.length.toLocaleString()}개</span>
              <span>스캔 {search.scanned.toLocaleString()}개</span>
              {search.truncated ? <span>스캔 제한 도달</span> : null}
            </div>
            <AdminSearchTable entries={search.entries} />
          </>
        ) : (
          <LoadingState />
        )}
      </div>
    </>
  );
}

function AdminSearchTable({ entries }: { entries: AdminSearchEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="empty-state" role="status">
        <h2>조건에 맞는 산출물이 없습니다.</h2>
        <p>검색어, 사용자, 팀, 상태를 조정해보세요.</p>
      </div>
    );
  }
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>산출물</th>
            <th>소유 / 공간</th>
            <th>유형</th>
            <th>상태</th>
            <th>크기</th>
            <th>수정일</th>
            <th>작업</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.path}>
              <td>
                <div style={{ display: "grid", gridTemplateColumns: "28px 1fr", gap: 10, alignItems: "center" }}>
                  <span className="kind-token" style={{ width: 28, height: 28 }}>{entry.kind_token}</span>
                  <div style={{ minWidth: 0 }}>
                    <strong className="ellipsis">{entry.name}</strong>
                    <small>{entry.path}</small>
                  </div>
                </div>
              </td>
              <td>
                <strong>{entry.owner}</strong>
                <small>{entry.team} · {entry.scope}</small>
              </td>
              <td>{entry.kind_label}</td>
              <td>{entry.status_label ? <span className={`pill ${statusClass(entry.status)}`}><span className="dot" />{entry.status_label}</span> : "—"}</td>
              <td className="tnum">{entry.size_label}</td>
              <td className="tnum">{entry.modified}</td>
              <td className="actions">
                <a className="btn sm ghost" href={entry.view_url}>보기</a>
                <a className="btn sm ghost" href={entry.folder_url}>폴더</a>
                <a className="btn sm" href={entry.download_url}>다운로드</a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ====================== Admin Activity ====================== */

export function AdminActivityPanel({
  csrfToken,
  activity,
  filters,
  onFiltersChange,
  onCleaned,
}: {
  csrfToken: string;
  activity: AdminActivityPayload | null;
  filters: AdminActivityFilters;
  onFiltersChange: (filters: AdminActivityFilters) => void;
  onCleaned: (message: string) => void;
}) {
  const [cleanupConfirmOpen, setCleanupConfirmOpen] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  function update(key: keyof AdminActivityFilters, value: string) {
    onFiltersChange({ ...filters, [key]: value });
  }

  async function cleanActivity() {
    setBusy("cleanup");
    setError("");
    try {
      const result = await cleanupAdminActivity(csrfToken);
      setCleanupConfirmOpen(false);
      onCleaned(`작업 기록에서 차단/테스트성 노이즈 ${result.removed.toLocaleString()}건을 정리했습니다.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "작업 기록을 정리하지 못했습니다.");
    } finally {
      setBusy("");
    }
  }
  const applied = [
    filters.actor ? { key: "actor" as const, label: `사용자: ${filters.actor}` } : null,
    filters.action ? { key: "action" as const, label: `작업: ${activity?.actions.find((item) => item.value === filters.action)?.label || filters.action}` } : null,
    filters.team ? { key: "team" as const, label: `팀: ${filters.team}` } : null,
    filters.q ? { key: "q" as const, label: `검색: ${filters.q}` } : null,
  ].filter(Boolean) as Array<{ key: keyof AdminActivityFilters; label: string }>;
  const quickActions = [
    ["portal_user_created", "계정 생성"],
    ["portal_password_reset", "비밀번호 초기화"],
    ["portal_user_disabled", "비활성화"],
    ["portal_user_enabled", "활성화"],
    ["archive_purged", "영구 삭제"],
    ["permission_denied", "권한 차단"],
  ] as const;

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">관리자</p>
          <h1>작업 기록</h1>
          <p className="sub">기본값은 업로드·상태 변경·팀 공유·보관·실패/차단 기록을 보여줍니다.</p>
        </div>
        <div className="actions">
          <button className="btn" type="button" disabled={!activity?.entries.length} onClick={() => activity && exportActivityCsv(activity.entries)}>CSV 내보내기</button>
          <button className="btn danger" type="button" onClick={() => setCleanupConfirmOpen(true)}>차단 로그 정리</button>
        </div>
      </div>
      <div className="card" style={{ padding: 0 }}>
        {error ? <div className="error-state" role="alert" style={{ margin: 0, borderRadius: 0 }}>{error}</div> : null}
        <div className="filter-bar" style={{ gridTemplateColumns: "minmax(220px,1fr) repeat(3, minmax(160px,.7fr)) auto" }}>
          <label>
            <span>검색</span>
            <input value={filters.q} type="search" placeholder="파일명, 경로, 사유" onChange={(e) => update("q", e.target.value)} />
          </label>
          <label>
            <span>사용자</span>
            <select value={filters.actor} onChange={(e) => update("actor", e.target.value)}>
              <option value="">전체 사용자</option>
              {activity?.users.map((u) => (<option key={u.username} value={u.username}>{u.name} ({u.username})</option>))}
            </select>
          </label>
          <label>
            <span>작업</span>
            <select value={filters.action} onChange={(e) => update("action", e.target.value)}>
              <option value="">전체 작업</option>
              {activity?.actions.map((a) => (<option key={a.value} value={a.value}>{a.label}</option>))}
            </select>
          </label>
          <label>
            <span>팀</span>
            <select value={filters.team} onChange={(e) => update("team", e.target.value)}>
              <option value="">전체 팀</option>
              {activity?.teams.map((t) => (<option key={t} value={t}>{t}</option>))}
            </select>
          </label>
          <button className="btn reset" onClick={() => onFiltersChange(DEFAULT_ADMIN_ACTIVITY)}>초기화</button>
        </div>
        <div className="quick-filter-row" aria-label="관리자 빠른 작업 필터">
          <span>빠른 필터</span>
          {quickActions.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={filters.action === value ? "active" : ""}
              onClick={() => update("action", filters.action === value ? "" : value)}
            >
              {label}
            </button>
          ))}
        </div>
        {applied.length ? (
          <div className="applied-chips" style={{ borderBottom: "1px solid var(--line)" }}>
            {applied.map((item) => (
              <span key={item.key} className="chip">
                {item.label}
                <button type="button" onClick={() => update(item.key, DEFAULT_ADMIN_ACTIVITY[item.key])}>×</button>
              </span>
            ))}
            <button type="button" className="chip reset" onClick={() => onFiltersChange(DEFAULT_ADMIN_ACTIVITY)}>모두 해제</button>
          </div>
        ) : null}
        {activity ? (
          <>
            <div className="stats-strip">
              <strong className="tnum">검색 결과 {activity.summary.total.toLocaleString()}건</strong>
              <span>권한 차단 {activity.summary.denied.toLocaleString()}건</span>
              <span>최근: {activity.summary.latest}</span>
              <span>{activity.limit_note}</span>
            </div>
            <AdminActivityTable entries={activity.entries} />
          </>
        ) : (
          <LoadingState />
        )}
      </div>
      {cleanupConfirmOpen ? (
        <AdminConfirmDialog
          title="관리자 로그를 정리할까요?"
          description="권한 차단, CSRF 차단, 로그인 실패, selftest 같은 운영 노이즈를 백업 후 정리합니다. 업로드, 다운로드, 계정 생성, 보관/복구 기록은 유지됩니다."
          confirmLabel={busy ? "정리 중" : "정리"}
          cancelLabel="취소"
          busy={Boolean(busy)}
          danger
          onCancel={() => setCleanupConfirmOpen(false)}
          onConfirm={cleanActivity}
        />
      ) : null}
    </>
  );
}

function exportActivityCsv(entries: AdminActivityEntry[]) {
  const headers = ["시간", "작업", "사용자", "아이디", "팀", "상태", "대상", "상세"];
  const rows = entries.map((entry) => [
    entry.time,
    entry.action_label,
    entry.actor_name,
    entry.actor,
    entry.team,
    entry.status,
    entry.path,
    entry.reason || entry.file_status_label,
  ]);
  const csv = [headers, ...rows]
    .map((row) => row.map((cell) => `"${String(cell || "").replaceAll('"', '""')}"`).join(","))
    .join("\n");
  const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `workroom-admin-activity-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function AdminActivityTable({ entries }: { entries: AdminActivityEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="empty-state" role="status">
        <h2>조건에 맞는 작업 기록이 없습니다.</h2>
        <p>사용자, 작업 종류, 팀 또는 검색어를 조정해보세요.</p>
      </div>
    );
  }
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>시간</th>
            <th>작업</th>
            <th>사용자</th>
            <th>팀</th>
            <th>상태</th>
            <th>대상</th>
            <th>상세</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry, idx) => (
            <tr key={`${entry.time}-${entry.action}-${entry.path}-${idx}`}>
              <td className="tnum">{entry.time}</td>
              <td><strong>{entry.action_label}</strong></td>
              <td>
                <strong>{entry.actor_name || entry.actor || "—"}</strong>
                <small>{entry.actor}</small>
              </td>
              <td>{entry.team || "—"}</td>
              <td>{entry.status === "ok" ? <span className="pill shared"><span className="dot" />정상</span> : <span className="pill revision"><span className="dot" />{entry.status}</span>}</td>
              <td>
                <strong className="ellipsis">{entry.path || "—"}</strong>
                <small>{entry.root_label}</small>
              </td>
              <td>{entry.reason || entry.file_status_label || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ====================== Admin Archive ====================== */

export function AdminArchivePanel({
  csrfToken,
  archive,
  onRestored,
}: {
  csrfToken: string;
  archive: AdminArchivePayload | null;
  onRestored: (message: string) => void;
}) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [restoreTarget, setRestoreTarget] = useState<AdminArchiveEntry | null>(null);
  const [purgeTarget, setPurgeTarget] = useState<AdminArchiveEntry | null>(null);
  const [purgeOldOpen, setPurgeOldOpen] = useState(false);
  const [ageFilter, setAgeFilter] = useState("all");
  const archiveEntries = archive ? filterArchiveEntries(archive.entries, ageFilter) : [];
  const stale30Count = archive ? filterArchiveEntries(archive.entries, "30").length : 0;

  async function restore(entry: AdminArchiveEntry) {
    setBusy(`restore:${entry.owner}:${entry.archive_path}`);
    setError("");
    try {
      await restoreArchiveItem(csrfToken, entry.owner, entry.archive_path);
      onRestored(`${entry.name} 항목을 복구했습니다.`);
      setRestoreTarget(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "복구하지 못했습니다.");
    } finally {
      setBusy("");
    }
  }

  async function purge(entry: AdminArchiveEntry) {
    setBusy(`purge:${entry.owner}:${entry.archive_path}`);
    setError("");
    try {
      await purgeArchiveItem(csrfToken, entry.owner, entry.archive_path);
      onRestored(`${entry.name} 항목을 보관함에서 영구 삭제했습니다.`);
      setPurgeTarget(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "영구 삭제하지 못했습니다.");
    } finally {
      setBusy("");
    }
  }

  async function purgeOld() {
    setBusy("purge-old");
    setError("");
    try {
      const result = await purgeOldArchiveItems(csrfToken, 30);
      setPurgeOldOpen(false);
      onRestored(`30일 이상 보관 항목 ${result.purged.toLocaleString()}개를 영구 삭제했습니다. 회수 용량: ${result.reclaimed_label}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "오래된 보관 항목을 삭제하지 못했습니다.");
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">관리자</p>
          <h1>보관함</h1>
          <p className="sub">직원이 보관함으로 이동한 산출물을 확인하고 원래 위치로 복구합니다.</p>
        </div>
      </div>
      <div className="card" style={{ padding: 0 }}>
        {error ? <div className="error-state" role="alert" style={{ margin: 0, borderRadius: 0 }}>{error}</div> : null}
        {archive ? (
          <>
            <div className="stats-strip">
              <strong className="tnum">보관 항목 {archive.total.toLocaleString()}개</strong>
              <span>보관 용량 {archive.total_bytes_label}</span>
              <span>30일 이상 {stale30Count.toLocaleString()}개</span>
              <span>최대 표시 {archive.limit.toLocaleString()}개</span>
            </div>
            <div className={`archive-policy-strip ${stale30Count ? "warn" : "ok"}`}>
              <div>
                <strong>30일 보관 정책</strong>
                <span>{stale30Count ? `30일 이상 보관된 항목 ${stale30Count.toLocaleString()}개를 검토하세요.` : "30일 이상 오래된 보관 항목이 없습니다."}</span>
              </div>
              <div className="archive-policy-actions">
                <button type="button" className="btn sm ghost" onClick={() => setAgeFilter("30")}>30일 이상 보기</button>
                {stale30Count ? <button type="button" className="btn sm danger" onClick={() => setPurgeOldOpen(true)}>30일 이상 영구삭제</button> : null}
              </div>
            </div>
            <div className="archive-control-row">
              <div className="archive-owner-strip" aria-label="사용자별 보관함 용량">
                {archive.owners.slice(0, 4).map((owner) => (
                  <span key={owner.owner}>
                    <strong>{owner.owner_name}</strong> {owner.count.toLocaleString()}개 · {owner.bytes_label}
                  </span>
                ))}
              </div>
              <div className="archive-age-filter" aria-label="보관 기간 필터">
                <button className={ageFilter === "all" ? "active" : ""} type="button" onClick={() => setAgeFilter("all")}>전체</button>
                <button className={ageFilter === "30" ? "active" : ""} type="button" onClick={() => setAgeFilter("30")}>30일+</button>
                <button className={ageFilter === "60" ? "active" : ""} type="button" onClick={() => setAgeFilter("60")}>60일+</button>
                <button className={ageFilter === "90" ? "active" : ""} type="button" onClick={() => setAgeFilter("90")}>90일+</button>
              </div>
            </div>
            <AdminArchiveTable entries={archiveEntries} busy={busy} onRestore={setRestoreTarget} onPurge={setPurgeTarget} />
          </>
        ) : (
          <LoadingState />
        )}
      </div>
      {restoreTarget ? (
        <AdminConfirmDialog
          title="보관 항목을 복구할까요?"
          description={`${restoreTarget.name} 항목을 원래 위치로 복구합니다. 같은 이름이 있으면 안전한 새 이름으로 복구됩니다.`}
          confirmLabel={busy ? "복구 중" : "복구"}
          cancelLabel="취소"
          busy={Boolean(busy)}
          onCancel={() => setRestoreTarget(null)}
          onConfirm={() => restore(restoreTarget)}
        />
      ) : null}
      {purgeTarget ? (
        <AdminConfirmDialog
          title="보관 항목을 영구 삭제할까요?"
          description={`${purgeTarget.name} 항목을 보관함에서 완전히 삭제합니다. 소유자: ${purgeTarget.owner_name}, 원래 위치: ${purgeTarget.original_path}. 이 작업은 되돌릴 수 없습니다.`}
          confirmLabel={busy ? "삭제 중" : "영구 삭제"}
          cancelLabel="취소"
          busy={Boolean(busy)}
          danger
          onCancel={() => setPurgeTarget(null)}
          onConfirm={() => purge(purgeTarget)}
        />
      ) : null}
      {purgeOldOpen ? (
        <AdminConfirmDialog
          title="30일 이상 보관 항목을 모두 삭제할까요?"
          description={`현재 표시 기준 30일 이상 보관된 항목 ${stale30Count.toLocaleString()}개가 대상입니다. 보관함 용량 관리를 위한 영구 삭제이며 작업 후 복구할 수 없습니다.`}
          confirmLabel={busy ? "삭제 중" : "영구 삭제"}
          cancelLabel="취소"
          busy={Boolean(busy)}
          danger
          onCancel={() => setPurgeOldOpen(false)}
          onConfirm={purgeOld}
        />
      ) : null}
    </>
  );
}

function filterArchiveEntries(entries: AdminArchiveEntry[], ageFilter: string) {
  if (ageFilter === "all") return entries;
  const minDays = Number(ageFilter);
  const cutoff = Date.now() - minDays * 24 * 60 * 60 * 1000;
  return entries.filter((entry) => {
    const archivedAt = Date.parse(entry.archived_at.replace(" ", "T"));
    return Number.isFinite(archivedAt) && archivedAt <= cutoff;
  });
}

function AdminArchiveTable({
  entries,
  busy,
  onRestore,
  onPurge,
}: {
  entries: AdminArchiveEntry[];
  busy: string;
  onRestore: (entry: AdminArchiveEntry) => void;
  onPurge: (entry: AdminArchiveEntry) => void;
}) {
  if (entries.length === 0) {
    return (
      <div className="empty-state" role="status">
        <h2>복구할 보관 항목이 없습니다.</h2>
        <p>직원이 보관함으로 이동한 항목이 생기면 여기에 표시됩니다.</p>
      </div>
    );
  }
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>소유자</th>
            <th>유형</th>
            <th>원래 위치</th>
            <th>크기</th>
            <th>보관일</th>
            <th>작업</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const restoreKey = `restore:${entry.owner}:${entry.archive_path}`;
            const purgeKey = `purge:${entry.owner}:${entry.archive_path}`;
            return (
              <tr key={`${entry.owner}:${entry.archive_path}`}>
                <td className="actions">
                  <strong>{entry.owner_name}</strong>
                  <small>{entry.team}</small>
                </td>
                <td>{entry.kind_label}</td>
                <td>
                  <strong className="ellipsis">{entry.name}</strong>
                  <small>{entry.original_path}</small>
                </td>
                <td className="tnum">{entry.size_label}</td>
                <td>
                  <strong className="tnum">{entry.archived_at}</strong>
                  <small>처리: {entry.actor}</small>
                </td>
                <td>
                  <button className="btn sm ink" type="button" disabled={Boolean(busy)} onClick={() => onRestore(entry)}>
                    {busy === restoreKey ? "복구 중" : "복구"}
                  </button>
                  <button className="btn sm danger" type="button" disabled={Boolean(busy)} onClick={() => onPurge(entry)}>
                    {busy === purgeKey ? "삭제 중" : "영구 삭제"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ====================== Admin User Report ====================== */

export function AdminUserPanel({
  report,
  selectedUsername,
  users,
  csrfToken,
  onSelectUser,
  onOpenActivity,
  onUserChanged,
}: {
  report: AdminUserPayload | null;
  selectedUsername: string;
  users: AdminUserOption[];
  csrfToken: string;
  onSelectUser: (username: string) => void;
  onOpenActivity: (username: string) => void;
  onUserChanged: (message: string, username?: string) => void;
}) {
  const teams = Array.from(new Set(users.map((u) => u.team).filter(Boolean))).sort();
  const [newUsername, setNewUsername] = useState("");
  const [newName, setNewName] = useState("");
  const [newTeam, setNewTeam] = useState("");
  const [customTeam, setCustomTeam] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [issuedPassword, setIssuedPassword] = useState<{ title: string; username: string; password: string } | null>(null);
  const [copyState, setCopyState] = useState("");
  const credentialPassword = report?.credentials.password
    ? {
      title: `${report.credentials.name} 발급 정보`,
      username: report.credentials.username,
      password: report.credentials.password,
      source: "stored" as const,
    }
    : null;
  const visiblePassword = issuedPassword ? { ...issuedPassword, source: "issued" as const } : credentialPassword;

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const team = (customTeam.trim() || newTeam || teams[0] || "").toLowerCase();
    if (!team) {
      setError("팀을 먼저 선택하세요.");
      return;
    }
    setError("");
    setBusy("create");
    try {
      const result = await createPortalUser(csrfToken, newUsername.trim(), newName.trim(), team);
      setIssuedPassword({ title: "신규 계정 임시 비밀번호", username: result.user.username, password: result.password });
      setCopyState("");
      setNewUsername("");
      setNewName("");
      setNewTeam(team);
      setCustomTeam("");
      onUserChanged(`${result.user.name} 계정을 만들었습니다.`, result.user.username);
    } catch (err) {
      setError(err instanceof Error ? err.message : "계정을 만들지 못했습니다.");
    } finally {
      setBusy("");
    }
  }

  async function handleResetPassword(username: string) {
    setError("");
    setBusy("reset");
    try {
      const result = await resetPortalUserPassword(csrfToken, username);
      setIssuedPassword({ title: "초기화된 임시 비밀번호", username: result.username, password: result.password });
      setCopyState("");
      onUserChanged("비밀번호를 초기화했습니다.", username);
    } catch (err) {
      setError(err instanceof Error ? err.message : "비밀번호를 초기화하지 못했습니다.");
    } finally {
      setBusy("");
    }
  }

  async function handleToggleDisabled(username: string, disabled: boolean) {
    setError("");
    setBusy(disabled ? "disable" : "enable");
    try {
      const result = await setPortalUserDisabled(csrfToken, username, disabled);
      onUserChanged(result.user.disabled ? "계정을 비활성화했습니다." : "계정을 활성화했습니다.", username);
    } catch (err) {
      setError(err instanceof Error ? err.message : "계정 상태를 변경하지 못했습니다.");
    } finally {
      setBusy("");
    }
  }

  function copyVisiblePassword() {
    if (!visiblePassword) return;
    if (!navigator.clipboard) {
      setCopyState("직접 선택해서 복사하세요.");
      return;
    }
    navigator.clipboard.writeText(visiblePassword.password)
      .then(() => {
        setCopyState("복사됨");
        window.setTimeout(() => setCopyState(""), 1800);
      })
      .catch(() => setCopyState("복사 실패"));
  }

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">관리자</p>
          <h1>사용자 관리</h1>
          <p className="sub">계정 발급, 임시 비밀번호 초기화, 계정 비활성화는 관리자만 수행합니다.</p>
        </div>
        <div className="actions">
          <select
            value={selectedUsername}
            onChange={(e) => onSelectUser(e.target.value)}
            style={{ height: 34, borderRadius: 10, border: "1px solid var(--line)", background: "var(--surface)", padding: "0 10px", minWidth: 220, fontSize: 13 }}
          >
            <option value="">사용자 선택</option>
            {users.map((u) => (<option key={u.username} value={u.username}>{u.disabled ? "[비활성] " : ""}{u.name} ({u.username}) · {u.team}</option>))}
          </select>
        </div>
      </div>
      <div className="account-admin-grid">
        <form className="card account-form" onSubmit={handleCreateUser}>
          <div>
            <p className="eyebrow">계정 발급</p>
            <h2>관리자 전용 계정 만들기</h2>
            <p className="sub">사용자는 직접 계정을 만들 수 없습니다. 팀을 선택하면 개인 작업공간과 dev/research/summary 폴더가 자동 생성됩니다.</p>
          </div>
          <div className="account-policy" aria-label="계정 운영 기준">
            <div>
              <strong>관리자 발급</strong>
              <span>계정 생성과 초기화는 admin만 처리합니다.</span>
            </div>
            <div>
              <strong>1:1 전달</strong>
              <span>임시 비밀번호는 자동 발송되지 않으며 사용자 본인에게만 전달합니다.</span>
            </div>
            <div>
              <strong>첫 로그인 변경</strong>
              <span>발급/초기화된 비밀번호로 로그인하면 새 비밀번호 설정이 필요합니다.</span>
            </div>
          </div>
          <div className="account-form-fields">
            <label>
              <span>아이디</span>
              <input value={newUsername} onChange={(e) => setNewUsername(e.target.value)} placeholder="예: intern01" autoComplete="off" />
            </label>
            <label>
              <span>이름</span>
              <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="예: 홍길동" autoComplete="off" />
            </label>
            <label>
              <span>팀</span>
              <select value={newTeam || teams[0] || ""} onChange={(e) => setNewTeam(e.target.value)}>
                {teams.length ? teams.map((team) => <option key={team} value={team}>{team}</option>) : <option value="">팀 없음</option>}
              </select>
            </label>
            <label>
              <span>새 팀명</span>
              <input value={customTeam} onChange={(e) => setCustomTeam(e.target.value)} placeholder="선택 입력: new_team" autoComplete="off" />
            </label>
          </div>
          {error ? <p className="form-error">{error}</p> : null}
          <div className="account-form-actions">
            <button type="submit" className="btn ink" disabled={busy === "create"}>{busy === "create" ? "생성 중" : "계정 생성"}</button>
          </div>
        </form>
        <div className="card issued-password">
          <p className="eyebrow">아이디 / 비밀번호</p>
          {visiblePassword ? (
            <>
              <h2>{visiblePassword.title}</h2>
              <p className="sub">
                {visiblePassword.source === "issued"
                  ? `${visiblePassword.username} 사용자 본인에게만 안전하게 전달하세요. 기존 비밀번호는 즉시 무효화되고, 로그인 후 새 비밀번호 설정 화면이 열립니다.`
                  : "관리자가 발급한 비밀번호 기록입니다. 사용자가 직접 새 비밀번호로 변경하면 더 이상 표시되지 않습니다."}
              </p>
              <div className="credential-row">
                <span>아이디</span>
                <strong>{visiblePassword.username}</strong>
              </div>
              <div className="issued-password-row">
                <input value={visiblePassword.password} readOnly aria-label="발급 비밀번호" />
                <button type="button" className="btn" onClick={copyVisiblePassword}>{copyState === "복사됨" ? "복사됨" : "복사"}</button>
              </div>
              {copyState ? <span className="copy-feedback" role="status">{copyState}</span> : null}
            </>
          ) : report?.credentials.status === "changed" ? (
            <>
              <h2>사용자가 직접 변경했습니다.</h2>
              <p className="sub">현재 비밀번호는 관리자 화면에 표시하지 않습니다. 필요하면 비밀번호 초기화로 새 임시 비밀번호를 발급하세요.</p>
              <div className="credential-row">
                <span>아이디</span>
                <strong>{report.credentials.username}</strong>
              </div>
              <span className="credential-status">{report.credentials.status_label}</span>
            </>
          ) : (
            <>
              <h2>{selectedUsername ? "비밀번호 기록이 없습니다." : "발급 후 여기에 표시됩니다."}</h2>
              <p className="sub">{selectedUsername ? "선택한 사용자에게 새 임시 비밀번호가 필요하면 초기화하세요." : "생성 또는 초기화 직후 한 번 확인하고 사용자 본인에게만 전달하세요. 자동 발송은 되지 않습니다."}</p>
            </>
          )}
        </div>
      </div>
      <div className="card" style={{ padding: 0 }}>
        {!selectedUsername ? (
          <div className="empty-state" role="status">
            <h2>사용자를 선택하세요.</h2>
            <p>사용자별 작업 현황과 최근 산출물을 볼 수 있습니다.</p>
          </div>
        ) : !report ? (
          <LoadingState />
        ) : (
          <AdminUserReport
            report={report}
            busy={busy}
            onOpenActivity={onOpenActivity}
            onResetPassword={() => handleResetPassword(report.user.username)}
            onToggleDisabled={() => handleToggleDisabled(report.user.username, !report.user.disabled)}
          />
        )}
      </div>
    </>
  );
}

function AdminUserReport({
  report,
  busy,
  onOpenActivity,
  onResetPassword,
  onToggleDisabled,
}: {
  report: AdminUserPayload;
  busy: string;
  onOpenActivity: (u: string) => void;
  onResetPassword: () => void;
  onToggleDisabled: () => void;
}) {
  const recentFiles = report.recent_files.slice(0, 5);
  const recentEvents = report.recent_events.slice(0, 5);
  const hiddenFiles = Math.max(report.recent_files.length - recentFiles.length, 0);
  const hiddenEvents = Math.max(report.recent_events.length - recentEvents.length, 0);
  return (
    <>
      <div className="user-card">
        <div className="avatar">{report.user.name.slice(0, 1)}</div>
        <div className="who">
          <h2>{report.user.name} <span style={{ color: "var(--muted)", fontSize: 14, fontWeight: 500, marginLeft: 6 }}>@{report.user.username}</span></h2>
          <p>{report.user.team}</p>
        </div>
        <div className="meta">
          {report.user.disabled ? <span className="pill danger">비활성</span> : <span className="pill shared">활성</span>}
          <span className="pill ink">개인 파일 {report.personal.files}개</span>
          <span className="pill shared">팀 공유 {report.shared.files}개</span>
          <button className="btn sm" onClick={() => onOpenActivity(report.user.username)}>이 사용자 기록</button>
        </div>
      </div>
      <div className="user-report-actions">
        <a className="btn sm" href={report.personal.url}>개인 폴더 열기</a>
        <a className="btn sm" href={report.shared.url}>공유 폴더 열기</a>
        <button className="btn sm ink" type="button" onClick={() => onOpenActivity(report.user.username)}>전체 작업 기록 보기</button>
        <button className="btn sm" type="button" disabled={Boolean(busy)} onClick={onResetPassword}>
          {busy === "reset" ? "초기화 중" : "비밀번호 초기화"}
        </button>
        <button className={`btn sm ${report.user.disabled ? "ink" : "danger"}`} type="button" disabled={Boolean(busy)} onClick={onToggleDisabled}>
          {report.user.disabled ? (busy === "enable" ? "활성화 중" : "계정 활성화") : (busy === "disable" ? "비활성화 중" : "계정 비활성화")}
        </button>
      </div>
      <div className="user-metrics">
        <div className="user-metric"><small>개인 용량</small><strong className="tnum">{report.personal.bytes_label}</strong><span className="sub">파일 {report.personal.files}개</span></div>
        <div className="user-metric"><small>팀 공유 용량</small><strong className="tnum">{report.shared.bytes_label}</strong><span className="sub">파일 {report.shared.files}개</span></div>
        <div className="user-metric"><small>업로드</small><strong className="tnum">{report.actions.upload}</strong><span className="sub">최근 30일</span></div>
        <div className="user-metric"><small>팀 공유</small><strong className="tnum">{report.actions.move_to_shared}</strong><span className="sub">최근 30일</span></div>
        <div className="user-metric"><small>상태 변경</small><strong className="tnum">{report.actions.status_update}</strong><span className="sub">최근 30일</span></div>
        <div className="user-metric"><small>미리보기</small><strong className="tnum">{report.actions.preview_open}</strong><span className="sub">최근 30일</span></div>
      </div>
      <div className="split-cols">
        <section>
          <h3>
            <span>최근 개인 파일</span>
            <em className="tnum">{recentFiles.length} / {report.recent_files.length}</em>
          </h3>
          {recentFiles.length ? (
            <ul>
              {recentFiles.map((file) => (
                <li key={file.path}>
                  <strong><a href={file.url}>{file.name}</a></strong>
                  <small>{file.path} · {file.size_label} · {file.modified}</small>
                </li>
              ))}
            </ul>
          ) : (
            <p style={{ color: "var(--muted)" }}>최근 파일이 없습니다.</p>
          )}
          {hiddenFiles ? <button type="button" className="inline-more" onClick={() => window.location.assign(report.personal.url)}>나머지 {hiddenFiles.toLocaleString()}개는 개인 폴더에서 보기</button> : null}
        </section>
        <section>
          <h3>
            <span>최근 작업 기록</span>
            <em className="tnum">{recentEvents.length} / {report.recent_events.length}</em>
          </h3>
          {recentEvents.length ? (
            <ul>
              {recentEvents.map((event, idx) => (
                <li key={`${event.time}-${event.action}-${idx}`} className={event.status !== "ok" ? "alert" : ""}>
                  <strong>{event.action_label}</strong>
                  <small>{event.path || "—"} · {event.time}</small>
                </li>
              ))}
            </ul>
          ) : (
            <p style={{ color: "var(--muted)" }}>최근 작업 기록이 없습니다.</p>
          )}
          {hiddenEvents ? <button type="button" className="inline-more" onClick={() => onOpenActivity(report.user.username)}>나머지 {hiddenEvents.toLocaleString()}건은 작업 기록에서 보기</button> : null}
        </section>
      </div>
    </>
  );
}

function AdminConfirmDialog({
  title,
  description,
  confirmLabel,
  cancelLabel,
  busy,
  danger = false,
  onCancel,
  onConfirm,
}: {
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel: string;
  busy: boolean;
  danger?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    cancelRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
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
        aria-labelledby="admin-confirm-title"
        aria-describedby="admin-confirm-description"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="confirm-icon" aria-hidden="true">!</div>
        <div className="confirm-copy">
          <h2 id="admin-confirm-title">{title}</h2>
          <p id="admin-confirm-description">{description}</p>
        </div>
        <div className="confirm-actions">
          <button ref={cancelRef} type="button" className="btn" disabled={busy} onClick={onCancel}>
            {cancelLabel}
          </button>
          <button type="button" className={`btn ${danger ? "danger solid" : "ink solid"}`} disabled={busy} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  );
}
