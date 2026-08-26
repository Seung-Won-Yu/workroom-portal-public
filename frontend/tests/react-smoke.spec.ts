import { expect, test } from "@playwright/test";
import { dirname } from "node:path";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";

function portalPassword(username: string) {
  const passwordFile = "/home/portal/workspaces/admin/portal_initial_passwords.txt";
  for (const line of readFileSync(passwordFile, "utf-8").split(/\r?\n/)) {
    const [user, , password] = line.split("\t");
    if (user === username && password) return password;
  }
  throw new Error(`${username} password not found`);
}

async function login(page: import("@playwright/test").Page, username = "admin") {
  await page.goto("/login");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(portalPassword(username));
  await page.getByRole("button", { name: "로그인" }).click();
  await page.waitForLoadState("networkidle");
}

function agentJob(role: string, outputPath: string, prompt: string) {
  const now = "2026-05-26T15:10:00+09:00";
  const profile = role === "summary" ? "summarybot" : `${role}bot`;
  return JSON.stringify({
    id: `qa-${role}-session`,
    session_id: `qa-${role}`,
    session_title: `${role} QA 세션`,
    status: "done",
    role,
    profile,
    prompt,
    created_at: now,
    updated_at: now,
    started_at: now,
    finished_at: now,
    username: "user1",
    user_name: "사용자1",
    team: "team-alpha",
    output_root: "personal",
    output_path: outputPath,
    reference_root: "",
    reference_path: "",
    references: [],
    summary: "QA 산출물",
    assistant_reply: "요청한 산출물을 만들었습니다.",
    hermes_session_id: `qa-hermes-${role}`,
    error: "",
    log_path: "",
  });
}

test("React app restores a folder route and opens an output preview", async ({ page }, testInfo) => {
  const fixtureName = `qa-preview-route-${testInfo.project.name}.md`;
  const fixturePath = `/home/portal/workspaces/team-alpha/user1/dev/${fixtureName}`;
  mkdirSync(dirname(fixturePath), { recursive: true });
  writeFileSync(fixturePath, "# QA preview route\n\n관리자 전체 작업공간 미리보기 확인용 문서입니다.\n");

  try {
    await login(page);
    await page.goto(`/app?root=all&path=team-alpha/user1/dev&q=${encodeURIComponent(fixtureName)}`);

    await expect(page.getByRole("heading", { name: "전체 작업공간", exact: true })).toBeVisible();
    await expect(page.getByText("/team-alpha/user1/dev")).toBeVisible();
    const firstEntry = page.locator(".entry").first();
    await expect(firstEntry).toBeVisible();
    await expect(page).toHaveURL(/root=all/);
    await expect(page).toHaveURL(/path=team-alpha%2Fhcr%2Fdev/);

    const firstEntryName = await firstEntry.locator(".name strong").innerText();
    await firstEntry.click();
    await expect(page).toHaveURL(/file=team-alpha%2Fhcr%2Fdev%2F/);
    await expect(page.getByRole("heading", { name: firstEntryName })).toBeVisible();
    await expect(page.getByText("검토 후 처리")).toBeVisible();
    await expect(page.locator(".preview-pane")).toHaveCount(1);
    await expect(page.locator(".preview-pane")).toBeInViewport();
    const desktopDetailMetrics = await page.locator(".preview-pane").evaluate((element) => ({
      height: element.getBoundingClientRect().height,
      innerHeight: window.innerHeight,
      innerWidth: window.innerWidth,
      scrollHeight: element.scrollHeight,
    }));
    if (desktopDetailMetrics.innerWidth > 960) {
      expect(desktopDetailMetrics.height).toBeLessThanOrEqual(desktopDetailMetrics.innerHeight - 80);
      expect(desktopDetailMetrics.scrollHeight).toBeGreaterThanOrEqual(desktopDetailMetrics.height - 4);
    }
    await expect(page.locator(".preview-pane")).toBeVisible();
    await expect(page.locator("iframe").first()).toHaveAttribute("src", /\/preview\?root=all/);

    await page.reload();
    await page.waitForLoadState("networkidle");
    const viewport = page.viewportSize();
    if (viewport && viewport.width <= 960) {
      await expect(page.getByRole("button", { name: "목록" })).toBeVisible();
      await page.getByRole("button", { name: "목록" }).click();
    }
    await expect(page.getByRole("button", { name: new RegExp(firstEntryName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) })).toBeVisible();
    await expect(page.locator(".entry-list")).toBeVisible();
  } finally {
    rmSync(fixturePath, { force: true });
  }
});

test("React admin tabs render and preserve view state", async ({ page }) => {
  await login(page);
  await page.goto("/app");

  await expect(page.getByRole("heading", { name: "대시보드" })).toBeVisible();
  await expect(page.locator(".admin-ops")).toBeVisible();
  await page.getByRole("button", { name: "Adminbot 점검 요청" }).click();
  await expect(page).toHaveURL(/root=personal/);
  await expect(page).toHaveURL(/path=admin/);
  await page.goto("/app");
  await expect(page.getByRole("button", { name: "관리자 대시보드" })).toHaveClass(/active/);
  await page.getByRole("button", { name: "전체 산출물" }).click();
  await expect(page).toHaveURL(/view=admin-search/);
  await expect(page.getByRole("heading", { name: "전체 산출물 검색" })).toBeVisible();
  await page.locator(".filter-bar select").nth(3).selectOption("code");
  await page.locator(".filter-bar select").nth(4).selectOption("active");
  await expect(page).toHaveURL(/type=code/);
  await expect(page).toHaveURL(/status=active/);
  await page.reload();
  await expect(page.locator(".filter-bar select").nth(3)).toHaveValue("code");
  await expect(page.locator(".filter-bar select").nth(4)).toHaveValue("active");

  await page.getByRole("button", { name: "작업 기록" }).click();
  await expect(page).toHaveURL(/view=admin-activity/);
  await expect(page.getByRole("heading", { name: "작업 기록", exact: true })).toBeVisible();
  await page.locator(".filter-bar select").nth(1).selectOption("upload");
  await expect(page).toHaveURL(/action=upload/);
  await page.reload();
  await expect(page.locator(".filter-bar select").nth(1)).toHaveValue("upload");

  await page.getByRole("button", { name: "보관함" }).click();
  await expect(page).toHaveURL(/view=admin-archive/);
  await expect(page.getByRole("heading", { name: "보관함" })).toBeVisible();
});

test("React agent conversation follows the selected bot folder", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "mutates shared QA fixtures once");

  const jobsPath = "/home/portal/workspaces/admin/portal/agent_jobs.jsonl";
  const researchPath = "/home/portal/workspaces/team-alpha/user1/research/qa-session-research.md";
  const devPath = "/home/portal/workspaces/team-alpha/user1/dev/qa-session-dev.md";
  const backup = existsSync(jobsPath) ? readFileSync(jobsPath, "utf-8") : "";

  mkdirSync(dirname(researchPath), { recursive: true });
  mkdirSync(dirname(devPath), { recursive: true });
  writeFileSync(researchPath, "# 리서치 QA 산출물\n\n리서치봇 세션 미리보기 확인용 문서입니다.\n");
  writeFileSync(devPath, "# 개발 QA 산출물\n\n개발봇 세션 미리보기 확인용 문서입니다.\n");
  writeFileSync(jobsPath, [
    agentJob("research", "research/qa-session-research.md", "시장 자료를 조사해줘"),
    agentJob("dev", "dev/qa-session-dev.md", "개발 산출물을 만들어줘"),
  ].join("\n") + "\n");

  try {
    await login(page, "user1");
    await page.goto("/app?root=personal&path=research");
    await page.getByRole("tab", { name: /리서치봇과 대화/ }).click();
    await expect(page.getByText("researchbot", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("research QA 세션").first()).toBeVisible();
    await expect(page.getByText("qa-session-research.md").first()).toBeVisible();

    await page.locator(".nav-subitem", { hasText: "개발 산출물" }).click();
    await page.getByRole("tab", { name: /개발봇과 대화/ }).click();
    await expect(page.getByText("devbot", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("dev QA 세션").first()).toBeVisible();
    await expect(page.getByText("qa-session-dev.md").first()).toBeVisible();
    await expect(page.locator(".output-preview-frame")).toHaveAttribute("src", /dev%2Fqa-session-dev\.md/);

    await page.getByRole("button", { name: "대화 삭제" }).click();
    await expect(page.getByRole("dialog", { name: "대화를 삭제할까요?" })).toBeVisible();
    await page.getByRole("button", { name: "취소" }).click();
    await page.getByRole("button", { name: "+ 새 작업" }).click();
    await expect(page.getByText("개발봇에게 새 작업을 맡겨보세요")).toBeVisible();
  } finally {
    writeFileSync(jobsPath, backup);
    rmSync(researchPath, { force: true });
    rmSync(devPath, { force: true });
  }
});

test("React agent reference picker stays inside personal and team scopes", async ({ page }, testInfo) => {
  const personalName = `qa-reference-personal-${testInfo.project.name}.md`;
  const teamName = `qa-reference-team-${testInfo.project.name}.md`;
  const personalPath = `/home/portal/workspaces/team-alpha/user1/research/${personalName}`;
  const teamPath = `/home/portal/workspaces/team-alpha/shared/dev/${teamName}`;

  mkdirSync(dirname(personalPath), { recursive: true });
  mkdirSync(dirname(teamPath), { recursive: true });
  writeFileSync(personalPath, "# 개인 참고자료\n\n봇 요청 참고자료 선택 QA입니다.\n");
  writeFileSync(teamPath, "# 팀 참고자료\n\n팀 공유 참고자료 선택 QA입니다.\n");

  try {
    await login(page, "user1");
    await page.goto("/app?root=personal&path=dev");
    await page.getByRole("tab", { name: /개발봇과 대화/ }).click();
    await page.getByRole("button", { name: "참고자료 선택" }).click();
    const referenceDialog = page.getByRole("dialog", { name: "봇이 참고할 파일 선택" });
    await expect(referenceDialog).toBeVisible();
    await expect(referenceDialog.getByRole("button", { name: /내 리서치/ })).toBeVisible();
    await expect(referenceDialog.getByRole("button", { name: /팀 공유/ })).toBeVisible();

    await referenceDialog.getByPlaceholder("파일명 검색").fill(personalName);
    await expect(referenceDialog.getByRole("button", { name: new RegExp(personalName) })).toBeVisible();
    await referenceDialog.getByRole("button", { name: new RegExp(personalName) }).click();
    await expect(referenceDialog.locator(".reference-row.selected", { hasText: personalName })).toBeVisible();

    await referenceDialog.getByRole("button", { name: /팀 공유/ }).click();
    await referenceDialog.locator(".reference-row.folder", { hasText: "dev" }).click();
    await referenceDialog.getByPlaceholder("파일명 검색").fill(teamName);
    await expect(referenceDialog.getByRole("button", { name: new RegExp(teamName) })).toBeVisible();
    await referenceDialog.getByRole("button", { name: new RegExp(teamName) }).click();
    await expect(referenceDialog.locator(".reference-row.selected", { hasText: teamName })).toBeVisible();
    await expect(referenceDialog.locator(".reference-chip")).toHaveCount(2);
    await referenceDialog.getByRole("button", { name: "선택 완료" }).click();
    const composerChips = page.locator(".composer .reference-chip");
    await expect(composerChips).toHaveCount(2);
    await expect(page.locator(".composer .reference-chip-list")).toContainText(personalName);
    await expect(page.locator(".composer .reference-chip-list")).toContainText(teamName);
  } finally {
    rmSync(personalPath, { force: true });
    rmSync(teamPath, { force: true });
  }
});

test("React admin user report and archive restore modal stay compact", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "mutates shared QA fixtures once");

  const archiveFile = "/home/portal/workspaces/team-alpha/user1/.archive/deleted/20260526-qa/dev/admin-qa-restore.txt";
  mkdirSync(dirname(archiveFile), { recursive: true });
  writeFileSync(archiveFile, "admin archive modal qa");

  try {
    await login(page, "admin");
    await page.goto("/app?view=admin-user&root=all&username=user1");
    await expect(page.getByRole("heading", { name: "사용자 관리" })).toBeVisible();
    await expect(page.getByText("개인 폴더 열기")).toBeVisible();
    await expect(page.getByText("전체 작업 기록 보기")).toBeVisible();
    await expect(page.locator(".split-cols")).toBeVisible();

    await page.goto("/app?view=admin-archive&root=all");
    await expect(page.getByRole("heading", { name: "보관함" })).toBeVisible();
    await expect(page.getByText("admin-qa-restore.txt").first()).toBeVisible();
    await page.getByRole("button", { name: "복구" }).first().click();
    await expect(page.getByRole("dialog", { name: "보관 항목을 복구할까요?" })).toBeVisible();
    await page.getByRole("button", { name: "취소" }).click();
  } finally {
    rmSync(archiveFile, { force: true });
    rmSync("/home/portal/workspaces/team-alpha/user1/.archive/deleted/20260526-qa", { force: true, recursive: true });
  }
});

test("React workspace keeps the mobile layout contained", async ({ page }) => {
  await login(page);
  await page.goto("/app?root=all&path=team-alpha/user1/dev");

  await expect(page.getByRole("heading", { name: "전체 작업공간", exact: true })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(2);
});
