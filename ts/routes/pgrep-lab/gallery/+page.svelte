<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- pgrep component gallery. A durable review surface that shows every pgrep
     primitive in its key states without running a study session. Each demo
     renders in light and dark side by side, so a reviewer can inspect both
     themes at once. Everything is a read-only consumer of the real components
     with clearly synthetic sample data. The manifold keeps its own richer lab,
     linked from the top nav. -->
<script lang="ts">
    import ChoiceList from "$lib/components/ChoiceList.svelte";
    import CoverageBar from "$lib/components/CoverageBar.svelte";
    import GradeBar from "$lib/components/GradeBar.svelte";
    import HintRung from "$lib/components/HintRung.svelte";
    import Manifold from "$lib/components/Manifold.svelte";
    import NavRail from "$lib/components/NavRail.svelte";
    import ReliabilityDiagram from "$lib/components/ReliabilityDiagram.svelte";
    import ScoreCard from "$lib/components/ScoreCard.svelte";
    import StudyFrame from "$lib/components/StudyFrame.svelte";
    import { FULL_SURFACE } from "$lib/pgrep/manifold";

    type Hue = "memory" | "performance" | "readiness";

    // Each demo is rendered once per theme so both are visible together. The
    // token system keys dark off .pgrep.night-mode, so a nested pane flips the
    // whole subtree with no page reload.
    const THEMES: { id: string; label: string; cls: string }[] = [
        { id: "light", label: "Light", cls: "" },
        { id: "dark", label: "Dark", cls: "night-mode" },
    ];

    const TOC: { id: string; label: string }[] = [
        { id: "score-card", label: "Score card" },
        { id: "choice-list", label: "Choice list" },
        { id: "hint-rung", label: "Hint rung" },
        { id: "grade-bar", label: "Grade bar" },
        { id: "coverage-bar", label: "Coverage bar" },
        { id: "reliability", label: "Reliability diagram" },
        { id: "calibration-panel", label: "Calibration panel" },
        { id: "study-frame", label: "Study frame" },
        { id: "exam", label: "Exam" },
        { id: "nav-rail", label: "Nav rail" },
        { id: "manifold", label: "Manifold" },
    ];

    // ScoreCard: full honesty anatomy for each of the three reserved hues.
    const scoreCards: {
        kind: Hue;
        value: number;
        range: [number, number];
        howSure: string;
        updated: string;
        sparkline: number[];
    }[] = [
        {
            kind: "memory",
            value: 74,
            range: [68, 79],
            howSure: "Fairly sure",
            updated: "Updated 2h ago",
            sparkline: [0.3, 0.42, 0.38, 0.5, 0.55, 0.64, 0.72],
        },
        {
            kind: "performance",
            value: 63,
            range: [57, 70],
            howSure: "Still forming",
            updated: "Updated 1h ago",
            sparkline: [0.5, 0.46, 0.52, 0.58, 0.55, 0.6, 0.66],
        },
        {
            kind: "readiness",
            value: 69,
            range: [61, 76],
            howSure: "Fairly sure",
            updated: "Updated 2h ago",
            sparkline: [0.4, 0.45, 0.5, 0.52, 0.6, 0.64, 0.69],
        },
    ];

    // ScoreCard: the abstain state for each hue. Data is thin, so the card names
    // what is missing rather than showing a bare number.
    const abstainCards: {
        kind: Hue;
        abstain: { missing: string; linkLabel: string; linkHref: string };
    }[] = [
        {
            kind: "memory",
            abstain: {
                missing:
                    "Only a handful of cards reviewed so far. Review a few more to size Memory.",
                linkLabel: "See what is missing",
                linkHref: "/pgrep/study",
            },
        },
        {
            kind: "performance",
            abstain: {
                missing:
                    "Only two problems attempted so far. Attempt a few more to size Performance.",
                linkLabel: "See what is missing",
                linkHref: "/pgrep/progress",
            },
        },
        {
            kind: "readiness",
            abstain: {
                missing:
                    "Coverage sits below the line. Cover Quantum Mechanics and Laboratory Methods to unlock Readiness.",
                linkLabel: "See coverage",
                linkHref: "/pgrep/progress",
            },
        },
    ];

    // ChoiceList: one problem, three states. Doubling the speed of a
    // nonrelativistic particle raises kinetic energy fourfold, so D is correct.
    const choices: { key: string; html: string }[] = [
        { key: "A", html: "It is unchanged" },
        { key: "B", html: "It doubles" },
        { key: "C", html: "It triples" },
        { key: "D", html: "It quadruples" },
        { key: "E", html: "It falls by half" },
    ];

    // GradeBar: the four FSRS grades with their next intervals.
    const grades: { label: string; value: number; interval: string }[] = [
        { label: "Again", value: 1, interval: "Under 1 min" },
        { label: "Hard", value: 2, interval: "About 8 min" },
        { label: "Good", value: 3, interval: "4 days" },
        { label: "Easy", value: 4, interval: "9 days" },
    ];

    // CoverageBar: nine PGRE units weighted by blueprint share. This set dips
    // below the line, so Readiness abstains.
    const coverageBelow: { topic: string; weight: number; covered: number }[] = [
        { topic: "Classical Mechanics", weight: 0.2, covered: 0.92 },
        { topic: "Electromagnetism", weight: 0.18, covered: 0.85 },
        { topic: "Quantum Mechanics", weight: 0.13, covered: 0.18 },
        { topic: "Thermo & Stat Mech", weight: 0.1, covered: 0.8 },
        { topic: "Atomic Physics", weight: 0.1, covered: 0.6 },
        { topic: "Optics & Waves", weight: 0.08, covered: 0.7 },
        { topic: "Specialized Topics", weight: 0.09, covered: 0.5 },
        { topic: "Special Relativity", weight: 0.06, covered: 0.7 },
        { topic: "Laboratory Methods", weight: 0.06, covered: 0.2 },
    ];

    // CoverageBar: the same nine units once coverage clears the line.
    const coverageHealthy: { topic: string; weight: number; covered: number }[] = [
        { topic: "Classical Mechanics", weight: 0.2, covered: 0.98 },
        { topic: "Electromagnetism", weight: 0.18, covered: 0.95 },
        { topic: "Quantum Mechanics", weight: 0.13, covered: 0.82 },
        { topic: "Thermo & Stat Mech", weight: 0.1, covered: 0.9 },
        { topic: "Atomic Physics", weight: 0.1, covered: 0.85 },
        { topic: "Optics & Waves", weight: 0.08, covered: 0.88 },
        { topic: "Specialized Topics", weight: 0.09, covered: 0.8 },
        { topic: "Special Relativity", weight: 0.06, covered: 0.9 },
        { topic: "Laboratory Methods", weight: 0.06, covered: 0.76 },
    ];

    // ReliabilityDiagram: a well-calibrated Performance read, an underconfident
    // Memory read, and the empty frame when nothing is graded yet.
    const relPerformance: { p: number; o: number }[] = [
        { p: 0.1, o: 0.09 },
        { p: 0.3, o: 0.31 },
        { p: 0.5, o: 0.48 },
        { p: 0.7, o: 0.69 },
        { p: 0.9, o: 0.9 },
    ];
    const relMemory: { p: number; o: number }[] = [
        { p: 0.1, o: 0.2 },
        { p: 0.3, o: 0.44 },
        { p: 0.5, o: 0.63 },
        { p: 0.7, o: 0.82 },
        { p: 0.9, o: 0.95 },
    ];

    // Calibration panel (Progress, L5.5): the wired pair the surface renders from
    // the embedded offline evidence. These points/Brier mirror
    // anki.pgrep.calibration_evidence (aggregate statistics, safe to show), so a
    // reviewer sees the real curves without a backend. Memory is the default FSRS
    // curve (slightly overconfident); Performance is the held-out synthetic run.
    const calibMemory: { p: number; o: number }[] = [
        { p: 0.554, o: 0.31 },
        { p: 0.682, o: 0.545 },
        { p: 0.748, o: 0.597 },
        { p: 0.803, o: 0.708 },
        { p: 0.838, o: 0.765 },
        { p: 0.865, o: 0.755 },
        { p: 0.888, o: 0.756 },
        { p: 0.911, o: 0.779 },
        { p: 0.939, o: 0.739 },
        { p: 0.98, o: 0.668 },
    ];
    const calibMemoryBrier = 0.234;
    const calibPerformance: { p: number; o: number }[] = [
        { p: 0.42, o: 0.313 },
        { p: 0.642, o: 0.75 },
        { p: 0.755, o: 0.625 },
        { p: 0.818, o: 0.75 },
        { p: 0.863, o: 0.813 },
        { p: 0.89, o: 0.938 },
        { p: 0.918, o: 0.938 },
        { p: 0.933, o: 0.75 },
        { p: 0.946, o: 0.688 },
        { p: 0.96, o: 0.875 },
    ];
    const calibPerformanceBrier = 0.175;

    // Readiness on the Progress surface: the honest abstain at n=1 (empty attempt
    // log, coverage below the gate, so the exam is named) and, for contrast, a
    // covered read with a point and an 80% range.
    const readinessUncovered =
        "Cover Mechanics, Electromagnetism, Quantum, Thermodynamics, Atomic physics, Optics and waves, Special relativity, Lab methods, Specialized to unlock Readiness.";

    // StudyFrame: a compact problem stem for the Problems door preview.
    const frameChoices: { key: string; html: string }[] = [
        { key: "A", html: "A traveling wave whose speed grows with the tension" },
        { key: "B", html: "A standing wave with a node at each fixed end" },
        { key: "C", html: "A damped oscillation that decays within one period" },
    ];

    // Exam: the question navigator, mid-run. Each cell is answered, flagged, or the
    // current question. Mirrors the states the exam surface tracks per index.
    const examCells: {
        n: number;
        answered: boolean;
        flagged: boolean;
        current: boolean;
    }[] = [
        { n: 1, answered: true, flagged: false, current: false },
        { n: 2, answered: true, flagged: false, current: false },
        { n: 3, answered: true, flagged: true, current: false },
        { n: 4, answered: true, flagged: false, current: false },
        { n: 5, answered: false, flagged: false, current: true },
        { n: 6, answered: false, flagged: true, current: false },
        { n: 7, answered: false, flagged: false, current: false },
        { n: 8, answered: true, flagged: false, current: false },
        { n: 9, answered: false, flagged: false, current: false },
        { n: 10, answered: false, flagged: false, current: false },
    ];

    // Exam result: the readiness ScoreCard reused at the end of a mock, either a
    // covered scaled score with its likely range or an honest abstain that names
    // the uncovered topics.
    const examAbstain = {
        message: "Not enough of the exam is covered yet",
        missing:
            "Cover Quantum Mechanics and Laboratory Methods to project a readiness score.",
    };

    function noop(): void {
        // Read-only gallery. Interactions are shown as fixed snapshots.
    }
</script>

<div>
    <header class="head">
        <h1>Component gallery</h1>
        <p>
            Every pgrep primitive in its key states, so a reviewer can inspect the
            system without running a study session. Each demo renders in light and dark
            together. The data is synthetic but realistic, and the reserved hues stay
            data only, amber for Memory, blue for Performance, lilac for Readiness.
        </p>
    </header>

    <div class="layout">
        <aside class="toc" aria-label="Sections">
            <span class="toc-title">On this page</span>
            <ul>
                {#each TOC as item (item.id)}
                    <li><a href="#{item.id}">{item.label}</a></li>
                {/each}
            </ul>
        </aside>

        <main class="content">
            <!-- Score card -->
            <section id="score-card" class="section">
                <div class="section-head">
                    <h2>Score card</h2>
                    <p>
                        The full honesty anatomy, a point number in tabular figures, a
                        likely range, a how sure read, and a last updated line. The hue
                        touches only the glyph and the sparkline. The second row shows
                        the abstain state, which names what is missing instead of
                        guessing a number.
                    </p>
                </div>
                <div class="split">
                    {#each THEMES as t (t.id)}
                        <div class="pane pgrep {t.cls}">
                            <span class="pane-label">{t.label}</span>
                            <div class="stage">
                                <span class="state-label">
                                    Full anatomy, all three hues
                                </span>
                                <div class="card-row">
                                    {#each scoreCards as c (c.kind)}
                                        <ScoreCard
                                            kind={c.kind}
                                            value={c.value}
                                            range={c.range}
                                            howSure={c.howSure}
                                            updated={c.updated}
                                            sparkline={c.sparkline}
                                        />
                                    {/each}
                                </div>
                                <span class="state-label">
                                    Abstain, not enough evidence yet
                                </span>
                                <div class="card-row">
                                    {#each abstainCards as c (c.kind)}
                                        <ScoreCard kind={c.kind} abstain={c.abstain} />
                                    {/each}
                                </div>
                            </div>
                        </div>
                    {/each}
                </div>
            </section>

            <!-- Choice list -->
            <section id="choice-list" class="section">
                <div class="section-head">
                    <h2>Choice list</h2>
                    <p>
                        Five choices, monochrome by default. A live selection takes a
                        thin blue outline and a faint wash. After commit the row locks,
                        the correct choice takes a calm success outline and a wrong
                        commit dims and wears a blue tag. Nothing turns red during
                        learning.
                    </p>
                </div>
                <div class="split">
                    {#each THEMES as t (t.id)}
                        <div class="pane pgrep {t.cls}">
                            <span class="pane-label">{t.label}</span>
                            <div class="stage">
                                <p class="stem">
                                    If the speed of a nonrelativistic particle doubles,
                                    how does its kinetic energy change?
                                </p>
                                <span class="state-label">Default</span>
                                <ChoiceList {choices} selected="" committed={false} />
                                <span class="state-label">Selected, before commit</span>
                                <ChoiceList {choices} selected="B" committed={false} />
                                <span class="state-label">Committed, not correct</span>
                                <ChoiceList
                                    {choices}
                                    selected="B"
                                    committed={true}
                                    correctKey="D"
                                />
                            </div>
                        </div>
                    {/each}
                </div>
            </section>

            <!-- Hint rung -->
            <section id="hint-rung" class="section">
                <div class="section-head">
                    <h2>Hint rung</h2>
                    <p>
                        One calm step of the wrong-answer ladder. A hint budget shows
                        how far you are along, the prompt asks for a sub-goal, and the
                        step reveals only itself. The final answer never appears here,
                        so the rung stays giveaway safe.
                    </p>
                </div>
                <div class="split">
                    {#each THEMES as t (t.id)}
                        <div class="pane pgrep {t.cls}">
                            <span class="pane-label">{t.label}</span>
                            <div class="stage stack">
                                <span class="state-label">
                                    Budget shown, step still hidden
                                </span>
                                <HintRung
                                    title="Break it down"
                                    index={2}
                                    total={3}
                                    prompt="Before plugging in numbers, name the principle that fixes the speed at the bottom of the ramp."
                                    revealHtml="Mechanical energy is conserved because the ramp is frictionless. Equate the potential energy at the top with the kinetic energy at the bottom, then isolate the speed."
                                    shown={false}
                                    onShow={noop}
                                />
                                <span class="state-label">
                                    Step revealed, answer still withheld
                                </span>
                                <HintRung
                                    title="Break it down"
                                    index={2}
                                    total={3}
                                    prompt="Before plugging in numbers, name the principle that fixes the speed at the bottom of the ramp."
                                    revealHtml="Mechanical energy is conserved because the ramp is frictionless. Equate the potential energy at the top with the kinetic energy at the bottom, then isolate the speed."
                                    shown={true}
                                    onShow={noop}
                                />
                            </div>
                        </div>
                    {/each}
                </div>
            </section>

            <!-- Grade bar -->
            <section id="grade-bar" class="section">
                <div class="section-head">
                    <h2>Grade bar</h2>
                    <p>
                        The four FSRS grades for the Cards door, equal and monochrome,
                        each carrying its next interval underneath. The top row hides
                        intervals for the moment before reveal, the bottom row shows
                        them.
                    </p>
                </div>
                <div class="split">
                    {#each THEMES as t (t.id)}
                        <div class="pane pgrep {t.cls}">
                            <span class="pane-label">{t.label}</span>
                            <div class="stage stack">
                                <span class="state-label">Intervals shown</span>
                                <GradeBar
                                    {grades}
                                    showIntervals={true}
                                    onGrade={noop}
                                />
                                <span class="state-label">Intervals hidden</span>
                                <GradeBar
                                    {grades}
                                    showIntervals={false}
                                    onGrade={noop}
                                />
                            </div>
                        </div>
                    {/each}
                </div>
            </section>

            <!-- Coverage bar -->
            <section id="coverage-bar" class="section">
                <div class="section-head">
                    <h2>Coverage bar</h2>
                    <p>
                        One segment per topic, width by blueprint weight, fill by how
                        covered that topic is. Coverage gates Readiness, so the note
                        states the rule plainly. The first bar clears the line, the
                        second dips below it and abstains.
                    </p>
                </div>
                <div class="split">
                    {#each THEMES as t (t.id)}
                        <div class="pane pgrep {t.cls}">
                            <span class="pane-label">{t.label}</span>
                            <div class="stage stack">
                                <span class="state-label">Above the line</span>
                                <CoverageBar
                                    segments={coverageHealthy}
                                    threshold={70}
                                    note="Coverage clears the line, so Readiness reports a number."
                                />
                                <span class="state-label">
                                    Below the line, Readiness abstains
                                </span>
                                <CoverageBar
                                    segments={coverageBelow}
                                    threshold={70}
                                    note="Two units sit below the line. Readiness abstains until Quantum Mechanics and Laboratory Methods are covered."
                                />
                            </div>
                        </div>
                    {/each}
                </div>
            </section>

            <!-- Reliability diagram -->
            <section id="reliability" class="section">
                <div class="section-head">
                    <h2>Reliability diagram</h2>
                    <p>
                        Predicted probability against observed accuracy, with the
                        perfect-calibration diagonal and a Brier score. With no graded
                        predictions it draws the empty frame and abstains rather than
                        inventing a curve.
                    </p>
                </div>
                <div class="split">
                    {#each THEMES as t (t.id)}
                        <div class="pane pgrep {t.cls}">
                            <span class="pane-label">{t.label}</span>
                            <div class="stage">
                                <div class="rel-row">
                                    <div class="rel-cell">
                                        <span class="state-label">
                                            Performance, well calibrated
                                        </span>
                                        <ReliabilityDiagram
                                            points={relPerformance}
                                            brier={0.11}
                                            read="Well calibrated"
                                            tone="performance"
                                            size={200}
                                        />
                                    </div>
                                    <div class="rel-cell">
                                        <span class="state-label">
                                            Memory, underconfident
                                        </span>
                                        <ReliabilityDiagram
                                            points={relMemory}
                                            brier={0.17}
                                            read="Slightly underconfident"
                                            tone="memory"
                                            size={200}
                                        />
                                    </div>
                                    <div class="rel-cell">
                                        <span class="state-label">
                                            Abstain, nothing graded yet
                                        </span>
                                        <ReliabilityDiagram
                                            points={[]}
                                            brier={null}
                                            read="Not enough graded predictions yet"
                                            tone="performance"
                                            size={200}
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>
                    {/each}
                </div>
            </section>

            <!-- Calibration panel -->
            <section id="calibration-panel" class="section">
                <div class="section-head">
                    <h2>Calibration panel</h2>
                    <p>
                        The wired Progress surface (L5.5). Readiness is coverage gated,
                        shown both abstaining at n equals one (naming the uncovered
                        exam) and covered with a point and an 80 percent range.
                        Calibration shows each model layer with its evidence, a
                        reliability diagram plus Brier and provenance for Memory and for
                        Performance, from the embedded offline runs. A failed fetch
                        reads as unavailable, kept distinct from a genuine absence of
                        evidence. The reserved hues stay data only, amber for Memory,
                        blue for Performance, lilac for Readiness.
                    </p>
                </div>
                <div class="split">
                    {#each THEMES as t (t.id)}
                        <div class="pane pgrep {t.cls}">
                            <span class="pane-label">{t.label}</span>
                            <div class="stage stack">
                                <span class="state-label">
                                    Readiness, abstain at n = 1
                                </span>
                                <ScoreCard
                                    kind="readiness"
                                    abstain={{
                                        message:
                                            "Not enough of the exam is covered yet",
                                        missing: readinessUncovered,
                                    }}
                                />
                                <span class="state-label">
                                    Readiness, covered with a range
                                </span>
                                <ScoreCard
                                    kind="readiness"
                                    value={620}
                                    range={[590, 660]}
                                    howSure="74 percent covered"
                                    updated=""
                                />
                                <span class="state-label">
                                    Calibration evidence, Memory and Performance
                                </span>
                                <div class="rel-row">
                                    <div class="rel-cell">
                                        <span
                                            class="calib-tone"
                                            style="color: var(--memory-text);"
                                        >
                                            Memory
                                        </span>
                                        <ReliabilityDiagram
                                            points={calibMemory}
                                            brier={calibMemoryBrier}
                                            read="Held-out reviews"
                                            tone="memory"
                                            size={200}
                                        />
                                        <p class="calib-caption">
                                            Validated on held-out reviews. Default FSRS,
                                            slightly overconfident.
                                        </p>
                                        <p class="calib-meta">n 7,503 · 2026-07-05</p>
                                        <p
                                            class="calib-prov"
                                            title="Default FSRS-6 (fsrs-rs 5.2.0) retrievability vs recall; binning-free Brier"
                                        >
                                            Held-out reviews from the anki-revlogs-10k
                                            sample (4 users, time-split)
                                        </p>
                                    </div>
                                    <div class="rel-cell">
                                        <span
                                            class="calib-tone"
                                            style="color: var(--performance-text);"
                                        >
                                            Performance
                                        </span>
                                        <ReliabilityDiagram
                                            points={calibPerformance}
                                            brier={calibPerformanceBrier}
                                            read="Held-out synthetic"
                                            tone="performance"
                                            size={200}
                                        />
                                        <p class="calib-caption">
                                            Methodology validated on held-out synthetic
                                            (n = 1 cohort).
                                        </p>
                                        <p class="calib-meta">n 160 · 2026-07-05</p>
                                        <p
                                            class="calib-prov"
                                            title="PFA logistic + beta calibration on a held-out split; binning-free Brier"
                                        >
                                            Held-out synthetic exam-style outcomes
                                            (pipeline validation)
                                        </p>
                                    </div>
                                </div>
                                <span class="state-label">
                                    Calibration unavailable, fetch failed
                                </span>
                                <div class="rel-row">
                                    <div class="rel-cell">
                                        <span
                                            class="calib-tone"
                                            style="color: var(--memory-text);"
                                        >
                                            Memory
                                        </span>
                                        <ReliabilityDiagram
                                            points={[]}
                                            brier={null}
                                            read="Calibration unavailable"
                                            tone="memory"
                                            size={200}
                                        />
                                        <p class="calib-caption">
                                            Calibration could not be loaded right now.
                                            Reload to try again.
                                        </p>
                                    </div>
                                    <div class="rel-cell">
                                        <span
                                            class="calib-tone"
                                            style="color: var(--performance-text);"
                                        >
                                            Performance
                                        </span>
                                        <ReliabilityDiagram
                                            points={[]}
                                            brier={null}
                                            read="Calibration unavailable"
                                            tone="performance"
                                            size={200}
                                        />
                                        <p class="calib-caption">
                                            Calibration could not be loaded right now.
                                            Reload to try again.
                                        </p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    {/each}
                </div>
            </section>

            <!-- Study frame -->
            <section id="study-frame" class="section">
                <div class="section-head">
                    <h2>Study frame</h2>
                    <p>
                        The minimal session chrome, a mono progress count, a topic chip
                        toned to the door, and a close control over a single focused
                        column. The previews are clipped to their chrome. The Problems
                        door tones blue, the Cards door tones amber.
                    </p>
                </div>
                <div class="split">
                    {#each THEMES as t (t.id)}
                        <div class="pane pgrep {t.cls}">
                            <span class="pane-label">{t.label}</span>
                            <div class="stage stack">
                                <span class="state-label">
                                    Problems door, performance tone
                                </span>
                                <div class="frame-preview">
                                    <StudyFrame
                                        count="Problem 3 of 12"
                                        topic="Electromagnetism"
                                        topicTone="performance"
                                        columnWidth={520}
                                        onClose={noop}
                                    >
                                        <p class="stem">
                                            A string fixed at both ends is driven at its
                                            second harmonic. Which pattern describes the
                                            steady displacement?
                                        </p>
                                        <ChoiceList
                                            choices={frameChoices}
                                            selected="B"
                                            committed={false}
                                        />
                                    </StudyFrame>
                                </div>
                                <span class="state-label">Cards door, memory tone</span>
                                <div class="frame-preview">
                                    <StudyFrame
                                        count="Card 5 of 20"
                                        topic="Quantum Mechanics"
                                        topicTone="memory"
                                        columnWidth={520}
                                        onClose={noop}
                                    >
                                        <p class="stem">
                                            State the selection rule for an electric
                                            dipole transition in hydrogen.
                                        </p>
                                        <button
                                            type="button"
                                            class="demo-btn primary"
                                            on:click={noop}
                                        >
                                            Show answer
                                        </button>
                                    </StudyFrame>
                                </div>
                            </div>
                        </div>
                    {/each}
                </div>
            </section>

            <!-- Exam -->
            <section id="exam" class="section">
                <div class="section-head">
                    <h2>Exam</h2>
                    <p>
                        The end-of-exam read reuses the readiness ScoreCard, either a
                        covered scaled score with its likely range or an honest abstain
                        that names the uncovered topics. The question navigator marks
                        each question as answered, flagged, or current, so a reviewer
                        can read the running state without sitting a timed mock.
                    </p>
                </div>
                <div class="split">
                    {#each THEMES as t (t.id)}
                        <div class="pane pgrep {t.cls}">
                            <span class="pane-label">{t.label}</span>
                            <div class="stage stack">
                                <span class="state-label">Question navigator</span>
                                <div class="navigator">
                                    {#each examCells as cell (cell.n)}
                                        <div
                                            class="nav-cell"
                                            class:answered={cell.answered}
                                            class:current={cell.current}
                                        >
                                            {cell.n}
                                            {#if cell.flagged}<span
                                                    class="nav-cell-flag"
                                                    aria-hidden="true"
                                                ></span>{/if}
                                        </div>
                                    {/each}
                                </div>
                                <div class="nav-legend">
                                    <span class="leg">
                                        <span class="leg-swatch answered"></span>
                                        Answered
                                    </span>
                                    <span class="leg">
                                        <span class="leg-swatch flag"></span>
                                        Flagged
                                    </span>
                                    <span class="leg">
                                        <span class="leg-swatch current"></span>
                                        Current
                                    </span>
                                </div>
                                <span class="state-label">
                                    Result, covered with a range
                                </span>
                                <ScoreCard
                                    kind="readiness"
                                    value={640}
                                    range={[610, 670]}
                                    howSure="76 percent covered"
                                    updated=""
                                />
                                <span class="state-label">
                                    Result, abstain until covered
                                </span>
                                <ScoreCard kind="readiness" abstain={examAbstain} />
                            </div>
                        </div>
                    {/each}
                </div>
            </section>

            <!-- Nav rail -->
            <section id="nav-rail" class="section">
                <div class="section-head">
                    <h2>Nav rail</h2>
                    <p>
                        The quiet left rail. It carries the nested-contour logo glyph,
                        the four calm destinations with the active one on a surface
                        chip, and an optional streak footer. Monochrome throughout, so
                        no score hue leaks into the chrome.
                    </p>
                </div>
                <div class="split">
                    {#each THEMES as t (t.id)}
                        <div class="pane pgrep {t.cls}">
                            <span class="pane-label">{t.label}</span>
                            <div class="stage">
                                <div class="rail-preview">
                                    <NavRail active="Study" streak={12} />
                                    <NavRail active="Home" />
                                    <div class="rail-main">
                                        Left carries an opt-in streak. Right is the
                                        honest default with none.
                                    </div>
                                </div>
                            </div>
                        </div>
                    {/each}
                </div>
            </section>

            <!-- Manifold -->
            <section id="manifold" class="section">
                <div class="section-head">
                    <h2>Manifold</h2>
                    <p>
                        The one piece of imagery, a data-driven wireframe surface.
                        Height is Performance, hue is the leading score, holes are
                        coverage gaps, footprint is blueprint weight. The thumbnail
                        follows the app theme. The manifold lab reshapes it live in 3D
                        or the 2D fallback.
                    </p>
                </div>
                <div class="pane manifold-pane">
                    <div class="stage">
                        <div class="manifold-thumb">
                            <Manifold
                                width={420}
                                height={260}
                                scale={104}
                                grid={62}
                                surface={FULL_SURFACE}
                                showLabels={false}
                            />
                        </div>
                        <a class="manifold-link" href="/pgrep-lab">
                            Open the manifold lab
                        </a>
                    </div>
                </div>
            </section>
        </main>
    </div>
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
            max-width: 78ch;
            font-size: var(--text-body);
            line-height: 1.55;
            color: var(--muted);
        }
    }

    .layout {
        display: grid;
        grid-template-columns: 176px minmax(0, 1fr);
        gap: var(--space-4);
        align-items: start;
    }

    .toc {
        position: sticky;
        top: var(--space-2);
        display: flex;
        flex-direction: column;
        gap: var(--space-1);

        .toc-title {
            font-size: var(--text-caption);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--muted);
        }

        ul {
            list-style: none;
            margin: 0;
            padding: 0;
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        a {
            display: block;
            padding: 6px 10px;
            border-radius: var(--radius-control);
            font-size: var(--text-body);
            color: var(--muted);
            text-decoration: none;
            transition: var(--transition-calm);

            &:hover {
                color: var(--text);
                background: var(--hover-wash);
            }
        }
    }

    .content {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
        min-width: 0;
    }

    .section {
        scroll-margin-top: var(--space-3);
    }

    .section-head {
        margin-bottom: var(--space-2);

        h2 {
            margin: 0 0 var(--space-0);
            font-size: var(--text-emphasis);
            font-weight: 600;
            letter-spacing: -0.01em;
        }

        p {
            margin: 0;
            max-width: 76ch;
            font-size: var(--text-body);
            line-height: 1.55;
            color: var(--muted);
        }
    }

    .split {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: var(--space-2);
    }

    .pane {
        position: relative;
        border: var(--hairline);
        border-radius: var(--radius-card);
        padding: var(--space-3) var(--space-2) var(--space-2);
        background: var(--canvas);
        min-width: 0;
        overflow: hidden;
    }

    .pane-label {
        position: absolute;
        top: 10px;
        right: 14px;
        font-size: var(--text-caption);
        font-weight: 500;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--muted);
    }

    .stage {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);

        &.stack {
            gap: var(--space-2);
        }
    }

    .state-label {
        font-size: var(--text-caption);
        font-weight: 500;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--muted);
        margin-top: var(--space-0);
    }

    .card-row {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
        gap: var(--space-1);
    }

    .stem {
        margin: 0;
        font-size: var(--text-body);
        line-height: 1.55;
        color: var(--text);
    }

    .rel-row {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        gap: var(--space-2);
    }

    .rel-cell {
        display: flex;
        flex-direction: column;
        gap: var(--space-0);
    }

    .calib-tone {
        font-size: var(--text-small);
        font-weight: 600;
    }

    .calib-caption {
        margin: var(--space-0) 0 0;
        font-size: var(--text-small);
        line-height: 1.5;
        color: var(--muted);
    }

    .calib-meta {
        margin: 2px 0 0;
        font-size: var(--text-caption);
        color: var(--muted);
        font-variant-numeric: tabular-nums;
    }

    .calib-prov {
        margin: 2px 0 0;
        font-size: var(--text-caption);
        line-height: 1.45;
        color: var(--muted);
        cursor: help;
    }

    /* Exam navigator, mirroring the cells the exam surface renders per question. */
    .navigator {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        padding: var(--space-1) 0;
        border-top: var(--hairline);
        border-bottom: var(--hairline);
    }

    .nav-cell {
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

    .nav-cell-flag {
        position: absolute;
        top: 3px;
        right: 3px;
        width: 5px;
        height: 5px;
        border-radius: var(--radius-pill);
        background: var(--caution);
    }

    .nav-legend {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-2);
        font-size: var(--text-caption);
        color: var(--muted);
    }

    .leg {
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }

    .leg-swatch {
        position: relative;
        width: 16px;
        height: 16px;
        border: var(--hairline);
        border-radius: 5px;
        background: var(--surface);

        &.answered {
            border-color: var(--performance-tint);
            background: var(--performance-wash);
        }

        &.current {
            border-color: var(--text);
            border-width: 1.5px;
        }

        &.flag::after {
            content: "";
            position: absolute;
            top: 2px;
            right: 2px;
            width: 4px;
            height: 4px;
            border-radius: var(--radius-pill);
            background: var(--caution);
        }
    }

    .frame-preview {
        height: 340px;
        overflow: hidden;
        border: var(--hairline);
        border-radius: var(--radius-card);
    }

    .rail-preview {
        display: flex;
        height: 440px;
        overflow: hidden;
        border: var(--hairline);
        border-radius: var(--radius-card);
    }

    .rail-main {
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: var(--text-small);
        color: var(--muted);
    }

    .manifold-pane {
        max-width: 520px;
    }

    .manifold-thumb {
        display: flex;
        justify-content: center;
        overflow: hidden;
    }

    .manifold-link {
        align-self: flex-start;
        margin-top: var(--space-1);
        font-size: var(--text-body);
        color: var(--text);
        text-decoration: underline;
        text-underline-offset: 3px;
    }

    .demo-btn {
        align-self: flex-start;
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

        &.primary {
            background: var(--action-bg);
            color: var(--action-fg);
            border-color: transparent;
        }
    }

    @media (max-width: 1000px) {
        .layout {
            grid-template-columns: minmax(0, 1fr);
        }

        .toc {
            position: static;
            flex-direction: row;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--space-1);
        }

        .toc ul {
            flex-direction: row;
            flex-wrap: wrap;
        }
    }

    @media (max-width: 720px) {
        .split {
            grid-template-columns: minmax(0, 1fr);
        }
    }
</style>
