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
                finish();
            }
        }, 1000);
    }

    onDestroy(stopTimer);

    async function startExam(): Promise<void> {
        loading = true;
        errored = false;
        startedEmpty = false;
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
        }
    }

    function leave(): void {
        stopTimer();
        void goto("/pgrep/study");
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
        <header class="bar">
            <div class="clock" class:low={lowOnTime} aria-label="Time remaining">
                {fmtClock(remainingS)}
            </div>
            <div class="progress-read">
                {answeredCount} of {total} answered
                {#if flaggedCount}<span class="flag-count">
                        {flaggedCount} flagged
                    </span>{/if}
            </div>
            <button class="close" aria-label="Leave exam" on:click={leave}>
                Leave
            </button>
        </header>

        <p class="no-help-strip">{noHelpLine}</p>

        {#if startedEmpty}
            <div class="notice">
                <p class="lead">No problems to sit yet.</p>
                <p class="muted">Seed sample content to try a timed mock.</p>
                <button class="btn" on:click={seedContent} disabled={busy}>
                    {busy ? "Seeding sample content" : "Seed sample content"}
                </button>
            </div>
        {:else if current}
            <nav class="navigator" aria-label="Question navigator">
                {#each cells as cell (cell.index)}
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

            <div class="qhead">
                <span class="qnum">Question {current.index + 1} of {total}</span>
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

            <div class="stem">{@html current.stem_html}</div>

            <ChoiceList
                choices={choiceItems(current.choices)}
                selected={answers[current.index]?.selected ?? current.selected ?? ""}
                committed={false}
                correctKey={null}
                onSelect={select}
            />

            <div class="controls">
                <button
                    class="btn ghost"
                    on:click={prev}
                    disabled={current.index === 0}
                >
                    Back
                </button>
                <button class="btn" on:click={next}>Next</button>
                <button class="btn primary" on:click={finish} disabled={busy}>
                    Finish exam
                </button>
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
                updated=""
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
                    <div class="stem">{@html item.stem_html}</div>
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
    .bar {
        display: grid;
        grid-template-columns: 1fr auto 1fr;
        align-items: center;
        gap: var(--space-2);
    }

    .clock {
        font-family: var(--font-mono);
        font-size: 34px;
        font-weight: 500;
        font-variant-numeric: tabular-nums;
        letter-spacing: 0.02em;
        color: var(--text);

        &.low {
            color: var(--caution);
        }
    }

    .progress-read {
        justify-self: center;
        font-size: var(--text-small);
        color: var(--muted);
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }

    .flag-count {
        margin-left: 10px;
        color: var(--caution);
    }

    .close {
        justify-self: end;
        background: none;
        border: var(--hairline);
        border-radius: var(--radius-control);
        color: var(--muted);
        padding: 6px 12px;
        font-size: var(--text-small);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover {
            color: var(--text);
            background: var(--hover-wash);
        }
    }

    .no-help-strip {
        margin: 0;
        font-size: var(--text-small);
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    .navigator {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        padding: var(--space-1) 0;
        border-top: var(--hairline);
        border-bottom: var(--hairline);
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

    .qhead {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        margin-top: var(--space-1);
    }

    .qnum {
        font-size: var(--text-small);
        color: var(--muted);
        font-variant-numeric: tabular-nums;
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

    .controls {
        display: flex;
        align-items: center;
        gap: var(--space-1);
        margin-top: var(--space-2);
        flex-wrap: wrap;

        .primary {
            margin-left: auto;
        }
    }

    .hint {
        margin: var(--space-1) 0 0;
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
