<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

pgrep Study (L2.1). Two doors, never one shuffled queue. Cards is retrieval
(memory, amber) and runs the real FSRS review loop. Problems is practice
(performance, blue) with a commit gate before any help and a static wrong-answer
ladder that only shows the final answer at the reveal rung. No AI, no confidence.
-->
<script lang="ts">
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
        { label: "Again", rating: 1 },
        { label: "Hard", rating: 2 },
        { label: "Good", rating: 3 },
        { label: "Easy", rating: 4 },
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
</script>

<section class="study">
    {#if screen === "launcher"}
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
                <span class="door-name">Cards</span>
                <span class="door-desc">
                    Retrieval that primes the problems. Real reviews.
                </span>
            </button>
            <button
                class="door problems"
                on:click={() => startDoor("problems")}
                disabled={loading}
            >
                <span class="door-name">Problems</span>
                <span class="door-desc">
                    Commit first, then work the ladder on a miss.
                </span>
            </button>
        </div>

        <div class="drill">
            <label for="drill-topic">Focus drill</label>
            <select id="drill-topic" bind:value={drillTopic}>
                <option value="">All topics</option>
                {#each CATEGORY_SLUGS as slug}
                    <option value={slug}>{CATEGORY_LABELS[slug]}</option>
                {/each}
            </select>
            <span class="muted small">Pick one topic to drill it on its own.</span>
        </div>

        {#if errored}
            <p class="muted">Something went wrong. Try a door again.</p>
        {/if}
    {:else}
        <header class="head row">
            <div>
                <h1
                    class:cards-accent={screen === "cards"}
                    class:problems-accent={screen === "problems"}
                >
                    {screen === "cards" ? "Cards" : "Problems"}
                </h1>
                <p class="sub">
                    {drillTopic
                        ? `Focus on ${CATEGORY_LABELS[drillTopic] ?? drillTopic}.`
                        : "Topics mixed."}
                </p>
            </div>
            <button class="btn ghost" on:click={toLauncher}>Back</button>
        </header>

        {#if loading || busy}
            <p class="muted">Working.</p>
        {/if}

        {#if errored}
            <div class="card">
                <p>Something went wrong.</p>
                <button class="btn" on:click={loadNext}>Try again</button>
            </div>
        {:else if doorEmpty}
            <div class="card">
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
                    <button class="btn" on:click={toLauncher}>Back to doors</button>
                {/if}
            </div>
        {:else if screen === "cards" && card}
            <article class="card item cards-item">
                <div class="topic-tag">{card.topic ?? "untagged"}</div>
                <div class="prompt">{@html card.question_html}</div>
                {#if answerShown}
                    <hr />
                    <div class="prompt answer">{@html card.answer_html}</div>
                    <div class="grades">
                        {#each RATINGS as r}
                            <button
                                class="btn grade"
                                on:click={() => grade(r.rating)}
                                disabled={busy}
                            >
                                {r.label}
                            </button>
                        {/each}
                    </div>
                {:else}
                    <div class="actions">
                        <button
                            class="btn primary"
                            on:click={() => (answerShown = true)}
                        >
                            Show answer
                        </button>
                    </div>
                {/if}
                <p class="muted small">{card.remaining} left in this door.</p>
            </article>
        {:else if screen === "problems" && problem}
            <article class="card item problems-item">
                <div class="topic-tag">{problem.topic ?? "untagged"}</div>
                <div class="prompt">{@html problem.stem_html}</div>

                <ul class="choices">
                    {#each problem.choices as choice, i}
                        <li>
                            <button
                                class="choice"
                                class:picked={selected === letterOf(i)}
                                class:locked={committed !== null}
                                class:correct-choice={committed &&
                                    letterOf(i) === committed.correct_choice}
                                on:click={() =>
                                    committed ? null : (selected = letterOf(i))}
                                disabled={committed !== null}
                            >
                                <span class="letter">{letterOf(i)}</span>
                                <span class="choice-text">{@html choice}</span>
                            </button>
                        </li>
                    {/each}
                </ul>

                {#if !committed}
                    <div class="actions">
                        <button
                            class="btn primary"
                            on:click={commit}
                            disabled={!selected || busy}
                        >
                            Commit
                        </button>
                        <span class="muted small">
                            Help stays locked until you commit.
                        </span>
                    </div>
                {:else}
                    <div
                        class="verdict"
                        class:hit={committed.correct}
                        class:miss={!committed.correct}
                    >
                        {committed.correct ? "Correct." : "Not correct."}
                    </div>
                    <div class="rationale">{@html committed.rationale_html}</div>

                    {#if committed.correct}
                        {#if revealedRungs === 0}
                            <button class="btn ghost" on:click={openSolution}>
                                Show the worked solution
                            </button>
                        {/if}
                    {/if}

                    {#if revealedRungs > 0}
                        <ol class="ladder">
                            {#each committed.ladder.slice(0, revealedRungs) as rung, i}
                                <li class="rung">
                                    <div class="rung-title">
                                        {RUNG_TITLES[rung.rung] ?? rung.rung}
                                    </div>
                                    {#if rung.prompt_html}
                                        <div class="rung-prompt">
                                            {@html rung.prompt_html}
                                        </div>
                                    {/if}
                                    {#if rung.reveal_html}
                                        {#if shownSteps[i]}
                                            <div class="rung-reveal">
                                                {@html rung.reveal_html}
                                            </div>
                                        {:else}
                                            <button
                                                class="btn ghost"
                                                on:click={() => showStep(i)}
                                            >
                                                Show the step
                                            </button>
                                        {/if}
                                    {/if}
                                </li>
                            {/each}
                        </ol>

                        {#if revealedRungs < committed.ladder.length}
                            <button class="btn ghost" on:click={nextRung}>
                                Next step
                            </button>
                        {/if}
                    {/if}

                    <div class="actions">
                        <button class="btn primary" on:click={loadNext} disabled={busy}>
                            Next
                        </button>
                        <span class="muted small">
                            {problem.remaining} left in this door.
                        </span>
                    </div>
                {/if}
            </article>
        {/if}
    {/if}
</section>

<style lang="scss">
    .study {
        // Cards are memory (amber); Problems are performance (blue).
        --cards-accent: #a9752a;
        --problems-accent: #2f6db0;

        max-width: 680px;
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }

    :global(.night-mode) .study {
        --cards-accent: #ebcb8b;
        --problems-accent: #81a1c1;
    }

    .head {
        h1 {
            margin: 0;
            font-size: 1.25rem;
        }

        .sub {
            margin: 0.15rem 0 0;
            color: var(--fg-subtle);
        }

        &.row {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 1rem;
        }
    }

    .cards-accent {
        color: var(--cards-accent);
    }

    .problems-accent {
        color: var(--problems-accent);
    }

    .doors {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.75rem;
    }

    .door {
        display: flex;
        flex-direction: column;
        gap: 0.35rem;
        padding: 1rem 1.1rem;
        text-align: left;
        color: var(--fg);
        background: var(--canvas-elevated);
        border: 1px solid var(--border);
        border-radius: var(--border-radius-medium, 12px);
        cursor: pointer;

        &:hover {
            border-color: var(--fg-subtle);
        }

        &:disabled {
            cursor: default;
            opacity: 0.6;
        }

        &.cards {
            border-left: 3px solid var(--cards-accent);
        }

        &.problems {
            border-left: 3px solid var(--problems-accent);
        }

        .door-name {
            font-size: 1.1rem;
            font-weight: 600;
        }

        .door-desc {
            color: var(--fg-subtle);
            font-size: 0.9rem;
        }
    }

    .drill {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        flex-wrap: wrap;

        label {
            font-weight: 550;
        }

        select {
            padding: 0.3rem 0.5rem;
            color: var(--fg);
            background: var(--canvas-elevated);
            border: 1px solid var(--border);
            border-radius: var(--border-radius, 6px);
        }
    }

    .card {
        padding: 1rem 1.1rem;
        background: var(--canvas-elevated);
        border: 1px solid var(--border);
        border-radius: var(--border-radius-medium, 12px);
    }

    .item {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }

    .cards-item {
        border-left: 3px solid var(--cards-accent);
    }

    .problems-item {
        border-left: 3px solid var(--problems-accent);
    }

    .topic-tag {
        align-self: flex-start;
        font-size: 0.75rem;
        color: var(--fg-subtle);
        font-variant-numeric: tabular-nums;
    }

    .prompt {
        font-size: 1.1rem;
        line-height: 1.5;

        &.answer {
            font-weight: 550;
        }
    }

    .choices {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
    }

    .choice {
        display: flex;
        gap: 0.6rem;
        align-items: baseline;
        width: 100%;
        text-align: left;
        padding: 0.5rem 0.7rem;
        color: var(--fg);
        background: var(--canvas);
        border: 1px solid var(--border);
        border-radius: var(--border-radius, 6px);
        cursor: pointer;

        &:hover:not(.locked) {
            border-color: var(--problems-accent);
        }

        &.picked {
            border-color: var(--problems-accent);
            box-shadow: inset 0 0 0 1px var(--problems-accent);
        }

        &.locked {
            cursor: default;
        }

        &.correct-choice {
            border-color: #3a8a4f;
            box-shadow: inset 0 0 0 1px #3a8a4f;
        }

        .letter {
            font-weight: 700;
            min-width: 1.1rem;
        }
    }

    .verdict {
        font-weight: 650;

        &.hit {
            color: #3a8a4f;
        }

        &.miss {
            color: var(--problems-accent);
        }
    }

    .rationale {
        color: var(--fg);
    }

    .ladder {
        margin: 0;
        padding-left: 1.1rem;
        display: flex;
        flex-direction: column;
        gap: 0.6rem;
    }

    .rung {
        .rung-title {
            font-weight: 600;
        }

        .rung-prompt {
            margin-top: 0.15rem;
            color: var(--fg-subtle);
        }

        .rung-reveal {
            margin-top: 0.35rem;
        }
    }

    .grades {
        display: flex;
        gap: 0.4rem;
        flex-wrap: wrap;
    }

    .actions {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        flex-wrap: wrap;
    }

    .lead {
        margin: 0 0 0.25rem;
        font-size: 1.1rem;
        font-weight: 600;
    }

    .btn {
        padding: 0.4rem 0.9rem;
        color: var(--fg);
        background: var(--canvas-elevated);
        border: 1px solid var(--border);
        border-radius: var(--border-radius, 6px);
        cursor: pointer;

        &:hover {
            border-color: var(--fg-subtle);
        }

        &:disabled {
            cursor: default;
            opacity: 0.6;
        }

        &.primary {
            border-color: var(--problems-accent);
        }

        &.grade {
            min-width: 4rem;
        }

        &.ghost {
            background: transparent;
        }
    }

    .muted {
        color: var(--fg-subtle);
    }

    .small {
        font-size: 0.85rem;
    }
</style>
