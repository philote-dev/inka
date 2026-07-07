<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

pgrep Study. A layered launcher (design/claude-design/Study Entry.dc.html):

  Layer 1  Launcher      Start today's session, Focus drill, Exam mode.
  Layer 2  Door choice   Cards or Problems live inside a session and inside a
                         focus drill (the locked two-door model: topics mix
                         within a door, never a card<->problem shuffle). The
                         focus drill first picks a topic (chips), then shows the
                         doors, or a calm "nothing due" state.
  Layer 3  In session    Cards run the real FSRS review loop (memory, amber) via
                         CardFace. Problems gate help behind Commit, then a static
                         wrong-answer ladder (performance, blue). Math is real
                         MathJax through renderMath.

Honesty rule: every count on screen is real (from the engine) or omitted; no
number is invented. Exam mode is the timed instrument at ts/routes/pgrep/study/exam.
The data flow through pgrepCall is unchanged.
-->
<script lang="ts">
    import { page } from "$app/state";
    import { onDestroy, onMount } from "svelte";

    import CardFace from "$lib/components/CardFace.svelte";
    import ChoiceList from "$lib/components/ChoiceList.svelte";
    import GradeBar from "$lib/components/GradeBar.svelte";
    import MemoryGlyph from "$lib/components/MemoryGlyph.svelte";
    import SessionSynthesis from "$lib/components/SessionSynthesis.svelte";
    import StudyFrame from "$lib/components/StudyFrame.svelte";
    import SubproblemCard from "$lib/components/SubproblemCard.svelte";
    import { renderMath } from "$lib/pgrep/math";
    import { resetSignal, setLearning } from "$lib/pgrep/nav";
    import type { SessionSynthesis as SessionSynthesisData } from "$lib/pgrep/synthesis";

    import { pgrepCall } from "../lib/bridge";

    interface StartResult {
        session_id: string;
        door: string;
        remaining: number;
    }

    interface CardItem {
        kind: "card";
        card_id: number;
        question_html: string;
        answer_html: string;
        topic: string | null;
        remaining: number;
    }

    interface ProblemItem {
        kind: "problem";
        note_id: number;
        stem_html: string;
        choices: string[];
        topic: string | null;
        remaining: number;
    }

    interface EmptyItem {
        kind: "empty";
    }

    type Item = CardItem | ProblemItem | EmptyItem;

    // The gated decomposition tutor a miss opens. Each subproblem is a mini MCQ
    // (its correct key, rationales, and model rationale withheld until answered)
    // plus, with AI on, an "explain why" step. The parent answer is never sent.
    interface Subproblem {
        index: number;
        variant_index: number;
        prompt: string;
        stem_html: string;
        choices: string[];
    }

    interface TutorState {
        note_id: number;
        variant_round: number;
        count: number;
        subproblems: Subproblem[];
    }

    interface CommitResult {
        correct: boolean;
        correct_choice?: string;
        tutor?: TutorState;
    }

    interface McqResult {
        correct: boolean;
        rationale_html?: string;
        correct_choice?: string;
        explain_why_html?: string;
        needs_explanation?: boolean;
        error?: string;
    }

    interface ExplainResult {
        ai: string;
        pass: boolean;
        feedback: string;
        explain_why_html?: string;
        error?: string;
    }

    const CATEGORY_LABELS: Record<string, string> = {
        mechanics: "Mechanics",
        electromagnetism: "Electromagnetism",
        quantum: "Quantum",
        thermodynamics: "Thermodynamics",
        atomic: "Atomic physics",
        optics_waves: "Optics and waves",
        special_relativity: "Special relativity",
        lab: "Lab methods",
        specialized: "Specialized",
    };
    const CATEGORY_SLUGS = Object.keys(CATEGORY_LABELS);
    const CHOICE_LETTERS = ["A", "B", "C", "D", "E"];
    const RATINGS = [
        { label: "No clue", value: 1 },
        { label: "Barely", value: 2 },
        { label: "Got it", value: 3 },
        { label: "Easily", value: 4 },
    ];

    type Door = "cards" | "problems";
    type Stage = "launcher" | "today" | "drill" | "session";

    let stage: Stage = "launcher";
    let mode: "today" | "drill" = "today";
    let drillTopic = ""; // "" means no topic picked yet (drill only)

    // Layer 2, the two doors. Each is a pre-started session so we can show an
    // honest remaining count and continue straight into it on click.
    interface DoorInfo {
        sessionId: string;
        remaining: number;
    }
    let cardsDoor: DoorInfo | null = null;
    let problemsDoor: DoorInfo | null = null;
    let doorsLoading = false;
    let doorsError = false;

    // Layer 3, the running session.
    let door: Door = "problems";
    let sessionId = "";
    let busy = false;
    let errored = false;
    let doorEmpty = false;
    let startedEmpty = false;

    // Cards door state.
    let card: CardItem | null = null;
    let answerShown = false;

    // Problems door state.
    let problem: ProblemItem | null = null;
    let selected = "";
    let committed: CommitResult | null = null;
    // M5 seam: when the current problem was shown, so commit can log response_ms
    // (the client-measured think time). Used only to filter rapid guesses.
    let problemShownAt = 0;

    // Decomposition tutor state (opened on a miss). The parent answer is never
    // revealed; the learner is gated through the subproblems one at a time.
    let tutor: TutorState | null = null;
    let tutorDone = false;
    let spIndex = 0; // current subproblem
    let spSelected = ""; // the subproblem's MCQ pick
    let spPhase: "mcq" | "explain" | "done" = "mcq";
    let spCorrectKey: string | null = null;
    let spMcqRationale = "";
    let spExplainWhy = "";
    let spExplanation = "";
    let spFeedback = "";
    let spOutcome: "pending" | "pass" | "fail" = "pending";
    let spBusy = false;

    // AI upgrade state (L4). AI is off by default; with it on, each subproblem
    // adds the graded "explain why" gate. Read once at mount.
    let aiOn = false;
    // Calibration gate: default calibrated=true so a read error or the pre-load
    // frame never flashes the lock; the real value lands on mount.
    let calibrated = true;
    let synthesis: SessionSynthesisData | null = null;
    let synthLoading = false;

    onMount(async () => {
        // Read AI and calibration independently. A failed calibration call must
        // never force aiOn off: that would leave the explain gate stranded after a
        // correct subproblem pick (phase becomes "explain" from the backend while
        // the card renders nothing because aiOn is false).
        try {
            const status = await pgrepCall<{ enabled: boolean }>("pgrepAiStatus", {});
            aiOn = status.enabled;
        } catch {
            aiOn = false;
        }
        try {
            const cal = await pgrepCall<{ calibrated: boolean }>(
                "pgrepCalibrationStatus",
                {},
            );
            calibrated = cal.calibrated;
        } catch {
            calibrated = true;
        }
        // Study is gated behind calibration while AI is on (card-sets plan §4):
        // stop before any door or deep-link work; the lock renders instead.
        if (aiOn && !calibrated) {
            return;
        }
        // A door preselected from the demo launcher arrives as ?door=cards|problems.
        // Jump straight into that door of today's session (used by the dev lab's
        // Flashcards and Practice tabs); falls back to the launcher on error.
        const doorParam = page.url.searchParams.get("door") ?? "";
        if (doorParam === "cards" || doorParam === "problems") {
            mode = "today";
            stage = "today";
            await loadDoors(null);
            enterDoor(doorParam);
            return;
        }
        // A topic preselected from the manifold focus-drill entry arrives as
        // ?topic=<slug>. Land straight in that topic's focus drill so the learner
        // can pick the Cards or Problems door for it.
        const preset = page.url.searchParams.get("topic") ?? "";
        if (CATEGORY_SLUGS.includes(preset)) {
            mode = "drill";
            drillTopic = preset;
            stage = "drill";
            void loadDoors(topicArg());
        } else {
            // Preload today's counts so the launcher can show them honestly.
            void loadDoors(null);
        }
    });

    onDestroy(() => {
        // Leaving the surface entirely (client nav) restores the rail.
        setLearning(false);
    });

    function topicArg(): string | null {
        return drillTopic ? `topic::${drillTopic}` : null;
    }

    function resetItemState(): void {
        card = null;
        answerShown = false;
        problem = null;
        selected = "";
        committed = null;
        doorEmpty = false;
        resetTutorState();
    }

    function resetTutorState(): void {
        tutor = null;
        tutorDone = false;
        resetSubproblemState();
    }

    function resetSubproblemState(): void {
        spSelected = "";
        spPhase = "mcq";
        spCorrectKey = null;
        spMcqRationale = "";
        spExplainWhy = "";
        spExplanation = "";
        spFeedback = "";
        spOutcome = "pending";
        spBusy = false;
    }

    // Start both doors for the current scope (all topics, or one drill topic) so
    // we can show real due counts before the learner commits to a door.
    async function loadDoors(topic: string | null): Promise<void> {
        doorsLoading = true;
        doorsError = false;
        cardsDoor = null;
        problemsDoor = null;
        try {
            const [cards, problems] = await Promise.all([
                pgrepCall<StartResult>("pgrepStudyStart", { door: "cards", topic }),
                pgrepCall<StartResult>("pgrepStudyStart", { door: "problems", topic }),
            ]);
            cardsDoor = { sessionId: cards.session_id, remaining: cards.remaining };
            problemsDoor = {
                sessionId: problems.session_id,
                remaining: problems.remaining,
            };
        } catch {
            doorsError = true;
        } finally {
            doorsLoading = false;
        }
    }

    function openToday(): void {
        mode = "today";
        drillTopic = "";
        stage = "today";
        void loadDoors(null);
    }

    function openDrill(): void {
        mode = "drill";
        drillTopic = "";
        cardsDoor = null;
        problemsDoor = null;
        doorsError = false;
        stage = "drill";
    }

    function selectTopic(slug: string): void {
        drillTopic = slug;
        void loadDoors(topicArg());
    }

    function enterDoor(which: Door): void {
        const info = which === "cards" ? cardsDoor : problemsDoor;
        if (!info) {
            return;
        }
        door = which;
        sessionId = info.sessionId;
        startedEmpty = info.remaining === 0;
        stage = "session";
        void loadNext();
    }

    async function loadNext(): Promise<void> {
        busy = true;
        errored = false;
        resetItemState();
        try {
            const item = await pgrepCall<Item>("pgrepStudyNext", {
                session_id: sessionId,
            });
            if (item.kind === "card") {
                card = item;
            } else if (item.kind === "problem") {
                problem = item;
                problemShownAt =
                    typeof performance !== "undefined" ? performance.now() : Date.now();
            } else {
                doorEmpty = true;
                if (door === "problems" && !startedEmpty) {
                    synthLoading = true;
                    await fetchSynthesis();
                    synthLoading = false;
                }
            }
        } catch {
            errored = true;
        } finally {
            busy = false;
        }
    }

    async function grade(rating: number): Promise<void> {
        if (!card || busy) {
            return;
        }
        busy = true;
        errored = false;
        try {
            await pgrepCall("pgrepStudyAnswerCard", {
                card_id: card.card_id,
                rating,
            });
            await loadNext();
        } catch {
            errored = true;
            busy = false;
        }
    }

    async function commit(): Promise<void> {
        if (!problem || !selected || busy) {
            return;
        }
        busy = true;
        errored = false;
        const nowMs =
            typeof performance !== "undefined" ? performance.now() : Date.now();
        const responseMs = problemShownAt ? Math.round(nowMs - problemShownAt) : null;
        try {
            committed = await pgrepCall<CommitResult>("pgrepStudyCommit", {
                note_id: problem.note_id,
                session_id: sessionId,
                selected,
                // M5 seam: think time from the item being shown to this commit.
                response_ms: responseMs,
            });
            // A miss opens the decomposition tutor (the parent answer stays
            // hidden). A hit, or a miss with no decomposition available, just
            // moves on.
            resetTutorState();
            tutor = committed.tutor ?? null;
            if (!committed.correct && tutor && tutor.count > 0) {
                startSubproblem(0);
            } else {
                tutorDone = true;
            }
        } catch {
            errored = true;
        } finally {
            busy = false;
        }
    }

    function startSubproblem(i: number): void {
        spIndex = i;
        resetSubproblemState();
    }

    // Gate 1: the subproblem MCQ. A wrong pick returns only that distractor's
    // rationale (unlimited retries); a correct pick reveals the model rationale
    // and, with AI on, opens the "explain why" gate.
    async function checkSubMcq(): Promise<void> {
        if (!tutor || !spSelected || spBusy) {
            return;
        }
        const sub = tutor.subproblems[spIndex];
        spBusy = true;
        try {
            const r = await pgrepCall<McqResult>("pgrepTutorMcq", {
                note_id: tutor.note_id,
                subgoal_index: sub.index,
                variant_index: sub.variant_index,
                selected: spSelected,
            });
            if (r.correct) {
                spCorrectKey = r.correct_choice ?? spSelected;
                spExplainWhy = r.explain_why_html ?? "";
                spMcqRationale = "";
                // Only open the explain gate when the card can actually show it
                // (aiOn), so a backend/frontend AI mismatch never strands the step.
                spPhase = r.needs_explanation && aiOn ? "explain" : "done";
            } else {
                spMcqRationale =
                    r.rationale_html || "Not quite. Look again and try another.";
            }
        } catch {
            spMcqRationale = "Something went wrong. Try again.";
        } finally {
            spBusy = false;
        }
    }

    // Gate 2 (AI on only): the lenient "explain why". A pass reveals the model
    // rationale and unlocks the next step; a fail shows feedback and lets the
    // learner revise and re-check.
    async function gradeSubExplain(): Promise<void> {
        if (!tutor || !spExplanation.trim() || spBusy) {
            return;
        }
        const sub = tutor.subproblems[spIndex];
        spBusy = true;
        try {
            const r = await pgrepCall<ExplainResult>("pgrepTutorExplain", {
                note_id: tutor.note_id,
                subgoal_index: sub.index,
                variant_index: sub.variant_index,
                learner_text: spExplanation,
            });
            spFeedback = r.feedback ?? "";
            if (r.pass) {
                spOutcome = "pass";
                spExplainWhy = r.explain_why_html ?? spExplainWhy;
                spPhase = "done";
            } else {
                spOutcome = "fail";
            }
        } catch {
            spFeedback = "Grading is unavailable right now. Try again.";
            spOutcome = "fail";
        } finally {
            spBusy = false;
        }
    }

    // Advance only when the step is satisfied. No skip anywhere.
    function continueSubproblem(): void {
        if (!tutor) {
            return;
        }
        if (spIndex + 1 < tutor.subproblems.length) {
            startSubproblem(spIndex + 1);
        } else {
            tutorDone = true;
        }
    }

    async function fetchSynthesis(): Promise<void> {
        try {
            synthesis = await pgrepCall<SessionSynthesisData>("pgrepTutorSynthesis", {
                session_id: sessionId,
            });
        } catch {
            synthesis = null;
        }
    }

    // Seed sample content, then reload the doors for the current scope so the
    // just-seeded items are ready to study.
    // Restart the sample set so the door has cards again: reseed if needed, lift
    // the daily caps, and forget the seeded cards back to new (pgrepRestartCards).
    // Reliable even after the set has been studied through, which plain seeding
    // (idempotent) could not fix.
    async function seedContent(): Promise<void> {
        busy = true;
        errored = false;
        try {
            await pgrepCall("pgrepRestartCards", {});
            await loadDoors(topicArg());
            const info = door === "cards" ? cardsDoor : problemsDoor;
            if (info) {
                sessionId = info.sessionId;
                startedEmpty = info.remaining === 0;
            }
            await loadNext();
        } catch {
            errored = true;
        } finally {
            busy = false;
        }
    }

    async function seedFromLayer(): Promise<void> {
        try {
            await pgrepCall("pgrepRestartCards", {});
        } catch {
            doorsError = true;
            return;
        }
        await loadDoors(topicArg());
    }

    // Close from a running session drops back to the layer it launched from, so
    // the learner can pick the other door without starting over.
    function endSession(): void {
        resetItemState();
        if (mode === "drill") {
            stage = "drill";
            void loadDoors(topicArg());
        } else {
            stage = "today";
            void loadDoors(null);
        }
    }

    function backToLauncher(): void {
        stage = "launcher";
        mode = "today";
        drillTopic = "";
        resetItemState();
        void loadDoors(null);
    }

    function letterOf(index: number): string {
        return CHOICE_LETTERS[index] ?? String(index + 1);
    }

    function prettyTopic(raw: string): string {
        const slug = (raw || "").replace(/^topic::/, "").split("::")[0];
        return (
            CATEGORY_LABELS[slug] ??
            slug.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
        );
    }

    function doorCountLabel(key: Door, remaining: number): string {
        if (key === "cards") {
            return remaining > 0 ? `${remaining} due` : "Nothing due";
        }
        return remaining > 0
            ? `${remaining} ${remaining === 1 ? "problem" : "problems"}`
            : "None right now";
    }

    // View helpers (presentation only, no data changes).
    let topicTone: "memory" | "performance" = "performance";
    $: topicTone = door === "cards" ? "memory" : "performance";

    // Study is locked behind calibration while AI is on (card-sets plan §4).
    // Home and Progress stay open; only this surface gates.
    $: locked = aiOn && !calibrated;

    // A running session is a focus surface, so the rail collapses while one runs
    // and restores on the launcher and pickers (ts/lib/pgrep/nav.ts).
    $: setLearning(stage === "session");
    // Re-clicking the active Study tab bumps the rail's reset signal; return this
    // surface to its launcher (skip the initial value seen at mount).
    let resetSeen = $resetSignal;
    $: if ($resetSignal !== resetSeen) {
        resetSeen = $resetSignal;
        backToLauncher();
    }
    $: currentTopic = (card?.topic ?? problem?.topic ?? "").trim();
    $: remainingCount = card?.remaining ?? problem?.remaining ?? null;
    $: countLabel = remainingCount === null ? "" : `${remainingCount} left`;
    $: choiceItems = problem
        ? problem.choices.map((html, i) => ({ key: letterOf(i), html }))
        : [];
    $: subChoiceItems =
        tutor && tutor.subproblems[spIndex]
            ? tutor.subproblems[spIndex].choices.map((html, i) => ({
                  key: letterOf(i),
                  html,
              }))
            : [];
    // Typeset delimited LaTeX in the stem (no-op on plain text).
    $: renderedStem = problem ? renderMath(problem.stem_html) : "";
    $: doorList = [
        {
            key: "cards" as Door,
            name: "Cards",
            kind: "Memory",
            desc: "Retrieval that primes the problems. Real reviews.",
            info: cardsDoor,
        },
        {
            key: "problems" as Door,
            name: "Problems",
            kind: "Performance",
            desc: "Commit first. A miss builds it back up, step by step.",
            info: problemsDoor,
        },
    ];
    $: doorsReady =
        !doorsLoading && !doorsError && cardsDoor !== null && problemsDoor !== null;
    $: bothEmpty =
        doorsReady && cardsDoor?.remaining === 0 && problemsDoor?.remaining === 0;
</script>

{#if locked}
    <section class="wrap">
        <header class="head">
            <h1>Study</h1>
            <p class="sub">One step first.</p>
        </header>
        <section class="notice">
            <p class="lead">Calibrate first</p>
            <p class="muted">
                Writing a card in your own words for each topic is how this sticks. Make
                one per topic in the Library, then Study opens.
            </p>
            <a class="btn primary" href="/pgrep/library">Go to the Library</a>
        </section>
    </section>
{:else if stage === "launcher"}
    <section class="wrap">
        <header class="head">
            <h1>Study</h1>
            <p class="sub">Pick how you want to train today.</p>
        </header>

        <section class="option today">
            <div class="option-body">
                <div class="eyebrow">Recommended</div>
                <div class="option-title">Start today's session</div>
                <p class="option-desc">Cards and problems, interleaved.</p>
                {#if cardsDoor || problemsDoor}
                    <div class="meta">
                        {#if cardsDoor}
                            <span class="metric">
                                <span class="dot memory"></span>
                                {cardsDoor.remaining} cards
                            </span>
                        {/if}
                        {#if problemsDoor}
                            <span class="metric">
                                <span class="dot performance"></span>
                                {problemsDoor.remaining} problems
                            </span>
                        {/if}
                    </div>
                {/if}
            </div>
            <button class="btn primary" on:click={openToday}>Start session</button>
        </section>

        <button class="option row" on:click={openDrill}>
            <div class="option-body">
                <div class="option-title">Focus drill</div>
                <p class="option-desc">One topic at a time.</p>
            </div>
            <svg
                class="chev"
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linecap="round"
                stroke-linejoin="round"
            >
                <polyline points="6,3.5 11,8 6,12.5" />
            </svg>
        </button>

        <a class="option row" href="/pgrep/study/exam">
            <div class="option-body">
                <div class="option-title">Exam mode</div>
                <p class="option-desc">A timed mock, zero help.</p>
            </div>
            <svg
                class="chev"
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linecap="round"
                stroke-linejoin="round"
            >
                <polyline points="6,3.5 11,8 6,12.5" />
            </svg>
        </a>
    </section>
{:else if stage === "today"}
    <section class="wrap">
        <header class="head">
            <button class="back" on:click={backToLauncher}>
                <svg
                    width="15"
                    height="15"
                    viewBox="0 0 16 16"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                >
                    <polyline points="10,3.5 5,8 10,12.5" />
                </svg>
                Study
            </button>
            <h1>Today's session</h1>
            <p class="sub">Two doors. Topics mix inside each one.</p>
        </header>

        {#if doorsLoading}
            <p class="muted center">Reading what's due.</p>
        {:else if doorsError}
            <div class="notice">
                <p class="lead">Could not read your session.</p>
                <button class="btn" on:click={() => void loadDoors(null)}>
                    Try again
                </button>
            </div>
        {:else if bothEmpty}
            <div class="notice">
                <p class="lead">Nothing due right now.</p>
                <p class="muted">Restart the set to study the sample content again.</p>
                <button class="btn primary" on:click={seedFromLayer}>
                    Restart the set
                </button>
            </div>
        {:else}
            <div class="doors">
                {#each doorList as d (d.key)}
                    <button
                        class="door {d.key}"
                        on:click={() => enterDoor(d.key)}
                        disabled={!d.info || d.info.remaining === 0}
                    >
                        <span class="door-head">
                            <span class="glyph">
                                {#if d.key === "cards"}
                                    <svg
                                        width="20"
                                        height="20"
                                        viewBox="0 0 20 20"
                                        fill="none"
                                        stroke="currentColor"
                                        stroke-width="1.5"
                                        stroke-linecap="round"
                                        stroke-linejoin="round"
                                    >
                                        <MemoryGlyph />
                                    </svg>
                                {:else}
                                    <svg
                                        width="20"
                                        height="20"
                                        viewBox="0 0 20 20"
                                        fill="none"
                                        stroke="currentColor"
                                        stroke-width="1.5"
                                    >
                                        <circle cx="10" cy="10" r="7" />
                                        <circle cx="10" cy="10" r="3.5" />
                                        <circle
                                            cx="10"
                                            cy="10"
                                            r="0.8"
                                            fill="currentColor"
                                            stroke="none"
                                        />
                                    </svg>
                                {/if}
                            </span>
                            <span class="door-kind">{d.kind}</span>
                        </span>
                        <span class="door-name">{d.name}</span>
                        <span class="door-desc">{d.desc}</span>
                        <span class="door-count">
                            {d.info ? doorCountLabel(d.key, d.info.remaining) : ""}
                        </span>
                    </button>
                {/each}
            </div>
        {/if}
    </section>
{:else if stage === "drill"}
    <section class="wrap drill">
        <header class="head center">
            <button class="back" on:click={backToLauncher}>
                <svg
                    width="15"
                    height="15"
                    viewBox="0 0 16 16"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                >
                    <polyline points="10,3.5 5,8 10,12.5" />
                </svg>
                Study
            </button>
            <h1>Focus drill</h1>
            <p class="sub">
                One topic, measured the same way. You can also tap a region on your map.
            </p>
        </header>

        <div class="chips">
            {#each CATEGORY_SLUGS as slug (slug)}
                <button
                    class="chip"
                    class:selected={slug === drillTopic}
                    on:click={() => selectTopic(slug)}
                >
                    {CATEGORY_LABELS[slug]}
                </button>
            {/each}
        </div>

        {#if drillTopic}
            {#if doorsLoading}
                <p class="muted center">Reading what's due.</p>
            {:else if doorsError}
                <div class="notice">
                    <p class="lead">Could not read this topic.</p>
                    <button class="btn" on:click={() => void loadDoors(topicArg())}>
                        Try again
                    </button>
                </div>
            {:else if bothEmpty}
                <section class="empty-card">
                    <div class="empty-title">
                        Nothing due in {CATEGORY_LABELS[drillTopic]}
                    </div>
                    <p class="muted">
                        You are ahead of schedule here. Reviews return as memory fades,
                        so resting is fine too.
                    </p>
                    <div class="empty-actions">
                        <button class="btn" on:click={openToday}>
                            Practice a mixed set
                        </button>
                        <a class="btn" href="/pgrep/library">
                            Add or generate problems
                        </a>
                    </div>
                </section>
            {:else}
                <div class="doors">
                    {#each doorList as d (d.key)}
                        <button
                            class="door {d.key}"
                            on:click={() => enterDoor(d.key)}
                            disabled={!d.info || d.info.remaining === 0}
                        >
                            <span class="door-head">
                                <span class="glyph">
                                    {#if d.key === "cards"}
                                        <svg
                                            width="20"
                                            height="20"
                                            viewBox="0 0 20 20"
                                            fill="none"
                                            stroke="currentColor"
                                            stroke-width="1.5"
                                            stroke-linecap="round"
                                            stroke-linejoin="round"
                                        >
                                            <MemoryGlyph />
                                        </svg>
                                    {:else}
                                        <svg
                                            width="20"
                                            height="20"
                                            viewBox="0 0 20 20"
                                            fill="none"
                                            stroke="currentColor"
                                            stroke-width="1.5"
                                        >
                                            <circle cx="10" cy="10" r="7" />
                                            <circle cx="10" cy="10" r="3.5" />
                                            <circle
                                                cx="10"
                                                cy="10"
                                                r="0.8"
                                                fill="currentColor"
                                                stroke="none"
                                            />
                                        </svg>
                                    {/if}
                                </span>
                                <span class="door-kind">{d.kind}</span>
                            </span>
                            <span class="door-name">{d.name}</span>
                            <span class="door-desc">{d.desc}</span>
                            <span class="door-count">
                                {d.info ? doorCountLabel(d.key, d.info.remaining) : ""}
                            </span>
                        </button>
                    {/each}
                </div>
            {/if}
        {/if}
    </section>
{:else if door === "problems" && doorEmpty && !startedEmpty && (synthLoading || (synthesis && synthesis.score.total > 0))}
    {#if synthesis && synthesis.score.total > 0}
        <SessionSynthesis {synthesis} onDone={endSession} onClose={endSession} />
    {:else}
        <div class="synth-loading">Consolidating your session.</div>
    {/if}
{:else}
    <StudyFrame
        count={countLabel}
        topic={prettyTopic(currentTopic)}
        {topicTone}
        center={door === "cards"}
        onClose={endSession}
    >
        {#if busy}
            <p class="muted center">Working.</p>
        {:else if errored}
            <div class="notice">
                <p class="lead">Something went wrong.</p>
                <button class="btn" on:click={loadNext}>Try again</button>
            </div>
        {:else if doorEmpty}
            <div class="notice">
                {#if startedEmpty}
                    <p class="lead">Nothing due right now.</p>
                    <p class="muted">Restart the set to study these again.</p>
                    <button class="btn primary" on:click={seedContent} disabled={busy}>
                        {busy ? "Restarting" : "Restart the set"}
                    </button>
                {:else}
                    <p class="lead">This door is clear for now.</p>
                    <p class="muted">
                        Come back when more is due, or try the other door.
                    </p>
                    <button class="btn" on:click={endSession}>Back</button>
                {/if}
            </div>
        {:else if door === "cards" && card}
            <CardFace
                questionHtml={card.question_html}
                answerHtml={card.answer_html}
                {answerShown}
            />
            {#if answerShown}
                <div class="grade-label">How well did you remember it?</div>
                <GradeBar grades={RATINGS} disabled={busy} onGrade={grade} />
            {:else}
                <div class="actions center">
                    <button class="btn primary" on:click={() => (answerShown = true)}>
                        Show answer
                    </button>
                </div>
            {/if}
        {:else if door === "problems" && problem}
            <div class="stem">{@html renderedStem}</div>

            <ChoiceList
                choices={choiceItems}
                {selected}
                committed={committed !== null}
                correctKey={committed?.correct_choice ?? null}
                onSelect={(key) => (selected = key)}
            />

            {#if !committed}
                <div class="actions">
                    <button
                        class="btn primary"
                        on:click={commit}
                        disabled={!selected || busy}
                    >
                        Commit
                    </button>
                    <span class="muted small">Help stays locked until you commit.</span>
                </div>
            {:else if committed.correct}
                <div class="verdict hit">Correct.</div>
                <div class="actions next">
                    <button class="btn primary" on:click={loadNext} disabled={busy}>
                        Next
                    </button>
                    <span class="muted small">
                        {problem.remaining} left in this door.
                    </span>
                </div>
            {:else if tutor && tutor.count > 0 && !tutorDone}
                <div class="verdict miss">Not correct. Let's build it up.</div>
                {#key spIndex}
                    <SubproblemCard
                        index={spIndex + 1}
                        total={tutor.count}
                        stemHtml={tutor.subproblems[spIndex].stem_html}
                        choices={subChoiceItems}
                        selected={spSelected}
                        phase={spPhase}
                        correctKey={spCorrectKey}
                        mcqRationaleHtml={spMcqRationale}
                        explainWhyHtml={spExplainWhy}
                        {aiOn}
                        bind:explanation={spExplanation}
                        feedback={spFeedback}
                        explanationOutcome={spOutcome}
                        busy={spBusy}
                        isLast={spIndex + 1 === tutor.count}
                        onSelect={(key) => {
                            spSelected = key;
                            spMcqRationale = "";
                        }}
                        onCheck={checkSubMcq}
                        onGrade={gradeSubExplain}
                        onContinue={continueSubproblem}
                    />
                {/key}
            {:else}
                <div class="verdict miss">Not correct.</div>
                {#if tutorDone && tutor && tutor.count > 0}
                    <p class="tutor-lead muted small">
                        Nicely worked through. You'll see this one again later with
                        different numbers.
                    </p>
                {:else}
                    <p class="tutor-lead muted small">
                        Take another look at the idea. The answer stays hidden, and
                        you'll get another go.
                    </p>
                {/if}
                <div class="actions next">
                    <button class="btn primary" on:click={loadNext} disabled={busy}>
                        Next
                    </button>
                    <span class="muted small">
                        {problem.remaining} left in this door.
                    </span>
                </div>
            {/if}
        {/if}
    </StudyFrame>
{/if}

<style lang="scss">
    .wrap {
        max-width: 680px;
        margin: 0 auto;
        padding: 64px 24px;
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        font-family: var(--font-ui);
        color: var(--text);
    }

    .head {
        margin-bottom: var(--space-1);

        h1 {
            margin: 0;
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        .sub {
            margin: 8px 0 0;
            color: var(--muted);
            font-size: var(--text-body);
        }

        &.center {
            text-align: center;
        }
    }

    .back {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        margin-bottom: var(--space-2);
        padding: 0;
        background: none;
        border: none;
        color: var(--muted);
        font-family: var(--font-ui);
        font-size: var(--text-body);
        font-weight: 500;
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
        }
    }

    .head.center .back {
        align-self: center;
    }

    /* Layer 1, the three training options. */
    .option {
        display: flex;
        align-items: center;
        gap: var(--space-3);
        width: 100%;
        text-align: left;
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        padding: 24px 28px;
        box-shadow: var(--shadow-card);
        color: var(--text);
        font-family: var(--font-ui);
        text-decoration: none;
    }

    button.option,
    a.option {
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover:not(:disabled) {
            border-color: var(--muted);
        }
    }

    .option-body {
        flex: 1 1 auto;
        min-width: 0;
    }

    .eyebrow {
        font-size: var(--text-caption);
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
        margin-bottom: 6px;
    }

    .option-title {
        font-size: var(--text-emphasis);
        font-weight: 600;
        letter-spacing: -0.01em;
    }

    .option-desc {
        margin: 6px 0 0;
        font-size: 13px;
        color: var(--muted);
        line-height: 1.5;
    }

    .meta {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        margin-top: 12px;
        flex-wrap: wrap;
    }

    .metric {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        font-family: var(--font-mono);
        font-size: var(--text-small);
        color: var(--muted);
        white-space: nowrap;
    }

    .dot {
        width: 6px;
        height: 6px;
        border-radius: var(--radius-pill);

        &.memory {
            background: var(--memory);
        }

        &.performance {
            background: var(--performance);
        }
    }

    .chev {
        flex: 0 0 auto;
        color: var(--muted);
    }

    /* Layer 2, the two doors. */
    .doors {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--space-2);
    }

    .door {
        display: flex;
        flex-direction: column;
        gap: 8px;
        text-align: left;
        padding: 20px;
        min-height: 168px;
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);
        cursor: pointer;
        transition: var(--transition-calm);
        color: var(--text);
        font-family: var(--font-ui);

        &:hover:not(:disabled) {
            border-color: var(--muted);
        }

        &:disabled {
            cursor: default;
            opacity: 0.55;
        }
    }

    .door-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 2px;
    }

    .glyph {
        display: inline-flex;
    }

    .cards .glyph {
        color: var(--memory-text);
    }

    .problems .glyph {
        color: var(--performance-text);
    }

    .door-kind {
        font-size: var(--text-caption);
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--muted);
    }

    .door-name {
        font-size: var(--text-emphasis);
        font-weight: 600;
        letter-spacing: -0.01em;
    }

    .door-desc {
        color: var(--muted);
        font-size: 13px;
        line-height: 1.5;
    }

    .door-count {
        margin-top: auto;
        padding-top: var(--space-1);
        font-family: var(--font-mono);
        font-size: var(--text-small);
        color: var(--muted);
    }

    /* Focus drill picker. */
    .chips {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-1);
        justify-content: center;
        margin-bottom: var(--space-2);
    }

    .chip {
        font-size: var(--text-small);
        font-weight: 500;
        color: var(--muted);
        background: none;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        padding: 6px 14px;
        cursor: pointer;
        font-family: var(--font-ui);
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
            border-color: var(--muted);
        }

        &.selected {
            color: var(--text);
            background: var(--elevated);
            border-color: var(--text);
        }
    }

    .empty-card {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-frame);
        padding: 36px;
        box-shadow: var(--shadow-card);
        text-align: center;
    }

    .empty-title {
        font-size: 20px;
        font-weight: 600;
        letter-spacing: -0.01em;
    }

    .empty-card .muted {
        margin: 10px 0 0;
        font-size: var(--text-body);
        line-height: 1.6;
    }

    .empty-actions {
        display: flex;
        justify-content: center;
        gap: 12px;
        margin-top: var(--space-3);
        flex-wrap: wrap;
    }

    /* Layer 3, the running session. */
    .stem {
        font-size: var(--text-content);
        line-height: 1.6;
        margin-bottom: var(--space-2);

        :global(p) {
            margin: 0 0 0.6em;
        }
    }

    .grade-label {
        margin: var(--space-3) 0 var(--space-1);
        font-size: var(--text-small);
        color: var(--muted);
        text-align: center;
    }

    .verdict {
        margin-top: var(--space-3);
        font-size: var(--text-emphasis);
        font-weight: 600;

        &.hit {
            color: var(--success);
        }

        &.miss {
            color: var(--performance-text);
        }
    }

    .tutor-lead {
        margin: var(--space-1) 0 var(--space-2);
    }

    .synth-loading {
        display: flex;
        flex: 1 1 auto;
        min-height: 60vh;
        align-items: center;
        justify-content: center;
        color: var(--muted);
        font-size: var(--text-body);
    }

    .actions {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        flex-wrap: wrap;
        margin-top: var(--space-2);

        &.center {
            justify-content: center;
        }

        &.next {
            margin-top: var(--space-3);
            padding-top: var(--space-2);
            border-top: var(--hairline);
        }
    }

    .notice {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: var(--space-1);
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        padding: var(--space-3);
        box-shadow: var(--shadow-card);
    }

    .lead {
        margin: 0;
        font-size: var(--text-emphasis);
        font-weight: 600;
    }

    .center {
        text-align: center;
    }

    .muted {
        color: var(--muted);
    }

    .small {
        font-size: var(--text-small);
    }

    .btn {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 11px 18px;
        font-family: var(--font-ui);
        font-size: var(--text-body);
        font-weight: 500;
        border-radius: var(--radius-control);
        border: var(--hairline);
        background: var(--surface);
        color: var(--text);
        cursor: pointer;
        text-decoration: none;
        transition: var(--transition-calm);

        &:hover:not(:disabled) {
            background: var(--hover-wash);
            border-color: var(--muted);
        }

        &:disabled {
            cursor: default;
            opacity: 0.55;
        }

        &.primary {
            background: var(--action-bg);
            color: var(--action-fg);
            border-color: transparent;

            &:hover:not(:disabled) {
                background: var(--action-bg-hover);
            }
        }

        &.ghost {
            background: none;
            border-color: var(--muted);
        }
    }
</style>
