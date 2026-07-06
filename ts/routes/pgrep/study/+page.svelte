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
    import HintRung from "$lib/components/HintRung.svelte";
    import StudyFrame from "$lib/components/StudyFrame.svelte";
    import { renderMath } from "$lib/pgrep/math";
    import { resetSignal, setLearning } from "$lib/pgrep/nav";

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

    interface LadderRung {
        rung: "nudge" | "decompose" | "sibling" | "reveal";
        prompt_html?: string;
        reveal_html?: string;
    }

    interface CommitResult {
        correct: boolean;
        correct_choice: string;
        rationale_html: string;
        ladder: LadderRung[];
    }

    interface TutorGrade {
        ai: string;
        mode: string;
        coverage?: string;
        probe?: string;
        giveaway_blocked?: boolean;
    }

    interface Synthesis {
        ai: string;
        recap: { attempted: number; correct: number; accuracy: number };
        patterns: string[];
        principles: string[];
        calibration: string;
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
        { label: "Again", value: 1 },
        { label: "Hard", value: 2 },
        { label: "Good", value: 3 },
        { label: "Easy", value: 4 },
    ];
    const RUNG_TITLES: Record<string, string> = {
        nudge: "Nudge",
        decompose: "Break it down",
        sibling: "Sibling worked example",
        reveal: "Reveal and explain back",
    };

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
    let revealedRungs = 0;
    let shownSteps: Record<number, boolean> = {};
    // M5 seam: when the current problem was shown, so commit can log response_ms
    // (the client-measured think time). Used only to filter rapid guesses.
    let problemShownAt = 0;

    // AI upgrade state (L4). AI is off by default, so the ladder stays the static
    // reveal-and-self-compare unless the learner turns AI on in Settings.
    let aiOn = false;
    let learnerStep = "";
    let learnerWhy = "";
    let gradeResult: TutorGrade | null = null;
    let grading = false;
    let synthesis: Synthesis | null = null;

    onMount(async () => {
        try {
            const status = await pgrepCall<{ enabled: boolean }>("pgrepAiStatus", {});
            aiOn = status.enabled;
        } catch {
            aiOn = false;
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
        revealedRungs = 0;
        shownSteps = {};
        doorEmpty = false;
        learnerStep = "";
        learnerWhy = "";
        gradeResult = null;
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
                    await fetchSynthesis();
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
            // On a miss, open the ladder at its first rung. On a hit, keep it
            // closed behind an opt-in toggle.
            revealedRungs = committed.correct ? 0 : 1;
            shownSteps = {};
        } catch {
            errored = true;
        } finally {
            busy = false;
        }
    }

    async function gradeStep(): Promise<void> {
        if (!problem || !learnerStep.trim() || grading) {
            return;
        }
        grading = true;
        try {
            gradeResult = await pgrepCall<TutorGrade>("pgrepTutorGrade", {
                note_id: problem.note_id,
                subgoal_index: 0,
                learner_text: learnerStep,
                learner_why: learnerWhy,
            });
        } catch {
            gradeResult = null;
        } finally {
            grading = false;
        }
    }

    async function fetchSynthesis(): Promise<void> {
        try {
            synthesis = await pgrepCall<Synthesis>("pgrepTutorSynthesis", {
                session_id: sessionId,
            });
        } catch {
            synthesis = null;
        }
    }

    // Seed sample content, then reload the doors for the current scope so the
    // just-seeded items are ready to study.
    async function seedContent(): Promise<void> {
        busy = true;
        errored = false;
        try {
            await pgrepCall("pgrepSeed", {});
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
            await pgrepCall("pgrepSeed", {});
        } catch {
            doorsError = true;
            return;
        }
        await loadDoors(topicArg());
    }

    function showStep(index: number): void {
        shownSteps = { ...shownSteps, [index]: true };
    }

    function nextRung(): void {
        if (committed && revealedRungs < committed.ladder.length) {
            revealedRungs += 1;
        }
    }

    function openSolution(): void {
        if (committed) {
            revealedRungs = committed.ladder.length;
            const revealIndex = committed.ladder.findIndex((r) => r.rung === "reveal");
            if (revealIndex >= 0) {
                shownSteps = { ...shownSteps, [revealIndex]: true };
            }
        }
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
    // Typeset delimited LaTeX in the stem and rationale (no-op on plain text).
    $: renderedStem = problem ? renderMath(problem.stem_html) : "";
    $: renderedRationale = committed ? renderMath(committed.rationale_html) : "";
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
            desc: "Commit first, then work the ladder on a miss.",
            info: problemsDoor,
        },
    ];
    $: doorsReady =
        !doorsLoading && !doorsError && cardsDoor !== null && problemsDoor !== null;
    $: bothEmpty =
        doorsReady && cardsDoor?.remaining === 0 && problemsDoor?.remaining === 0;
</script>

{#if stage === "launcher"}
    <section class="wrap">
        <header class="head">
            <h1>Study</h1>
            <p class="sub">Pick how you want to train today.</p>
        </header>

        <section class="option today">
            <div class="option-body">
                <div class="eyebrow">Recommended</div>
                <div class="option-title">Start today's session</div>
                <p class="option-desc">
                    Cards and problems, with your topics mixed inside each door and
                    ordered to what moves your score.
                </p>
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
                <p class="option-desc">
                    One topic at a time. Pick it here or tap a region on your map.
                </p>
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
                <p class="option-desc">
                    A timed mock at real PGRE proportions, zero help. Blind review at
                    the end.
                </p>
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
                <p class="lead">No items here yet.</p>
                <p class="muted">Seed sample content to try a session.</p>
                <button class="btn primary" on:click={seedFromLayer}>
                    Seed sample content
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
                                        <polyline points="3,10 10,6.5 17,10" />
                                        <polyline points="3,13.5 10,10 17,13.5" />
                                        <polygon points="10,3 14,5.2 10,7.4 6,5.2" />
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
                                            <polyline points="3,10 10,6.5 17,10" />
                                            <polyline points="3,13.5 10,10 17,13.5" />
                                            <polygon
                                                points="10,3 14,5.2 10,7.4 6,5.2"
                                            />
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
{:else}
    <StudyFrame
        count={countLabel}
        topic={prettyTopic(currentTopic)}
        {topicTone}
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
                    <p class="lead">No items here yet.</p>
                    <p class="muted">Seed sample content to try this door.</p>
                    <button class="btn primary" on:click={seedContent} disabled={busy}>
                        {busy ? "Seeding sample content" : "Seed sample content"}
                    </button>
                {:else}
                    <p class="lead">This door is clear for now.</p>
                    <p class="muted">
                        Come back when more is due, or try the other door.
                    </p>
                    {#if synthesis && synthesis.recap.attempted > 0}
                        <div class="synthesis">
                            <p class="synth-recap">
                                Session: {synthesis.recap.correct}/{synthesis.recap
                                    .attempted} first-try correct.
                            </p>
                            {#if synthesis.patterns.length}
                                <p class="synth-h">Patterns</p>
                                <ul>
                                    {#each synthesis.patterns as p}<li>{p}</li>{/each}
                                </ul>
                            {/if}
                            {#if synthesis.principles.length}
                                <p class="synth-h">Principles to remember</p>
                                <ul>
                                    {#each synthesis.principles as p}<li>{p}</li>{/each}
                                </ul>
                            {/if}
                            {#if synthesis.calibration}
                                <p class="muted small">{synthesis.calibration}</p>
                            {/if}
                        </div>
                    {/if}
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
                <div class="grade-label">How well did you recall it?</div>
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
                correctKey={committed ? committed.correct_choice : null}
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
            {:else}
                <div
                    class="verdict"
                    class:hit={committed.correct}
                    class:miss={!committed.correct}
                >
                    {committed.correct ? "Correct." : "Your answer, not correct."}
                </div>
                <div class="rationale">{@html renderedRationale}</div>

                {#if committed.correct && revealedRungs === 0}
                    <div class="actions">
                        <button class="btn ghost" on:click={openSolution}>
                            Show the worked solution
                        </button>
                    </div>
                {/if}

                {#if revealedRungs > 0}
                    <div class="ladder">
                        {#each committed.ladder.slice(0, revealedRungs) as rung, i (i)}
                            <HintRung
                                title={RUNG_TITLES[rung.rung] ?? rung.rung}
                                index={i + 1}
                                total={committed.ladder.length}
                                prompt={rung.prompt_html ?? ""}
                                revealHtml={rung.reveal_html}
                                shown={shownSteps[i] ?? false}
                                onShow={() => showStep(i)}
                            />
                            {#if aiOn && rung.rung === "decompose"}
                                <div class="grade-step">
                                    <label for="learner-step">
                                        Produce this sub-goal in your own words, plus a
                                        one-line why.
                                    </label>
                                    <textarea
                                        id="learner-step"
                                        bind:value={learnerStep}
                                        rows="2"
                                        placeholder="Your sub-goal"
                                    ></textarea>
                                    <input
                                        bind:value={learnerWhy}
                                        placeholder="Why (one line)"
                                    />
                                    <button
                                        class="btn"
                                        on:click={gradeStep}
                                        disabled={grading || !learnerStep.trim()}
                                    >
                                        {grading ? "Grading" : "Grade my step"}
                                    </button>
                                    {#if gradeResult}
                                        <div class="grade-result">
                                            <span class="cov {gradeResult.coverage}">
                                                {gradeResult.coverage}
                                            </span>
                                            <p class="probe">{gradeResult.probe}</p>
                                            {#if gradeResult.giveaway_blocked}
                                                <p class="muted small">
                                                    A leaking hint was blocked; here is
                                                    a safe nudge instead.
                                                </p>
                                            {/if}
                                        </div>
                                    {/if}
                                </div>
                            {/if}
                        {/each}
                    </div>

                    {#if revealedRungs < committed.ladder.length}
                        <div class="actions">
                            <button class="btn ghost" on:click={nextRung}>
                                Next step
                            </button>
                        </div>
                    {/if}

                    <p class="ladder-footer">Working it out yourself is the point.</p>
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

    .rationale {
        margin-top: var(--space-1);
        color: var(--text);
        font-size: var(--text-body);
        line-height: 1.6;

        :global(p) {
            margin: 0 0 0.6em;
        }
    }

    .ladder {
        margin-top: var(--space-2);
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
    }

    .ladder-footer {
        margin: var(--space-2) 0 0;
        text-align: center;
        font-size: var(--text-small);
        color: var(--muted);
        opacity: 0.8;
    }

    .grade-step {
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin: var(--space-1) 0 var(--space-2);
        padding: var(--space-2);
        border: var(--hairline);
        border-radius: var(--radius-control);

        label {
            font-size: var(--text-small);
            color: var(--muted);
        }

        textarea,
        input {
            font-family: var(--font-ui);
            font-size: var(--text-body);
            color: var(--text);
            background: var(--canvas);
            border: var(--hairline);
            border-radius: var(--radius-control);
            padding: 8px 10px;
            resize: vertical;
        }

        button {
            align-self: flex-start;
        }
    }

    .grade-result {
        margin-top: 6px;

        .cov {
            display: inline-block;
            font-size: var(--text-caption);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            padding: 2px 8px;
            border-radius: var(--radius-pill);
            border: var(--hairline);
            color: var(--muted);
        }

        .cov.covered {
            color: var(--success);
            border-color: var(--success);
        }

        .probe {
            margin: 8px 0 0;
            font-size: var(--text-body);
            line-height: 1.5;
        }
    }

    .synthesis {
        align-self: stretch;
        margin-top: var(--space-2);
        padding-top: var(--space-2);
        border-top: var(--hairline);

        .synth-recap {
            font-weight: 600;
            margin: 0 0 8px;
        }

        .synth-h {
            margin: 10px 0 4px;
            font-size: var(--text-caption);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: var(--muted);
        }

        ul {
            margin: 0;
            padding-left: 18px;
            font-size: var(--text-body);
            line-height: 1.5;
        }
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
