// pgrep concept walkthrough recorder.
//
// Drives the clickable prototype (design/prod/pgrep-prototype.html) with an
// injected on-screen cursor, synced lower-third captions, chapter cards, and
// Ken Burns image stages, and records one continuous video (webm) via Playwright.
//
// This produces a CONCEPT / PITCH video from the prototype. It is NOT the graded
// Wednesday submission. A persistent
// watermark and the outro card keep that honest.
//
// Run:  node design/prod/video/record.mjs
// Tune: PACE=1.15 node design/prod/video/record.mjs   (global speed multiplier)

import { chromium } from "playwright";
import path from "node:path";
import fs from "node:fs";
import { pathToFileURL } from "node:url";

const ROOT = "/Users/philote/projects/inka";
const PROTO = pathToFileURL(path.join(ROOT, "design/prod/pgrep-prototype.html")).href;
const EXAM = pathToFileURL(path.join(ROOT, "design/assets/ux/v2-exam-dark.png")).href;
const MOBILE = pathToFileURL(path.join(ROOT, "design/assets/ux/v2-mobile-dark.png")).href;
const OUTDIR = path.join(ROOT, "design/prod/video/raw");
const EXE =
  "/Users/philote/Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing";

const W = 1728;
const H = 1080;
const PACE = Number(process.env.PACE || 1);

fs.mkdirSync(OUTDIR, { recursive: true });

// ---- overlay layer injected into the prototype page ------------------------
// Everything here is pointer-events:none so real clicks reach the prototype.
function injectOverlay(assets) {
  const css = `
  #vo-layer, #vo-layer * { pointer-events: none; }
  #vo-cursor {
    position: fixed; left: 0; top: 0; width: 26px; height: 26px; z-index: 2147483000;
    transform: translate(-40%, -20%); transition: transform .04s linear; will-change: transform;
    filter: drop-shadow(0 2px 3px rgba(0,0,0,.45));
  }
  #vo-ripple {
    position: fixed; z-index: 2147482999; width: 14px; height: 14px; border-radius: 50%;
    border: 2px solid var(--primary-bg, #ECEAE3); opacity: 0; transform: translate(-50%,-50%) scale(1);
  }
  #vo-ripple.go { animation: voRipple .5s ease-out; }
  @keyframes voRipple { 0%{opacity:.8; transform:translate(-50%,-50%) scale(.5);} 100%{opacity:0; transform:translate(-50%,-50%) scale(3.4);} }
  #vo-cap {
    position: fixed; left: 50%; bottom: 46px; transform: translateX(-50%) translateY(10px);
    z-index: 2147483000; max-width: 60%; text-align: center; opacity: 0; transition: opacity .3s ease, transform .3s ease;
    background: color-mix(in srgb, var(--surface) 82%, transparent); border: 1px solid var(--border);
    border-radius: 14px; padding: 13px 22px; box-shadow: var(--shadow); backdrop-filter: blur(6px);
  }
  #vo-cap.on { opacity: 1; transform: translateX(-50%) translateY(0); }
  #vo-cap .t { font-size: 21px; font-weight: 600; letter-spacing: -.01em; color: var(--text); }
  #vo-cap .s { font-size: 14px; color: var(--muted); margin-top: 3px; }
  #vo-mark {
    position: fixed; left: 16px; bottom: 14px; z-index: 2147483000; font-size: 11.5px; letter-spacing: .02em;
    color: var(--muted); opacity: .72; font-family: var(--font-ui);
  }
  #vo-card, #vo-stage {
    position: fixed; inset: 0; z-index: 2147483001; display: flex; flex-direction: column;
    align-items: center; justify-content: center; text-align: center;
    background: var(--canvas); opacity: 0; transition: opacity .45s ease; gap: 14px;
  }
  #vo-card.on, #vo-stage.on { opacity: 1; }
  #vo-card .mark { width: 42px; height: 42px; opacity: .9; margin-bottom: 6px; }
  #vo-card .t { font-size: 46px; font-weight: 650; letter-spacing: -.025em; color: var(--text); max-width: 70%; }
  #vo-card .rule { width: 46px; height: 3px; border-radius: 2px; background: var(--memory); margin: 6px 0; }
  #vo-card .s { font-size: 20px; color: var(--muted); max-width: 56%; line-height: 1.5; }
  #vo-card .lines { margin-top: 10px; display: flex; flex-direction: column; gap: 9px; }
  #vo-card .lines div { font-size: 18px; color: var(--text); opacity: .92; }
  #vo-card .lines div b { color: var(--memory-t); font-weight: 700; margin-right: 8px; font-family: var(--font-mono); }
  #vo-stage img { max-width: 84%; max-height: 82%; border-radius: 18px; will-change: transform; }
  #vo-stage.zoom img { animation: voZoom 9s ease-out both; }
  #vo-stage.pan img { animation: voPan 10s ease-out both; }
  @keyframes voZoom { from{transform:scale(1.02);} to{transform:scale(1.13);} }
  @keyframes voPan { from{transform:scale(1.08) translateX(3%);} to{transform:scale(1.08) translateX(-3%);} }
  #vo-stage .cap2 { position: fixed; bottom: 54px; left: 50%; transform: translateX(-50%);
    font-size: 19px; color: var(--muted); }
  /* clean framing of the app on a stage */
  .banner { display: none !important; }
  .app { max-width: 1520px; margin: 0 auto; }
  main { margin-left: auto; margin-right: auto; }
  `;
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  const mark =
    '<svg viewBox="0 0 22 22" fill="none"><path d="M11 2c4 0 7 3 7 7 0 3-2 5-5 6-2 .7-3 2-5 2-3 0-5-2-5-5 0-4 4-4 5-7 1-2 1-3 3-3z" stroke="currentColor" stroke-width="1.3" opacity=".55"/><path d="M11 6c2.4 0 4 1.6 4 4 0 1.8-1.2 2.8-2.8 3.4-1.2.4-1.8 1-2.8 1-1.8 0-3-1.2-3-3 0-2.4 2.2-2.4 2.8-4C9.6 6.4 9.8 6 11 6z" stroke="currentColor" stroke-width="1.3"/></svg>';

  const layer = document.createElement("div");
  layer.id = "vo-layer";
  layer.innerHTML = `
    <div id="vo-ripple"></div>
    <svg id="vo-cursor" viewBox="0 0 24 24" fill="var(--text)" stroke="var(--canvas)" stroke-width="1.2">
      <path d="M4 2 L4 19 L9 14 L12.5 21.5 L15 20.3 L11.7 13 L18 13 Z"/>
    </svg>
    <div id="vo-cap"><div class="t"></div><div class="s"></div></div>
    <div id="vo-mark">concept prototype · not the graded build</div>
    <div id="vo-card"><div class="mark" style="color:var(--text)">${mark}</div><div class="t"></div><div class="rule"></div><div class="s"></div><div class="lines"></div></div>
    <div id="vo-stage"><img alt=""><div class="cap2"></div></div>
  `;
  document.body.appendChild(layer);

  const cur = document.getElementById("vo-cursor");
  const rip = document.getElementById("vo-ripple");
  const cap = document.getElementById("vo-cap");
  const card = document.getElementById("vo-card");
  const stage = document.getElementById("vo-stage");
  const stImg = stage.querySelector("img");
  const stCap = stage.querySelector(".cap2");

  let cx = W_ / 2,
    cy = H_ / 2;
  window.addEventListener(
    "mousemove",
    (e) => {
      cx = e.clientX;
      cy = e.clientY;
      cur.style.left = cx + "px";
      cur.style.top = cy + "px";
    },
    true
  );

  window.VO = {
    ripple() {
      rip.style.left = cx + "px";
      rip.style.top = cy + "px";
      rip.classList.remove("go");
      void rip.offsetWidth;
      rip.classList.add("go");
    },
    cap(t, s = "") {
      cap.querySelector(".t").textContent = t;
      cap.querySelector(".s").textContent = s;
      cap.classList.add("on");
    },
    capHide() {
      cap.classList.remove("on");
    },
    card(t, s = "", lines = []) {
      card.querySelector(".t").textContent = t;
      card.querySelector(".s").textContent = s;
      const lc = card.querySelector(".lines");
      lc.innerHTML = "";
      for (const ln of lines) {
        const d = document.createElement("div");
        if (Array.isArray(ln)) d.innerHTML = "<b>" + ln[0] + "</b>" + ln[1];
        else d.textContent = ln;
        lc.appendChild(d);
      }
      card.classList.add("on");
    },
    cardHide() {
      card.classList.remove("on");
    },
    stage(src, mode, caption = "") {
      stImg.src = src;
      stCap.textContent = caption;
      stage.classList.remove("zoom", "pan");
      void stage.offsetWidth;
      stage.classList.add("on", mode);
    },
    stageHide() {
      stage.classList.remove("on", "zoom", "pan");
    },
  };
}

// ---- driver ---------------------------------------------------------------
(async () => {
  const browser = await chromium.launch({ executablePath: EXE, headless: false });
  const context = await browser.newContext({
    viewport: { width: W, height: H },
    deviceScaleFactor: 2,
    recordVideo: { dir: OUTDIR, size: { width: W, height: H } },
  });
  const page = await context.newPage();
  page.on("dialog", (d) => d.accept().catch(() => {}));

  await page.goto(PROTO, { waitUntil: "load" });
  await page.evaluate(
    ({ fn, W_, H_ }) => {
      // eslint-disable-next-line no-eval
      window.W_ = W_;
      window.H_ = H_;
      eval("(" + fn + ")({})");
    },
    { fn: injectOverlay.toString(), W_: W, H_: H }
  );

  const sleep = (s) => page.waitForTimeout(s * 1000 * PACE);
  const cap = (t, s) => page.evaluate(([t, s]) => window.VO.cap(t, s), [t, s || ""]);
  const capHide = () => page.evaluate(() => window.VO.capHide());
  const card = (t, s, lines) =>
    page.evaluate(([t, s, lines]) => window.VO.card(t, s, lines), [t, s || "", lines || []]);
  const cardHide = () => page.evaluate(() => window.VO.cardHide());
  const stage = (src, mode, c) => page.evaluate(([src, mode, c]) => window.VO.stage(src, mode, c), [src, mode, c || ""]);
  const stageHide = () => page.evaluate(() => window.VO.stageHide());
  const nav = (js) => page.evaluate(js);

  async function moveTo(x, y) {
    await page.mouse.move(x, y, { steps: 26 });
    await sleep(0.12);
  }
  async function center(sel) {
    const b = await page.locator(sel).first().boundingBox();
    return b ? { x: b.x + b.width / 2, y: b.y + b.height / 2 } : null;
  }
  async function hover(sel) {
    const c = await center(sel);
    if (c) await moveTo(c.x, c.y);
  }
  async function click(sel) {
    const c = await center(sel);
    if (!c) return;
    await moveTo(c.x, c.y);
    await sleep(0.22);
    await page.evaluate(() => window.VO.ripple());
    await page.mouse.click(c.x, c.y);
    await sleep(0.32);
  }

  // ---- 1. INTRO -----------------------------------------------------------
  await sleep(0.6);
  await card(
    "pgrep",
    "Physics GRE prep on the Anki engine. One engine, two apps, three honest scores."
  );
  await sleep(4.6);
  await cardHide();
  await sleep(0.6);

  // ---- 2. HOME ------------------------------------------------------------
  await nav(() => go("home"));
  await sleep(0.6);
  await cap("Home", "Your readiness at a glance.");
  await moveTo(560, 360);
  await sleep(2.4);
  await hover(".score.m");
  await cap("Memory is shown honestly", "A point number, a likely range, and how sure it is.");
  await sleep(3.6);
  await hover(".score.p.abstain");
  await cap("Performance and Readiness abstain", "No evidence yet, so they refuse to guess.");
  await sleep(3.6);
  await hover(".score.r.abstain");
  await sleep(2.4);
  await hover(".today");
  await cap("One clear next step", "The best thing to study today.");
  await sleep(3.0);
  await capHide();
  await sleep(0.4);

  // ---- 3. STUDY -----------------------------------------------------------
  await card("Study", "Two doors. Cards for memory, problems for performance.");
  await sleep(2.0);
  await nav(() => go("study"));
  await sleep(0.4);
  await cardHide();
  await sleep(0.5);
  await cap("Start today's session", "Topics interleave inside each door.");
  await hover(".launch .card:nth-child(1)");
  await sleep(2.4);
  await hover(".launch .card:nth-child(2)");
  await sleep(2.2);
  await capHide();
  await sleep(0.3);

  // ---- 4. CARDS DOOR ------------------------------------------------------
  await card("The Cards door", "Retrieval, then grade. FSRS schedules the next review.");
  await sleep(2.0);
  await nav(() => startCards());
  await sleep(0.4);
  await cardHide();
  await sleep(0.5);
  await cap("A real review loop", "On a Physics GRE deck.");
  await sleep(2.0);
  await click("#showRow .btn.primary"); // show answer
  await cap("Recall, check, then grade", "");
  await sleep(2.0);
  await click("#gradeRow .grade:nth-child(3)"); // Good
  await sleep(1.2);
  await click("#showRow .btn.primary"); // next card, show answer
  await sleep(1.8);
  await click("#gradeRow .grade:nth-child(3)"); // Good
  await sleep(1.0);
  await click("#showRow .btn.primary");
  await sleep(1.6);
  await capHide();
  await sleep(0.3);

  // ---- 5. PRODUCTIVE FAILURE (Problems door) ------------------------------
  await card("Productive failure", "Struggle first. The ladder never hands you the answer.");
  await sleep(2.2);
  await nav(() => startProblem());
  await sleep(0.4);
  await cardHide();
  await sleep(0.5);
  await cap("Commit before any help", "No confidence rating, no predict-before-answer.");
  await click("#choices .choice:nth-child(4)"); // pick D (a wrong distractor)
  await sleep(1.6);
  await click("#commitBtn"); // commit -> wrong -> ladder opens
  await sleep(1.2);
  await cap("The wrong-answer ladder", "One rung at a time. A sub-goal, in your own words.");
  await hover("#rung textarea");
  await sleep(3.2);
  await click("#rung .btn"); // show the step
  await cap("It reveals the step", "Never the final answer.");
  await sleep(3.6);
  await capHide();
  await sleep(0.3);

  // ---- 6. PROGRESS --------------------------------------------------------
  await card("Honest evidence", "Coverage gates readiness. Calibration shows if the numbers can be trusted.");
  await sleep(2.2);
  await nav(() => go("progress"));
  await sleep(0.5);
  await cardHide();
  await sleep(0.5);
  await cap("Coverage is only 58 percent", "So readiness abstains for now.");
  await hover(".cov");
  await sleep(3.4);
  await cap("Model calibration", "A reliability diagram and a Brier score, not a vibe.");
  await hover(".calib:nth-child(1)");
  await sleep(3.6);
  await capHide();
  await sleep(0.3);

  // ---- 7. LIBRARY (forced generation, named sources) ----------------------
  await card("Author a seed", "Write one card. AI conforms the rest, each traced to a named source.");
  await sleep(2.2);
  await nav(() => go("library"));
  await sleep(0.5);
  await cardHide();
  await sleep(0.5);
  await cap("With AI off, the app still works", "You author seeds by hand, and every one counts.");
  await sleep(2.8);
  await click("#aiChip"); // turn AI on
  await cap("AI on", "Siblings in your style, cited to Griffiths and Sakurai, gold-set gated.");
  await hover(".sibling:nth-child(1)");
  await sleep(4.0);
  await page.evaluate(() => toggleAI()); // back to AI off (honest default)
  await capHide();
  await sleep(0.4);

  // ---- 8. EXAM MODE (static render) ---------------------------------------
  await card("Built for the exam", "Timed mocks, real PGRE proportions.");
  await sleep(2.0);
  await cardHide();
  await sleep(0.6);
  await stage(EXAM, "zoom", "Exam mode. A full timed mock, zero help.");
  await sleep(6.4);
  await stageHide();
  await sleep(0.7);

  // ---- 9. iPHONE APP (static render) --------------------------------------
  await card("Two apps, one engine", "The same Rust engine, in your pocket.");
  await sleep(2.0);
  await cardHide();
  await sleep(0.6);
  await stage(MOBILE, "pan", "The phone companion. Readiness at a glance, and a session that mirrors desktop.");
  await sleep(7.4);
  await stageHide();
  await sleep(0.7);

  // ---- 10. THEME beat + OUTRO ---------------------------------------------
  await nav(() => go("home"));
  await sleep(0.5);
  await cap("Light and dark are both first class", "");
  await click("#themeChip"); // to light
  await sleep(2.6);
  await click("#themeChip"); // back to dark
  await sleep(1.6);
  await capHide();
  await sleep(0.4);

  await card(
    "The Wednesday MVP",
    "What the real proofs show.",
    [
      ["01", "Forked Anki, building from source"],
      ["02", "A real Rust engine change, with tests"],
      ["03", "A desktop review loop and an honest Memory score"],
      ["04", "An installer on a clean machine"],
      ["05", "The same engine running on a phone"],
    ]
  );
  await sleep(7.5);
  await cardHide();
  await sleep(0.5);
  await card("pgrep", "An honest instrument for the Physics GRE.");
  await sleep(3.6);
  await cardHide();
  await sleep(0.8);

  const video = page.video();
  await context.close();
  await browser.close();
  const src = await video.path();
  const dest = path.join(OUTDIR, "walkthrough.webm");
  fs.copyFileSync(src, dest);
  console.log("RAW_VIDEO=" + dest);
})();
