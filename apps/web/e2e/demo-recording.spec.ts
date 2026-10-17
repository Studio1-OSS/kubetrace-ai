import { expect, test } from "@playwright/test";

// Records the flagship demo as a video: a LIVE run (real model on Nebius Token Factory) of the
// application-bug scenario. Run with: npx playwright test --config playwright.demo.config.ts
// The model shown is whatever the server's NEBIUS_MODEL is; the header badge displays it.
const hold = (page: any, ms: number) => page.waitForTimeout(ms);

// A short on-screen caption, so anything done off camera is stated rather than hidden.
async function caption(page: any, text: string, ms: number) {
  await page.evaluate((t: string) => {
    const el = document.createElement("div");
    el.id = "demo-caption";
    el.textContent = t;
    Object.assign(el.style, { position: "fixed", left: "50%", bottom: "28px", transform: "translateX(-50%)", zIndex: "9999",
      background: "rgba(10,14,22,0.92)", color: "#e6edf5", border: "1px solid #2a3442", borderRadius: "8px",
      padding: "10px 16px", font: "500 15px system-ui, sans-serif", maxWidth: "900px", textAlign: "center" });
    document.body.appendChild(el);
  }, text);
  await hold(page, ms);
  await page.evaluate(() => document.getElementById("demo-caption")?.remove());
}

test("demo: Beam fixes a checkout bug end to end", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("header-status")).toContainText("Token Factory");
  await expect(page.getByTestId("topology")).toBeVisible();
  await hold(page, 5000);

  await page.goto("/experiments");
  const card = page.getByTestId("experiment-application-bug");
  const live = page.locator("#live");
  if ((await live.getAttribute("data-state")) !== "checked") await live.click();
  await expect(page.getByText("Live model")).toBeVisible();
  await card.scrollIntoViewIfNeeded();
  await hold(page, 3000);

  // Setup (namespace, RBAC, baseline image) can run before recording to keep the video short.
  // The badge then already reads "Baseline healthy", and the caption says so.
  const badge = card.getByTestId("state-badge");
  if (/Baseline healthy/.test((await badge.textContent()) ?? "")) {
    await caption(page, "Setup ran before recording: demo namespace, scoped RBAC and the healthy baseline are in place.", 4500);
  } else {
    await page.getByTestId("setup-application-bug").click();
    await expect(badge).toHaveText(/Baseline healthy/, { timeout: 8 * 60_000 });
    await hold(page, 2000);
  }

  // The healthy cluster before the fault.
  await page.goto("/");
  await hold(page, 6000);
  await page.goto("/experiments");
  await page.getByTestId("inject-application-bug").click();
  await expect(page.getByTestId("experiment-application-bug").getByTestId("state-badge")).toHaveText(/Detected/, { timeout: 5 * 60_000 });
  await hold(page, 2500);

  await page.getByTestId("investigate-application-bug").click();
  await expect(page).toHaveURL(/\/runs\/[\w-]+$/);
  await expect(page.getByTestId("provenance")).toHaveText(/Live/);
  // Early in the investigation: the full topology view of the broken release, then back to the run.
  await hold(page, 6000);
  const expand = page.getByTestId("topology-expand");
  if (await expand.isVisible()) {
    await expand.click();
    await hold(page, 5000);
    await page.keyboard.press("Escape");
    await hold(page, 800);
  }
  const outcome = page.getByTestId("state-stepper");
  // Let the live run play out on screen; the timeline auto-scrolls.
  await expect(outcome).toContainText(/Resolved|Unresolved|Blocked|Escalated|Cancelled/, { timeout: 15 * 60_000 });
  await hold(page, 4000);

  for (const tab of ["Patch", "Tests", "Verification", "Evidence"]) {
    await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
    await hold(page, 5000);
  }

  await page.getByRole("link", { name: "Report" }).click();
  await expect(page.getByTestId("report")).toBeVisible();
  await page.locator("#pres").click();
  await hold(page, 3000);
  for (let y = 0; y < 5; y++) {
    await page.mouse.wheel(0, 700);
    await hold(page, 2500);
  }
});
