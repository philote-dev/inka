<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

pgrep Exam mode (L5.9). The readiness-measuring instrument: a timed mock over
Problems at real PGRE proportions, zero help, blind review until the end. A large
countdown, a question navigator, a flag toggle, and a clear no-hints line. On
finish it shows the projected Readiness scaled score with its range (reusing the
ScoreCard), the pace read from response_ms, and a blind review of every question.
No AI, no confidence, no scheduling state touched. Both themes use the pgrep
tokens. The countdown runs on a 1s interval so nothing blocks the 100ms rule.
-->
<script lang="ts">
    import { onDestroy } from "svelte";

    import { goto } from "$app/navigation";

    import ChoiceList from "$lib/components/ChoiceList.svelte";
    import ScoreCard from "$lib/components/ScoreCard.svelte";
    import { renderMath } from "$lib/pgrep/math";

    import { pgrepCall } from "../../lib/bridge";

    interface StartResult {
        session_id: string;
        total: number;
        duration_s: number;
        seconds_per_question: number;
        no_help_line: string;
    }

    interface ExamItem {
        kind: "item";
        index: number;
        note_id: number;
        stem_html: string;
        choices: string[];
        topic: string | null;
        total: number;
        answered: number;
        selected: string;
        flagged: boolean;
        // Optional per-question figure markup (diagrams). Absent until the
        // backend serves it, so the figure slot stays empty for now.
        figure?: string;
    }

    interface EmptyItem {
        kind: "empty";
    }

    interface Pace {
        count: number;
        median_ms: number;
        mean_ms: number;
        fastest_ms: number;
        slowest_ms: number;
        rapid_guesses: number;
        rapid_guess_floor_ms: number;
    }

    interface ReviewItem {
        index: number;
        note_id: number;
        topic: string | null;
        stem_html: string;
        choices: string[];
        selected: string;
        correct_choice: string;
        correct: boolean;
        answered: boolean;
        flagged: boolean;
    }

    interface ResultData {
        n_served: number;
        n_answered: number;
        correct: number;
        incorrect: number;
        skipped: number;
        accuracy: number;
        raw_actual: number;
        coverage_pct: number;
        coverage_gate: number;
        untested_topics: string[];
        pace: Pace | null;
        scaled: number | null;
        low: number | null;
        high: number | null;
        abstain: boolean;
        reason: string | null;
        review: ReviewItem[];
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
    const CHOICE_LETTERS = ["A", "B", "C", "D", "E"];
    // The navigator shows one page of this many question cells at a time.
    const NAV_CHUNK = 10;

    type Phase = "intro" | "running" | "review";

    let phase: Phase = "intro";
    let section = false; // false = full-length, true = shorter sectioned run

    let sessionId = "";
    let total = 0;
    let durationS = 0;
    let remainingS = 0;
    let noHelpLine = "No hints. No help. Timed like the exam.";

    let loading = false;
    let busy = false;
    // Scoring is its own flag because busy is also raised during navigation, and
    // only the finish/scoring pass should take over the running view.
    let scoring = false;
    let timeUp = false; // the countdown, not the user, ended the exam
    let errored = false;
    let startedEmpty = false;

    let current: ExamItem | null = null;
    // Client-side model of each question's state, keyed by index.
    let answers: Record<number, { selected: string; flagged: boolean }> = {};

    let result: ResultData | null = null;

    // response_ms measurement: accumulate focus time per question (M5 pace signal).
    let elapsedMs: Record<number, number> = {};
    let activeIndex: number | null = null;
    let activeSince: number | null = null;

    let timer: ReturnType<typeof setInterval> | null = null;

    // Leaving a running exam discards an uncommitted session, so the running-phase
    // Leave takes two clicks: the first arms it, a second within a few seconds
    // confirms, and a stray single click disarms itself.
    let leaveArmed = false;
    let leaveTimer: ReturnType<typeof setTimeout> | undefined;

    // Which navigator page is visible. It follows the current question but can
    // be paged on its own to preview other ranges without jumping there.
    let navChunk = 0;

    function label(slug: string | null): string {
        if (!slug) {
            return "";
        }
        const key = slug.replace(/^topic::/, "").split("::")[0];
        return CATEGORY_LABELS[key] ?? key.replace(/_/g, " ");
    }

    function now(): number {
        return typeof performance !== "undefined" ? performance.now() : Date.now();
    }

    function flushElapsed(): void {
        if (activeIndex !== null && activeSince !== null) {
            const delta = now() - activeSince;
            elapsedMs[activeIndex] = (elapsedMs[activeIndex] ?? 0) + delta;
            activeSince = now();
        }
    }

    function stopTimer(): void {
        if (timer !== null) {
            clearInterval(timer);
            timer = null;
        }
    }

    function startTimer(): void {
        stopTimer();
        timer = setInterval(() => {
            remainingS -= 1;
            if (remainingS <= 0) {
                remainingS = 0;
                timeUp = true;
                finish();
            }
        }, 1000);
    }

    onDestroy(() => {
        stopTimer();
        clearTimeout(leaveTimer);
    });

    async function startExam(): Promise<void> {
        loading = true;
        errored = false;
        startedEmpty = false;
        timeUp = false;
        answers = {};
        elapsedMs = {};
        result = null;
        try {
            const res = await pgrepCall<StartResult>("pgrepExamStart", { section });
            sessionId = res.session_id;
            total = res.total;
            durationS = res.duration_s;
            remainingS = res.duration_s;
            noHelpLine = res.no_help_line;
            if (total === 0) {
                startedEmpty = true;
                phase = "running";
                return;
            }
            phase = "running";
            await loadIndex(0);
            startTimer();
        } catch {
            errored = true;
        } finally {
            loading = false;
        }
    }

    async function seedContent(): Promise<void> {
        busy = true;
        errored = false;
        try {
            await pgrepCall("pgrepSeed", {});
            await startExam();
        } catch {
            errored = true;
        } finally {
            busy = false;
        }
    }

    async function loadIndex(index: number): Promise<void> {
        if (index < 0 || index >= total) {
            return;
        }
        flushElapsed();
        busy = true;
        errored = false;
        try {
            const item = await pgrepCall<ExamItem | EmptyItem>("pgrepExamNext", {
                session_id: sessionId,
                index,
            });
            if (item.kind === "item") {
                current = item;
                activeIndex = item.index;
                activeSince = now();
            }
        } catch {
            errored = true;
        } finally {
            busy = false;
        }
    }

    // Advance to the next unanswered question (the natural next step). Returns
    // false when every question has an answer, so the caller can offer Finish.
    async function loadNextUnanswered(): Promise<boolean> {
        flushElapsed();
        busy = true;
        errored = false;
        try {
            const item = await pgrepCall<ExamItem | EmptyItem>("pgrepExamNext", {
                session_id: sessionId,
            });
            if (item.kind === "item") {
                current = item;
                activeIndex = item.index;
                activeSince = now();
                return true;
            }
            return false;
        } catch {
            errored = true;
            return true;
        } finally {
            busy = false;
        }
    }

    async function record(selected: string): Promise<void> {
        if (!current) {
            return;
        }
        flushElapsed();
        const index = current.index;
        const flagged = answers[index]?.flagged ?? current.flagged;
        answers[index] = { selected, flagged };
        answers = answers; // trigger reactivity
        current = { ...current, selected };
        try {
            await pgrepCall("pgrepExamAnswer", {
                session_id: sessionId,
                index,
                selected,
                response_ms: Math.round(elapsedMs[index] ?? 0),
                flagged,
            });
        } catch {
            // A dropped record is recoverable: the value is still held locally and
            // re-sent on the next answer or at finish. Never blocks the exam.
        }
    }

    function select(key: string): void {
        void record(key);
    }

    async function toggleFlag(): Promise<void> {
        if (!current) {
            return;
        }
        const index = current.index;
        const selected = answers[index]?.selected ?? current.selected ?? "";
        const flagged = !(answers[index]?.flagged ?? current.flagged);
        answers[index] = { selected, flagged };
        answers = answers;
        current = { ...current, flagged };
        try {
            await pgrepCall("pgrepExamAnswer", {
                session_id: sessionId,
                index,
                selected,
                response_ms: Math.round(elapsedMs[index] ?? 0),
                flagged,
            });
        } catch {
            // held locally; re-sent on the next answer or at finish
        }
    }

    async function next(): Promise<void> {
        if (!current) {
            return;
        }
        if (current.index + 1 < total) {
            await loadIndex(current.index + 1);
        } else {
            await loadNextUnanswered();
        }
    }

    async function prev(): Promise<void> {
        if (current && current.index > 0) {
            await loadIndex(current.index - 1);
        }
    }

    async function finish(): Promise<void> {
        if (phase !== "running") {
            return;
        }
        stopTimer();
        flushElapsed();
        busy = true;
        scoring = true;
        errored = false;
        try {
            result = await pgrepCall<ResultData>("pgrepExamResult", {
                session_id: sessionId,
            });
            phase = "review";
        } catch {
            errored = true;
        } finally {
            busy = false;
            scoring = false;
        }
    }

    function leave(): void {
        stopTimer();
        void goto("/pgrep/study");
    }

    function armLeave(): void {
        leaveArmed = true;
        clearTimeout(leaveTimer);
        leaveTimer = setTimeout(() => {
            leaveArmed = false;
        }, 4000);
    }

    // Running-phase Leave only: intro and review leave directly via leave().
    function onLeaveClick(): void {
        if (leaveArmed) {
            clearTimeout(leaveTimer);
            leaveArmed = false;
            leave();
        } else {
            armLeave();
        }
    }

    function navPageBack(): void {
        if (navChunk > 0) {
            navChunk -= 1;
        }
    }

    function navPageForward(): void {
        if (navChunk < chunkCount - 1) {
            navChunk += 1;
        }
    }

    function choiceItems(choices: string[]): Array<{ key: string; html: string }> {
        return choices.map((html, i) => ({
            key: CHOICE_LETTERS[i] ?? `${i + 1}`,
            html,
        }));
    }

    function fmtClock(seconds: number): string {
        const s = Math.max(0, Math.floor(seconds));
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = s % 60;
        const mm = String(m).padStart(2, "0");
        const ss = String(sec).padStart(2, "0");
        return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
    }

    function fmtSeconds(ms: number): string {
        return `${(ms / 1000).toFixed(1)}s`;
    }

    function verdictLabel(item: ReviewItem): string {
        if (item.correct) {
            return "Correct";
        }
        return item.answered ? "Not correct" : "Skipped";
    }

    // Typeset delimited LaTeX in the running-question stem (no-op on plain text).
    $: renderedStem = current ? renderMath(current.stem_html) : "";

    // Navigator cells: number, answered, flagged, current.
    $: cells = Array.from({ length: total }, (_, i) => ({
        index: i,
        answered: !!answers[i]?.selected,
        flagged: !!answers[i]?.flagged,
        current: current?.index === i,
    }));
    $: answeredCount = cells.filter((c) => c.answered).length;
    $: flaggedCount = cells.filter((c) => c.flagged).length;
    $: lowOnTime = phase === "running" && durationS > 0 && remainingS <= 60;

    // Navigator pagination: one page of NAV_CHUNK cells, kept aligned with the
    // current question, with a derived window the arrows can page through.
    $: chunkCount = Math.max(1, Math.ceil(total / NAV_CHUNK));
    $: if (current) {
        navChunk = Math.floor(current.index / NAV_CHUNK);
    }
    $: visibleCells = cells.slice(
        navChunk * NAV_CHUNK,
        navChunk * NAV_CHUNK + NAV_CHUNK,
    );

    // Readiness result read for the ScoreCard.
    $: resultCovered = !!result && !result.abstain && result.scaled != null;
    $: readinessRange =
        resultCovered && result
            ? ([result.low, result.high] as [number, number])
            : undefined;
    $: readinessAbstain =
        result && result.abstain
            ? {
                  message: result.reason ?? "Not enough of the exam is covered yet",
                  missing: result.untested_topics.length
                      ? `Cover ${result.untested_topics
                            .map(label)
                            .join(", ")} to project a score.`
                      : undefined,
              }
            : undefined;
</script>

{#if phase === "intro"}
    <section class="intro">
        <button class="back" on:click={leave}>Back to Study</button>
        <header class="head">
            <h1>Exam mode</h1>
            <p class="sub">A timed mock at real exam proportions.</p>
        </header>

        <div class="card">
            <p class="no-help">{noHelpLine}</p>
            <ul class="facts">
                <li>Real PGRE topic proportions.</li>
                <li>Blind review. Answers show only at the end.</li>
                <li>Pace is measured, not penalized.</li>
            </ul>

            <div class="lengths">
                <label class="len" class:on={!section}>
                    <input type="radio" bind:group={section} value={false} />
                    <span class="len-name">Full length</span>
                    <span class="len-desc">Every topic, exam pace.</span>
                </label>
                <label class="len" class:on={section}>
                    <input type="radio" bind:group={section} value={true} />
                    <span class="len-name">Short section</span>
                    <span class="len-desc">A quicker timed set.</span>
                </label>
            </div>

            <div class="actions">
                <button class="btn primary" on:click={startExam} disabled={loading}>
                    {loading ? "Starting" : "Start exam"}
                </button>
                <span class="muted small">The clock starts on the first question.</span>
            </div>
            {#if errored}
                <p class="muted small">Something went wrong. Try again.</p>
            {/if}
        </div>
    </section>
{:else if phase === "running"}
    <section class="exam">
        <header class="hero">
            <div class="hero-top">
                <button
                    class="leave"
                    class:armed={leaveArmed}
                    aria-label={leaveArmed
                        ? "Leave without scoring"
                        : "Leave exam"}
                    on:click={onLeaveClick}
                >
                    {leaveArmed ? "Leave without scoring?" : "Leave"}
                </button>
            </div>
            <div class="timer" class:low={lowOnTime} aria-label="Time remaining">
                {fmtClock(remainingS)}
            </div>
            {#if current}
                <div
                    class="hero-pos"
                    aria-label="Question {current.index + 1} of {total}"
                >
                    {current.index + 1} / {total}
                </div>
            {/if}
        </header>

        <p class="no-help-strip">{noHelpLine}</p>

        {#if scoring}
            <div class="notice">
                <p class="lead">Scoring your exam</p>
                <p class="muted">
                    {timeUp
                        ? "Time is up. Tallying your answers."
                        : "Tallying your answers."}
                </p>
            </div>
        {:else if startedEmpty}
            <div class="notice">
                <p class="lead">No problems to sit yet.</p>
                <p class="muted">Seed sample content to try a timed mock.</p>
                <button class="btn" on:click={seedContent} disabled={busy}>
                    {busy ? "Seeding sample content" : "Seed sample content"}
                </button>
            </div>
        {:else if current}
            <div class="qhead">
                {#if current.topic}<span class="qtopic">
                        {label(current.topic)}
                    </span>{/if}
                <button
                    class="flag"
                    class:on={answers[current.index]?.flagged ?? current.flagged}
                    on:click={toggleFlag}
                >
                    {(answers[current.index]?.flagged ?? current.flagged)
                        ? "Flagged"
                        : "Flag"}
                </button>
            </div>

            <div class="stem">{@html renderedStem}</div>

            {#if current.figure}
                <div class="figure">{@html current.figure}</div>
            {/if}

            <ChoiceList
                choices={choiceItems(current.choices)}
                selected={answers[current.index]?.selected ?? current.selected ?? ""}
                committed={false}
                correctKey={null}
                onSelect={select}
            />

            <div class="controls">
                <div class="nudge">
                    <button
                        class="btn small ghost"
                        on:click={prev}
                        disabled={current.index === 0}
                    >
                        Prev
                    </button>
                    <button
                        class="btn small"
                        on:click={next}
                        disabled={current.index + 1 >= total}
                    >
                        Next
                    </button>
                </div>
                <button class="btn primary" on:click={finish} disabled={busy}>
                    Finish exam
                </button>
            </div>

            <div class="nav-area">
                <div class="nav-summary">
                    {answeredCount} of {total} answered
                    {#if flaggedCount}<span class="flag-count">
                            {flaggedCount} flagged
                        </span>{/if}
                </div>
                <div class="nav-row">
                    <button
                        class="nav-arrow"
                        on:click={navPageBack}
                        disabled={navChunk === 0}
                        aria-label="Earlier questions"
                    >
                        &lsaquo;
                    </button>
                    <nav class="navigator" aria-label="Question navigator">
                        {#each visibleCells as cell (cell.index)}
                            <button
                                class="cell"
                                class:answered={cell.answered}
                                class:flagged={cell.flagged}
                                class:current={cell.current}
                                on:click={() => loadIndex(cell.index)}
                                aria-current={cell.current ? "true" : undefined}
                            >
                                {cell.index + 1}
                                {#if cell.flagged}<span
                                        class="cell-flag"
                                        aria-hidden="true"
                                    ></span>{/if}
                            </button>
                        {/each}
                    </nav>
                    <button
                        class="nav-arrow"
                        on:click={navPageForward}
                        disabled={navChunk >= chunkCount - 1}
                        aria-label="Later questions"
                    >
                        &rsaquo;
                    </button>
                </div>
            </div>

            <p class="muted small hint">
                Answer in any order. Flag to revisit. Finish when you are ready.
            </p>
        {:else if errored}
            <div class="notice">
                <p class="lead">Something went wrong.</p>
                <button class="btn" on:click={() => loadIndex(0)}>Try again</button>
            </div>
        {/if}
    </section>
{:else if phase === "review" && result}
    <section class="review">
        <header class="head">
            <h1>Exam result</h1>
            <p class="sub">Your projected score, pace, and a full review.</p>
        </header>

        <div class="score-row">
            <ScoreCard
                kind="readiness"
                value={result.scaled ?? undefined}
                range={readinessRange}
                howSure={resultCovered
                    ? `${Math.round(result.coverage_pct * 100)} percent covered`
                    : ""}
                updated="Just now"
                abstain={readinessAbstain}
            />
            <div class="tallies">
                <div class="tally">
                    <span class="t-value">{result.correct}/{result.n_answered}</span>
                    <span class="t-label">Correct</span>
                </div>
                <div class="tally">
                    <span class="t-value">{Math.round(result.accuracy * 100)}%</span>
                    <span class="t-label">Accuracy</span>
                </div>
                <div class="tally">
                    <span class="t-value">{result.skipped}</span>
                    <span class="t-label">Skipped</span>
                </div>
                {#if result.pace}
                    <div class="tally">
                        <span class="t-value">{fmtSeconds(result.pace.median_ms)}</span>
                        <span class="t-label">Median pace</span>
                    </div>
                {/if}
            </div>
        </div>

        {#if result.pace}
            <p class="muted small pace-note">
                Pace ran {fmtSeconds(result.pace.fastest_ms)} to {fmtSeconds(
                    result.pace.slowest_ms,
                )} per question.
                {#if result.pace.rapid_guesses > 0}
                    {result.pace.rapid_guesses} looked rushed.
                {/if}
                Latency is pace here, never a penalty.
            </p>
        {/if}

        <div class="review-list">
            <h2>Review</h2>
            {#each result.review as item (item.index)}
                <div class="ritem" class:skipped={!item.answered}>
                    <div class="rhead">
                        <span class="rnum">Question {item.index + 1}</span>
                        {#if item.topic}<span class="rtopic">
                                {label(item.topic)}
                            </span>{/if}
                        {#if item.flagged}<span class="rflag">Flagged</span>{/if}
                        <span
                            class="rverdict"
                            class:hit={item.correct}
                            class:miss={item.answered && !item.correct}
                        >
                            {verdictLabel(item)}
                        </span>
                    </div>
                    <div class="stem">{@html renderMath(item.stem_html)}</div>
                    <ChoiceList
                        choices={choiceItems(item.choices)}
                        selected={item.selected}
                        committed={true}
                        correctKey={item.correct_choice}
                    />
                </div>
            {/each}
        </div>

        <div class="actions end">
            <button class="btn" on:click={() => (phase = "intro")}>New exam</button>
            <button class="btn ghost" on:click={leave}>Back to Study</button>
        </div>
    </section>
{/if}

<style lang="scss">
    .intro,
    .review {
        max-width: 720px;
        margin: 0 auto;
        padding: 48px 24px 64px;
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
        font-family: var(--font-ui);
        color: var(--text);
    }

    .exam {
        max-width: 720px;
        margin: 0 auto;
        padding: 20px 24px 64px;
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        font-family: var(--font-ui);
        color: var(--text);
    }

    .head {
        h1 {
            margin: 0;
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        .sub {
            margin: 6px 0 0;
            color: var(--muted);
            font-size: var(--text-body);
        }
    }

    .back {
        align-self: flex-start;
        background: none;
        border: none;
        color: var(--muted);
        font-family: var(--font-ui);
        font-size: var(--text-small);
        cursor: pointer;
        padding: 0;

        &:hover {
            color: var(--text);
        }
    }

    .card {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);
        padding: var(--space-3);
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        border-left: 3px solid var(--readiness);
    }

    .no-help {
        margin: 0;
        font-size: var(--text-emphasis);
        font-weight: 600;
    }

    .facts {
        margin: 0;
        padding-left: 18px;
        color: var(--muted);
        font-size: var(--text-body);
        line-height: 1.6;
    }

    .lengths {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--space-1);
    }

    .len {
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 12px 14px;
        border: var(--hairline);
        border-radius: var(--radius-row);
        cursor: pointer;
        transition: var(--transition-calm);

        input {
            position: absolute;
            opacity: 0;
            pointer-events: none;
        }

        &.on {
            border-color: var(--readiness-text);
            background: var(--hover-wash);
        }
    }

    .len-name {
        font-weight: 500;
        font-size: var(--text-body);
    }

    .len-desc {
        color: var(--muted);
        font-size: var(--text-small);
    }

    /* Running exam */
    .hero {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
    }

    .hero-top {
        align-self: stretch;
        display: flex;
        justify-content: flex-end;
    }

    .leave {
        background: none;
        border: var(--hairline);
        border-radius: var(--radius-control);
        color: var(--muted);
        padding: 6px 12px;
        font-family: var(--font-ui);
        font-size: var(--text-small);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
            background: var(--hover-wash);
        }

        &.armed {
            color: var(--caution);
            border-color: var(--caution);

            &:hover {
                color: var(--caution);
            }
        }
    }

    .timer {
        font-family: var(--font-mono);
        font-size: 56px;
        font-weight: 500;
        font-variant-numeric: tabular-nums;
        letter-spacing: 0.02em;
        line-height: 1.05;
        color: var(--text);

        &.low {
            color: var(--caution);
        }
    }

    .hero-pos {
        font-family: var(--font-mono);
        font-size: var(--text-body);
        color: var(--muted);
        font-variant-numeric: tabular-nums;
    }

    .no-help-strip {
        margin: 0;
        font-size: var(--text-small);
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        text-align: center;
    }

    .qhead {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        margin-top: var(--space-1);
    }

    .qtopic {
        font-size: var(--text-caption);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--performance-text);
    }

    .flag {
        margin-left: auto;
        background: none;
        border: var(--hairline);
        border-radius: var(--radius-pill);
        padding: 4px 14px;
        font-size: var(--text-small);
        color: var(--muted);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            border-color: var(--muted);
            color: var(--text);
        }

        &.on {
            color: var(--caution);
            border-color: var(--caution);
        }
    }

    .stem {
        font-size: var(--text-content);
        line-height: 1.6;
        margin: var(--space-1) 0 var(--space-2);

        :global(p) {
            margin: 0 0 0.6em;
        }
    }

    .figure {
        display: flex;
        justify-content: center;
        margin: 0 0 var(--space-2);

        :global(svg),
        :global(img) {
            max-width: 100%;
            height: auto;
        }
    }

    .controls {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        margin-top: var(--space-2);
        flex-wrap: wrap;

        .primary {
            margin-left: auto;
        }
    }

    .nudge {
        display: flex;
        gap: var(--space-1);
    }

    .nav-area {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
        margin-top: var(--space-2);
        padding-top: var(--space-2);
        border-top: var(--hairline);
    }

    .nav-summary {
        text-align: center;
        font-size: var(--text-small);
        color: var(--muted);
        font-variant-numeric: tabular-nums;
    }

    .flag-count {
        margin-left: 10px;
        color: var(--caution);
    }

    .nav-row {
        display: flex;
        align-items: center;
        gap: var(--space-1);
    }

    .nav-arrow {
        flex: none;
        width: 34px;
        height: 34px;
        display: flex;
        align-items: center;
        justify-content: center;
        border: var(--hairline);
        border-radius: 8px;
        background: var(--surface);
        color: var(--muted);
        font-family: var(--font-mono);
        font-size: var(--text-body);
        line-height: 1;
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover:not(:disabled) {
            border-color: var(--muted);
            color: var(--text);
        }

        &:disabled {
            opacity: 0.4;
            cursor: default;
        }
    }

    .navigator {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        gap: 6px;
        flex: 1;
    }

    .cell {
        position: relative;
        width: 34px;
        height: 34px;
        display: flex;
        align-items: center;
        justify-content: center;
        border: var(--hairline);
        border-radius: 8px;
        background: var(--surface);
        color: var(--muted);
        font-family: var(--font-mono);
        font-size: var(--text-small);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            border-color: var(--muted);
        }

        &.answered {
            color: var(--text);
            border-color: var(--performance-tint);
            background: var(--performance-wash);
        }

        &.current {
            border-color: var(--text);
            border-width: 1.5px;
            color: var(--text);
        }
    }

    .cell-flag {
        position: absolute;
        top: 3px;
        right: 3px;
        width: 5px;
        height: 5px;
        border-radius: var(--radius-pill);
        background: var(--caution);
    }

    .hint {
        margin: var(--space-1) 0 0;
        text-align: center;
    }

    /* Result */
    .score-row {
        display: grid;
        grid-template-columns: minmax(240px, 1fr) 1fr;
        gap: var(--space-2);
        align-items: start;
    }

    .tallies {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--space-1);
    }

    .tally {
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding: 14px 16px;
        border: var(--hairline);
        border-radius: var(--radius-row);
        background: var(--surface);
    }

    .t-value {
        font-family: var(--font-mono);
        font-size: 22px;
        font-weight: 500;
        font-variant-numeric: tabular-nums;
    }

    .t-label {
        font-size: var(--text-caption);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--muted);
    }

    .pace-note {
        margin: 0;
        line-height: 1.55;
    }

    .review-list {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);

        h2 {
            margin: var(--space-1) 0 0;
            font-size: var(--text-emphasis);
            font-weight: 600;
        }
    }

    .ritem {
        border: var(--hairline);
        border-radius: var(--radius-card);
        padding: var(--space-2);
        background: var(--surface);

        &.skipped {
            opacity: 0.75;
        }

        .stem {
            font-size: var(--text-body);
            margin: 6px 0 var(--space-1);
        }
    }

    .rhead {
        display: flex;
        align-items: center;
        gap: var(--space-1);
        flex-wrap: wrap;
    }

    .rnum {
        font-size: var(--text-small);
        color: var(--muted);
        font-variant-numeric: tabular-nums;
    }

    .rtopic {
        font-size: var(--text-caption);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--performance-text);
    }

    .rflag {
        font-size: var(--text-caption);
        color: var(--caution);
    }

    .rverdict {
        margin-left: auto;
        font-size: var(--text-small);
        font-weight: 500;
        color: var(--muted);

        &.hit {
            color: var(--success);
        }

        &.miss {
            color: var(--performance-text);
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

    .actions {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        flex-wrap: wrap;
        margin-top: var(--space-1);

        &.end {
            margin-top: var(--space-2);
        }
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
        transition: var(--transition-calm);

        &:hover:not(:disabled) {
            background: var(--hover-wash);
            border-color: var(--muted);
        }

        &:disabled {
            cursor: default;
            opacity: 0.55;
        }

        &.small {
            padding: 7px 12px;
            font-size: var(--text-small);
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
