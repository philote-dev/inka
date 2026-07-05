<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

pgrep Study (L2.1). Two doors, never one shuffled queue. Cards is retrieval
(memory, amber) and runs the real FSRS review loop. Problems is practice
(performance, blue) with a commit gate before any help and a static wrong-answer
ladder that only shows the final answer at the reveal rung. No AI, no confidence.
Styled with the pgrep design system (StudyFrame, ChoiceList, HintRung, GradeBar);
the data flow through pgrepCall is unchanged.
-->
<script lang="ts">
    import { page } from "$app/state";
    import { onMount } from "svelte";

    import ChoiceList from "$lib/components/ChoiceList.svelte";
    import GradeBar from "$lib/components/GradeBar.svelte";
    import HintRung from "$lib/components/HintRung.svelte";
    import StudyFrame from "$lib/components/StudyFrame.svelte";

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

    type Screen = "launcher" | "cards" | "problems";

    let screen: Screen = "launcher";
    let drillTopic = ""; // "" means all topics (cross-topic interleaving on)

    let sessionId = "";
    let loading = false;
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

    // AI upgrade state (L4). AI is off by default, so the ladder stays the static
    // reveal-and-self-compare unless the learner turns AI on in Settings.
    let aiOn = false;
    let learnerStep = "";
    let learnerWhy = "";
    let gradeResult: TutorGrade | null = null;
    let grading = false;
    let synthesis: Synthesis | null = null;

    onMount(async () => {
        // A topic preselected from the manifold focus-drill entry arrives as
        // ?topic=<slug>. Scope the drill to it so the learner lands on the
        // launcher ready to pick the Cards or Problems door for that topic.
        const preset = page.url.searchParams.get("topic") ?? "";
        if (CATEGORY_SLUGS.includes(preset)) {
            drillTopic = preset;
        }
        try {
            const status = await pgrepCall<{ enabled: boolean }>("pgrepAiStatus", {});
            aiOn = status.enabled;
        } catch {
            aiOn = false;
        }
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

    async function startDoor(door: Screen): Promise<void> {
        if (door === "launcher") {
            return;
        }
        loading = true;
        errored = false;
        startedEmpty = false;
        resetItemState();
        try {
            const res = await pgrepCall<StartResult>("pgrepStudyStart", {
                door,
                topic: topicArg(),
            });
            sessionId = res.session_id;
            screen = door;
            // Nothing to study usually means nothing seeded yet, so offer to seed.
            startedEmpty = res.remaining === 0;
            await loadNext();
        } catch {
            errored = true;
        } finally {
            loading = false;
        }
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
            } else {
                doorEmpty = true;
                if (screen === "problems" && !startedEmpty) {
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
        try {
            committed = await pgrepCall<CommitResult>("pgrepStudyCommit", {
                note_id: problem.note_id,
                session_id: sessionId,
                selected,
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

    async function seedContent(): Promise<void> {
        busy = true;
        errored = false;
        try {
            await pgrepCall("pgrepSeed", {});
            await startDoor(screen === "launcher" ? "problems" : screen);
        } catch {
            errored = true;
        } finally {
            busy = false;
        }
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

    function toLauncher(): void {
        screen = "launcher";
        resetItemState();
    }

    function letterOf(index: number): string {
        return CHOICE_LETTERS[index] ?? String(index + 1);
    }

    // View helpers (presentation only, no data changes).
    let topicTone: "memory" | "performance" = "performance";
    $: topicTone = screen === "cards" ? "memory" : "performance";
    $: currentTopic = (card?.topic ?? problem?.topic ?? "").trim();
    $: remainingCount = card?.remaining ?? problem?.remaining ?? null;
    $: countLabel = remainingCount === null ? "" : `${remainingCount} left`;
    $: choiceItems = problem
        ? problem.choices.map((html, i) => ({ key: letterOf(i), html }))
        : [];
</script>

{#if screen === "launcher"}
    <section class="launcher">
        <header class="head">
            <h1>Study</h1>
            <p class="sub">Two doors. Topics mix inside each one.</p>
        </header>

        <div class="doors">
            <button
                class="door cards"
                on:click={() => startDoor("cards")}
                disabled={loading}
            >
                <span class="door-top">
                    <span class="door-name">Cards</span>
                    <span class="door-kind">Memory</span>
                </span>
                <span class="door-desc">
                    Retrieval that primes the problems. Real reviews.
                </span>
            </button>
            <button
                class="door problems"
                on:click={() => startDoor("problems")}
                disabled={loading}
            >
                <span class="door-top">
                    <span class="door-name">Problems</span>
                    <span class="door-kind">Performance</span>
                </span>
                <span class="door-desc">
                    Commit first, then work the ladder on a miss.
                </span>
            </button>
        </div>

        <div class="drill">
            <label for="drill-topic">Focus drill</label>
            <select id="drill-topic" bind:value={drillTopic}>
                <option value="">All topics</option>
                {#each CATEGORY_SLUGS as slug (slug)}
                    <option value={slug}>{CATEGORY_LABELS[slug]}</option>
                {/each}
            </select>
            <span class="muted small">Pick one topic to drill it on its own.</span>
        </div>

        {#if loading}
            <p class="muted small">Opening the door.</p>
        {/if}
        {#if errored}
            <p class="muted small">Something went wrong. Try a door again.</p>
        {/if}
    </section>
{:else}
    <StudyFrame
        count={countLabel}
        topic={currentTopic}
        {topicTone}
        onClose={toLauncher}
    >
        {#if loading || busy}
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
                    <button class="btn" on:click={seedContent} disabled={busy}>
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
                    <button class="btn" on:click={toLauncher}>Back to doors</button>
                {/if}
            </div>
        {:else if screen === "cards" && card}
            <div class="prompt">{@html card.question_html}</div>
            {#if answerShown}
                <div class="answer">{@html card.answer_html}</div>
                <div class="grade-label">How well did you recall it?</div>
                <GradeBar grades={RATINGS} disabled={busy} onGrade={grade} />
            {:else}
                <div class="actions">
                    <button class="btn primary" on:click={() => (answerShown = true)}>
                        Show answer
                    </button>
                </div>
            {/if}
        {:else if screen === "problems" && problem}
            <div class="stem">{@html problem.stem_html}</div>

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
                <div class="rationale">{@html committed.rationale_html}</div>

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
    .launcher {
        max-width: 640px;
        margin: 0 auto;
        padding: 64px 24px;
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
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

    .doors {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--space-2);
    }

    .door {
        display: flex;
        flex-direction: column;
        gap: 10px;
        text-align: left;
        padding: 20px;
        background: var(--surface);
        border: var(--hairline);
        border-left-width: 3px;
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);
        cursor: pointer;
        transition: var(--transition-calm);
        color: var(--text);

        &:hover:not(:disabled) {
            border-color: var(--muted);
        }

        &:disabled {
            cursor: default;
            opacity: 0.6;
        }

        &.cards {
            border-left-color: var(--memory);
        }

        &.problems {
            border-left-color: var(--performance);
        }
    }

    .door-top {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
    }

    .door-name {
        font-size: var(--text-emphasis);
        font-weight: 600;
        letter-spacing: -0.01em;
    }

    .door-kind {
        font-size: var(--text-caption);
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    .cards .door-kind {
        color: var(--memory-text);
    }

    .problems .door-kind {
        color: var(--performance-text);
    }

    .door-desc {
        color: var(--muted);
        font-size: var(--text-body);
        line-height: 1.5;
    }

    .drill {
        display: flex;
        align-items: center;
        gap: var(--space-1);
        flex-wrap: wrap;

        label {
            font-weight: 500;
            font-size: var(--text-body);
        }

        select {
            padding: 8px 10px;
            color: var(--text);
            background: var(--surface);
            border: var(--hairline);
            border-radius: var(--radius-control);
            font-family: var(--font-ui);
            font-size: var(--text-body);
        }
    }

    .prompt,
    .stem {
        font-size: var(--text-content);
        line-height: 1.6;
        margin-bottom: var(--space-3);

        :global(p) {
            margin: 0 0 0.6em;
        }
    }

    .answer {
        margin-top: var(--space-2);
        padding-top: var(--space-2);
        border-top: var(--hairline);
        font-size: var(--text-content);
        line-height: 1.6;

        :global(p) {
            margin: 0 0 0.6em;
        }
    }

    .grade-label {
        margin: var(--space-3) 0 var(--space-1);
        font-size: var(--text-small);
        color: var(--muted);
    }

    .stem {
        margin-bottom: var(--space-2);
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
            border-radius: 999px;
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
