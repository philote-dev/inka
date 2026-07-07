<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep decomposition tutor harness. A durable dev control that runs the real
     gated tutor a Problems miss opens, on any problem that has decomposition data,
     without needing a full session or an actual miss. It drives the same backend
     handlers the Study page uses (pgrepTutorMcq, pgrepTutorExplain), so the AI
     explanation grade is exercised end to end. Dev-only: it lives in pgrep-lab and
     is never wired into the shipped surfaces. Use it to test and perfect the
     tutor: pick a problem, turn AI on, and walk the subproblems. -->
<script lang="ts">
    import { onMount } from "svelte";

    import SessionSynthesis from "$lib/components/SessionSynthesis.svelte";
    import SubproblemCard from "$lib/components/SubproblemCard.svelte";
    import { renderMath } from "$lib/pgrep/math";
    import type { SessionSynthesis as SessionSynthesisData } from "$lib/pgrep/synthesis";
    import { noDashes } from "$lib/pgrep/text";

    import { pgrepCall } from "../../pgrep/lib/bridge";

    const LETTERS = ["A", "B", "C", "D", "E"];

    interface TutorProblem {
        note_id: number;
        label: string;
        subgoals: number;
    }
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
        parent_stem_html?: string;
    }
    interface McqResult {
        correct: boolean;
        correct_choice?: string;
        explain_why_html?: string;
        needs_explanation?: boolean;
        rationale_html?: string;
    }
    interface ExplainResult {
        ai: string;
        pass: boolean;
        feedback?: string;
        explain_why_html?: string;
    }

    let problems: TutorProblem[] = [];
    let listLoading = true;
    let listError = "";
    let selectedNoteId: number | null = null;
    let roundIndex = 0;

    let aiOn = false;
    let aiBusy = false;

    let tutor: TutorState | null = null;
    let loadingTutor = false;
    let loadError = "";
    let tutorDone = false;

    // Subproblem state, mirroring the Study page's gated flow exactly.
    let spIndex = 0;
    let spSelected = "";
    let spPhase: "mcq" | "explain" | "done" = "mcq";
    let spCorrectKey: string | null = null;
    let spMcqRationale = "";
    let spExplainWhy = "";
    let spExplanation = "";
    let spFeedback = "";
    let spOutcome: "pending" | "pass" | "fail" = "pending";
    let spBusy = false;

    async function loadAi(): Promise<void> {
        try {
            const s = await pgrepCall<{ enabled: boolean }>("pgrepAiStatus", {});
            aiOn = !!s.enabled;
        } catch {
            aiOn = false;
        }
    }

    async function toggleAi(): Promise<void> {
        aiBusy = true;
        try {
            const s = await pgrepCall<{ enabled: boolean }>("pgrepAiSetEnabled", {
                enabled: !aiOn,
            });
            aiOn = !!s.enabled;
        } catch {
            // leave aiOn as-is; the pill still reflects the last known state
        } finally {
            aiBusy = false;
        }
    }

    async function loadList(): Promise<void> {
        listLoading = true;
        listError = "";
        try {
            const r = await pgrepCall<{ problems: TutorProblem[] }>(
                "pgrepTutorList",
                {},
            );
            problems = r.problems ?? [];
            if (problems.length && selectedNoteId === null) {
                selectedNoteId = problems[0].note_id;
            }
        } catch (e) {
            listError = `${e}`;
        } finally {
            listLoading = false;
        }
    }

    let previewSynthesis: SessionSynthesisData | null = null;
    let previewBusy = false;

    // The session-end consolidation on a fixed sample, so it can be tuned without
    // playing a whole session.
    async function previewConsolidation(): Promise<void> {
        previewBusy = true;
        try {
            previewSynthesis = await pgrepCall<SessionSynthesisData>(
                "pgrepTutorSynthesisPreview",
                {},
            );
        } catch {
            previewSynthesis = null;
        } finally {
            previewBusy = false;
        }
    }

    let seedBusy = false;
    let seedMsg = "";

    // Seeds the bundled Problems if the collection has none and refreshes their
    // tutor data from the current bundle, so a stale collection can run the tutor.
    async function seedProblems(): Promise<void> {
        seedBusy = true;
        seedMsg = "Seeding\u2026";
        try {
            const r = await pgrepCall<{
                created: number;
                refreshed: number;
                with_tutor: number;
                total: number;
            }>("pgrepTutorSeed", {});
            seedMsg = `${r.with_tutor} of ${r.total} problems now have tutor data (created ${r.created}, refreshed ${r.refreshed}).`;
            selectedNoteId = null;
            await loadList();
        } catch (e) {
            seedMsg = `Seed failed. ${e}`;
        } finally {
            seedBusy = false;
        }
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

    function startSubproblem(i: number): void {
        spIndex = i;
        resetSubproblemState();
    }

    async function openTutor(): Promise<void> {
        if (selectedNoteId === null) {
            return;
        }
        loadingTutor = true;
        loadError = "";
        tutor = null;
        tutorDone = false;
        try {
            const r = await pgrepCall<TutorState>("pgrepTutorLoad", {
                note_id: selectedNoteId,
                round_index: roundIndex,
            });
            if (!r.count) {
                loadError = "This problem has no usable subproblems.";
                return;
            }
            tutor = r;
            startSubproblem(0);
        } catch (e) {
            loadError = `${e}`;
        } finally {
            loadingTutor = false;
        }
    }

    // Gate 1: the MCQ. A wrong pick returns that distractor's rationale only.
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
                spPhase = r.needs_explanation ? "explain" : "done";
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

    // Gate 2 (AI on only): the lenient "explain why", graded by the real AI.
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

    function selectChoice(key: string): void {
        spSelected = key;
    }

    $: currentSub =
        tutor && tutor.subproblems[spIndex] ? tutor.subproblems[spIndex] : null;
    $: choices = currentSub
        ? currentSub.choices.map((html, i) => ({ key: LETTERS[i], html }))
        : [];
    $: parentStem = tutor?.parent_stem_html
        ? renderMath(noDashes(tutor.parent_stem_html))
        : "";
    $: openLabel = tutor ? "Restart" : "Open tutor";

    onMount(() => {
        void loadAi();
        void loadList();
    });
</script>

<div>
    <header class="head">
        <h1>Tutor harness</h1>
        <p>
            Run the gated decomposition tutor a Problems miss opens, on any problem
            that has decomposition data, without a full session. It calls the same
            backend the Study page does, so with AI on the explanation gate is graded
            live. Dev only, never part of the shipped app.
        </p>
    </header>

    <section class="controls">
        <div class="row">
            <button
                class="pill"
                class:on={aiOn}
                disabled={aiBusy}
                on:click={toggleAi}
                aria-pressed={aiOn}
            >
                <span class="dot" class:on={aiOn}></span>
                AI grading {aiOn ? "on" : "off"}
            </button>

            <label class="field">
                <span>Problem</span>
                <select bind:value={selectedNoteId} disabled={listLoading}>
                    {#each problems as p (p.note_id)}
                        <option value={p.note_id}>
                            {p.label} ({p.subgoals} steps)
                        </option>
                    {/each}
                </select>
            </label>

            <label class="field">
                <span>Variant round</span>
                <select bind:value={roundIndex}>
                    <option value={0}>0 (base numbers)</option>
                    <option value={1}>1</option>
                    <option value={2}>2</option>
                </select>
            </label>

            <button
                class="btn strong"
                disabled={loadingTutor || selectedNoteId === null}
                on:click={openTutor}
            >
                {loadingTutor ? "Opening\u2026" : openLabel}
            </button>

            <button class="btn" disabled={seedBusy} on:click={seedProblems}>
                {seedBusy ? "Seeding\u2026" : "Load / refresh sample problems"}
            </button>

            <button class="btn" disabled={previewBusy} on:click={previewConsolidation}>
                {previewBusy ? "Loading\u2026" : "Preview consolidation"}
            </button>
        </div>

        {#if listLoading}
            <p class="hint">Loading problems with tutor data…</p>
        {:else if listError}
            <p class="error">{listError}</p>
        {:else if problems.length === 0}
            <p class="notice">
                No problems in this collection have decomposition data yet. Click
                "Load / refresh sample problems" to seed the bundled problems and pull
                in their tutor data, then pick one.
            </p>
        {:else}
            <p class="hint">
                {problems.length} problems have decomposition data. Pick one and open the
                tutor to simulate a miss.
            </p>
        {/if}
        {#if seedMsg}
            <p class="hint">{seedMsg}</p>
        {/if}

        {#if !aiOn}
            <p class="notice">
                AI grading is off, so the explanation gate is skipped and only the
                multiple choice gates. Turn AI on to test the full flow (run the app
                with <code>just run-ai</code> so a key is loaded).
            </p>
        {/if}
    </section>

    {#if loadError}
        <p class="error">{loadError}</p>
    {/if}

    {#if previewSynthesis}
        <section class="preview-card">
            <div class="preview-head">
                <span class="preview-tag">Consolidation preview (sample data)</span>
            </div>
            <SessionSynthesis
                synthesis={previewSynthesis}
                onClose={() => (previewSynthesis = null)}
                onDone={() => (previewSynthesis = null)}
            />
        </section>
    {/if}

    {#if tutor}
        {#if parentStem}
            <section class="parent">
                <span class="parent-label">Parent problem (its answer stays hidden)</span>
                <div class="parent-stem">{@html parentStem}</div>
            </section>
        {/if}

        {#if tutorDone}
            <section class="done">
                <div class="done-mark">Tutor complete</div>
                <p>
                    Every subproblem was satisfied. In a real session the missed
                    problem re-enters the rotation and returns later with different
                    numbers. Change the variant round above and restart to see the
                    renumbered version.
                </p>
                <button class="btn strong" on:click={openTutor}>Run again</button>
            </section>
        {:else if currentSub}
            <SubproblemCard
                index={spIndex + 1}
                total={tutor.count}
                prompt={currentSub.prompt}
                stemHtml={currentSub.stem_html}
                {choices}
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
                isLast={spIndex + 1 >= tutor.count}
                onSelect={selectChoice}
                onCheck={checkSubMcq}
                onGrade={gradeSubExplain}
                onContinue={continueSubproblem}
            />
        {/if}
    {/if}
</div>

<style lang="scss">
    .head {
        margin-bottom: var(--space-4);

        h1 {
            margin: 0 0 var(--space-1);
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        p {
            margin: 0;
            max-width: 74ch;
            font-size: var(--text-body);
            line-height: 1.55;
            color: var(--muted);
        }
    }

    .controls {
        margin-bottom: var(--space-3);
    }

    .row {
        display: flex;
        align-items: flex-end;
        gap: var(--space-2);
        flex-wrap: wrap;
    }

    .field {
        display: flex;
        flex-direction: column;
        gap: 4px;
        font-size: var(--text-small);
        color: var(--muted);

        select {
            font: inherit;
            font-size: var(--text-body);
            color: var(--text);
            background: var(--surface);
            border: var(--hairline);
            border-radius: var(--radius-control);
            padding: 8px 10px;
            max-width: 46ch;
        }
    }

    .pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        appearance: none;
        border: var(--hairline);
        background: var(--surface);
        color: var(--muted);
        font: inherit;
        font-size: var(--text-small);
        font-weight: 500;
        padding: 9px 14px;
        border-radius: var(--radius-pill);
        cursor: pointer;
        transition: var(--transition-calm);

        &.on {
            color: var(--text);
            border-color: var(--muted);
        }

        &:disabled {
            cursor: default;
            opacity: 0.6;
        }
    }

    .dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--muted);

        &.on {
            background: var(--success);
        }
    }

    .btn {
        appearance: none;
        border: var(--hairline);
        background: var(--surface);
        color: var(--text);
        font: inherit;
        font-size: var(--text-small);
        font-weight: 500;
        padding: 9px 16px;
        border-radius: var(--radius-control);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover:not(:disabled) {
            background: var(--hover-wash);
            border-color: var(--muted);
        }

        &.strong {
            background: var(--action-bg);
            color: var(--action-fg);
            border-color: transparent;

            &:hover:not(:disabled) {
                background: var(--action-bg-hover);
            }
        }

        &:disabled {
            cursor: default;
            opacity: 0.6;
        }
    }

    .hint {
        margin: var(--space-2) 0 0;
        font-size: var(--text-small);
        color: var(--muted);
    }

    .notice {
        margin: var(--space-2) 0 0;
        font-size: var(--text-small);
        line-height: 1.5;
        color: var(--performance-text);
        border: var(--hairline);
        border-color: var(--performance-tint);
        background: var(--performance-wash);
        border-radius: var(--radius-control);
        padding: 10px 12px;
        max-width: 74ch;
    }

    .error {
        margin: var(--space-2) 0 0;
        font-size: var(--text-small);
        color: var(--error);
    }

    .parent {
        margin-bottom: var(--space-2);
        border: var(--hairline);
        border-radius: var(--radius-card);
        background: var(--surface);
        padding: var(--space-2) var(--space-3);
    }

    .preview-card {
        margin-bottom: var(--space-3);
        border: var(--hairline);
        border-radius: var(--radius-card);
        background: var(--surface);
        box-shadow: var(--shadow-card);
        padding: var(--space-3);
    }

    .preview-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-2);
        margin-bottom: var(--space-2);
    }

    .preview-tag {
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
    }

    .parent-label {
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
    }

    .parent-stem {
        margin-top: 6px;
        font-size: var(--text-body);
        line-height: 1.55;

        :global(p) {
            margin: 0 0 0.5em;
        }
    }

    .done {
        border: var(--hairline);
        border-color: var(--success);
        background: var(--success-wash);
        border-radius: var(--radius-card);
        padding: var(--space-3);

        .done-mark {
            font-size: var(--text-emphasis);
            font-weight: 600;
        }

        p {
            margin: 8px 0 var(--space-2);
            font-size: var(--text-body);
            line-height: 1.55;
            color: var(--muted);
            max-width: 74ch;
        }
    }

    code {
        font-family: var(--font-mono);
        font-size: 0.92em;
        padding: 1px 6px;
        border-radius: var(--radius-control);
        background: var(--elevated);
    }
</style>
