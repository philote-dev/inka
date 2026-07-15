<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Calibration walkthrough demo (review playground). A self-contained prototype
     of the redesigned calibration flow on synthetic data, so the whole arc can be
     watched end to end without a backend or a running collection. It restores the
     per-subtopic granularity (the 20 blueprint topic tags, each with its real ETS
     focus line from docs_pgrep/ai/blueprint.md), authors one card per subtopic on
     each "Author & next", tracks coverage across the nine categories, and on
     completion deals in the real CardWheel (the Library card sets). "Auto-play"
     runs it hands-free; "Fill all" fast-forwards to the payoff. No bridge calls;
     the card fronts/backs are clearly synthetic sample text. This is a design
     companion for the calibration redesign, not the shipped surface. -->
<script lang="ts">
    import { onDestroy } from "svelte";
    import { fly } from "svelte/transition";

    import CardWheel from "$lib/components/CardWheel.svelte";
    import { renderMath } from "$lib/pgrep/math";

    interface Topic {
        category: string;
        tag: string;
        label: string;
        // The real ETS content line for this finest unit (blueprint.md §3): the
        // "what to focus on" guidance the redesign surfaces per subtopic.
        focus: string;
        front: string;
        back: string;
        // Mock diagnostic: a rusty category asks for extra authoring here.
        rusty?: boolean;
    }

    const CATEGORY_ORDER = [
        "mechanics",
        "electromagnetism",
        "quantum",
        "thermodynamics",
        "atomic",
        "optics_waves",
        "special_relativity",
        "lab",
        "specialized",
    ] as const;

    const CATEGORY_NAMES: Record<string, string> = {
        mechanics: "Classical Mechanics",
        electromagnetism: "Electromagnetism",
        quantum: "Quantum Mechanics",
        thermodynamics: "Thermo & Stat Mech",
        atomic: "Atomic Physics",
        optics_waves: "Optics & Waves",
        special_relativity: "Special Relativity",
        lab: "Laboratory Methods",
        specialized: "Specialized Topics",
    };

    // The 20 distinct blueprint topic tags, in blueprint order (docs_pgrep/ai/
    // slugs.md): 14 big-three subtopics plus the 6 small categories. Each carries
    // its real ETS focus line and a synthetic sample card the demo authors for it.
    const TOPICS: Topic[] = [
        {
            category: "mechanics",
            tag: "topic::mechanics::dynamics_energy",
            label: "Newtonian dynamics, work and energy",
            focus: "kinematics, Newton's laws, work-energy theorem, systems of particles",
            front: "State the work-energy theorem and say when it holds.",
            back: "The net work on a body equals its change in kinetic energy, \\(W_{\\text{net}} = \\Delta K\\). It holds for any force, conservative or not.",
        },
        {
            category: "mechanics",
            tag: "topic::mechanics::oscillations",
            label: "Oscillations",
            focus: "simple, damped, and driven harmonic motion, resonance",
            front: "What sets the frequency of small oscillations about a potential minimum?",
            back: "The curvature at the minimum: \\(\\omega = \\sqrt{V''(x_0)/m}\\).",
        },
        {
            category: "mechanics",
            tag: "topic::mechanics::rotation",
            label: "Rotation and rigid bodies",
            focus: "rotation about a fixed axis, angular momentum, moment of inertia",
            front: "How does a net torque relate to angular momentum?",
            back: "\\(\\tau = dL/dt\\): the rotational analog of Newton's second law.",
        },
        {
            category: "mechanics",
            tag: "topic::mechanics::central_forces",
            label: "Central forces and orbits",
            focus: "central forces, celestial mechanics, orbits, effective potential",
            front: "What does the effective potential add to the true potential?",
            back: "The centrifugal term \\(L^2/(2mr^2)\\), which encodes angular momentum and fixes the allowed radii.",
        },
        {
            category: "mechanics",
            tag: "topic::mechanics::lagrangian_hamiltonian",
            label: "Lagrangian and Hamiltonian formalism",
            focus: "Lagrangian and Hamiltonian mechanics, noninertial frames",
            front: "When is a coordinate's conjugate momentum conserved?",
            back: "When the coordinate is cyclic (\\(\\partial L/\\partial q = 0\\)), so \\(p = \\partial L/\\partial \\dot q\\) is constant.",
        },
        {
            category: "electromagnetism",
            tag: "topic::electromagnetism::electrostatics",
            label: "Electrostatics",
            focus: "Coulomb, fields, potential, Gauss's law, capacitance, dielectrics",
            front: "When does Gauss's law make a field easy to find?",
            back: "When the charge has enough symmetry (spherical, cylindrical, planar) that \\(E\\) is constant over a chosen surface.",
        },
        {
            category: "electromagnetism",
            tag: "topic::electromagnetism::magnetostatics",
            label: "Magnetostatics and the Lorentz force",
            focus: "magnetic fields, Lorentz force, Ampère, Biot-Savart",
            front: "What path does a charge take in a uniform magnetic field?",
            back: "A helix: circular motion of radius \\(mv_\\perp/qB\\) plus constant drift along \\(\\mathbf{B}\\).",
        },
        {
            category: "electromagnetism",
            tag: "topic::electromagnetism::induction_maxwell",
            label: "Induction and Maxwell's equations",
            focus: "Faraday induction, Maxwell's equations and their applications",
            front: "What does Lenz's law fix about an induced current?",
            back: "Its direction: the induced current opposes the change in flux that made it (energy conservation).",
            rusty: true,
        },
        {
            category: "electromagnetism",
            tag: "topic::electromagnetism::em_waves",
            label: "Electromagnetic waves",
            focus: "electromagnetic wave propagation, radiation",
            front: "What does the Poynting vector represent?",
            back: "\\(\\mathbf{S} = \\tfrac{1}{\\mu_0}\\,\\mathbf{E}\\times\\mathbf{B}\\): the energy flux and direction of an EM wave.",
        },
        {
            category: "electromagnetism",
            tag: "topic::electromagnetism::circuits",
            label: "Circuits (DC and AC)",
            focus: "DC and AC circuits, RLC, impedance",
            front: "What happens at resonance in a series RLC circuit?",
            back: "Reactances cancel, impedance is just \\(R\\), and current peaks at \\(\\omega = 1/\\sqrt{LC}\\).",
        },
        {
            category: "quantum",
            tag: "topic::quantum::formalism",
            label: "Formalism",
            focus: "states, operators, measurement, uncertainty",
            front: "What does the commutator \\([\\hat x, \\hat p] = i\\hbar\\) imply?",
            back: "Position and momentum cannot both be sharp: \\(\\Delta x\\,\\Delta p \\ge \\hbar/2\\).",
            rusty: true,
        },
        {
            category: "quantum",
            tag: "topic::quantum::schrodinger_solutions",
            label: "Schrödinger solutions",
            focus: "square wells, barriers, harmonic oscillator, hydrogenic atoms",
            front: "Why is the ground-state energy of a box nonzero?",
            back: "Confinement plus uncertainty: \\(E_1 = \\pi^2\\hbar^2/(2mL^2) > 0\\).",
        },
        {
            category: "quantum",
            tag: "topic::quantum::angular_momentum_spin",
            label: "Angular momentum and spin",
            focus: "angular momentum, spin",
            front: "How do the ladder operators act on \\(|j,m\\rangle\\)?",
            back: "\\(J_\\pm|j,m\\rangle = \\hbar\\sqrt{j(j+1)-m(m\\pm1)}\\,|j,m\\pm1\\rangle\\).",
        },
        {
            category: "quantum",
            tag: "topic::quantum::perturbation_symmetry",
            label: "Perturbation theory and symmetry",
            focus: "perturbation theory, identical particles, wavefunction symmetry",
            front: "Write the first-order energy shift from a perturbation \\(H'\\).",
            back: "\\(E_n^{(1)} = \\langle n | H' | n \\rangle\\), the expectation in the unperturbed state.",
        },
        {
            category: "thermodynamics",
            tag: "topic::thermodynamics",
            label: "Thermodynamics and statistical mechanics",
            focus: "laws and processes, ensembles, kinetic theory",
            front: "What efficiency bounds any engine between two reservoirs?",
            back: "The Carnot limit \\(\\eta = 1 - T_c/T_h\\), set by the second law.",
            rusty: true,
        },
        {
            category: "atomic",
            tag: "topic::atomic",
            label: "Atomic physics",
            focus: "Bohr model, spectra, selection rules, atoms in fields",
            front: "State the electric-dipole selection rule on \\(\\ell\\).",
            back: "\\(\\Delta\\ell = \\pm 1\\) (with \\(\\Delta m = 0, \\pm 1\\)): the photon carries one unit of angular momentum.",
        },
        {
            category: "optics_waves",
            tag: "topic::optics_waves",
            label: "Optics and wave phenomena",
            focus: "interference, diffraction, geometrical optics, polarization",
            front: "State the Rayleigh criterion for resolving two sources.",
            back: "Just resolved when one's first diffraction minimum lands on the other's maximum, \\(\\theta \\approx 1.22\\,\\lambda/D\\).",
        },
        {
            category: "special_relativity",
            tag: "topic::special_relativity",
            label: "Special relativity",
            focus: "time dilation, length contraction, four-vectors, energy-momentum",
            front: "What is invariant under a Lorentz transformation?",
            back: "The interval \\(s^2 = (ct)^2 - x^2\\), and \\(m^2c^4 = E^2 - (pc)^2\\).",
        },
        {
            category: "lab",
            tag: "topic::lab",
            label: "Laboratory methods",
            focus: "data and error analysis, counting statistics, instrumentation",
            front: "What is the uncertainty on a Poisson count of \\(N\\) events?",
            back: "\\(\\sqrt{N}\\); the relative error \\(1/\\sqrt{N}\\) shrinks as you count more.",
        },
        {
            category: "specialized",
            tag: "topic::specialized",
            label: "Specialized topics",
            focus: "nuclear and particle, condensed matter, astrophysics",
            front: "Why does a superconductor expel a weak magnetic field?",
            back: "The Meissner effect: surface supercurrents screen the interior, so \\(B = 0\\) inside.",
        },
    ];

    // Extra sample fronts so the six small categories read as full sets when the
    // wheel deals in (the walk authors one card each; these round out the browse).
    const PAD: Record<string, { front: string; back?: string }[]> = {
        thermodynamics: [
            { front: "Write the partition function of a two-level system." },
            { front: "What separates Bose-Einstein from Fermi-Dirac statistics?" },
        ],
        atomic: [
            { front: "Why does a Stern-Gerlach beam split into exactly two?" },
            { front: "Unpack the term symbol \\(^{2}P_{3/2}\\)." },
        ],
        optics_waves: [
            { front: "Where do the maxima land in two-slit interference?" },
            { front: "Group velocity or phase velocity: which carries the signal?" },
        ],
        special_relativity: [
            { front: "Why is simultaneity frame dependent?" },
            { front: "What breaks the symmetry between the twins?" },
        ],
        lab: [
            {
                front: "Chi-squared per degree of freedom sits near one. What does that mean?",
            },
            { front: "When is a straight line on a log-log plot the right fit?" },
        ],
        specialized: [
            { front: "Sketch the dispersion relation for a monatomic 1D lattice." },
            {
                front: "What conserved quantity does beta decay seem to violate until the neutrino?",
            },
        ],
    };

    const total = TOPICS.length;

    let filled: boolean[] = TOPICS.map(() => false);
    let index = 0;
    let completed = false;
    let auto = false;
    let theme: "light" | "dark" = "light";
    let reduceMotion = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    $: doneCount = filled.filter(Boolean).length;
    $: pct = Math.round((doneCount / total) * 100);
    $: current = TOPICS[index];
    $: shownFront = filled[index] ? current.front : "";
    $: shownBack = filled[index] ? current.back : "";

    // Coverage checklist: the nine categories with their subtopics, checking off
    // as cards are authored. This is the gate made visible (one card per subtopic).
    $: groups = CATEGORY_ORDER.map((cat) => {
        const items = TOPICS.map((t, i) => ({ t, i })).filter(
            (x) => x.t.category === cat,
        );
        return {
            cat,
            name: CATEGORY_NAMES[cat],
            items,
            done: items.filter((x) => filled[x.i]).length,
        };
    });

    // The payoff wheel: the authored cards grouped into their category sets, padded
    // so the small categories browse as full decks. Fed to the real CardWheel.
    $: wheelSets = CATEGORY_ORDER.map((cat) => ({
        category: cat,
        name: CATEGORY_NAMES[cat],
        cards: [
            ...TOPICS.filter((t) => t.category === cat).map((t) => ({
                front: t.front,
                back: t.back,
            })),
            ...(PAD[cat] ?? []),
        ],
    })).filter((s) => s.cards.length > 0);

    function firstUnfilled(): number {
        return filled.findIndex((f) => !f);
    }

    function fillCurrent(): void {
        if (filled[index]) {
            return;
        }
        filled = filled.map((f, i) => (i === index ? true : f));
    }

    function finish(): void {
        completed = true;
        stopAuto();
    }

    // One manual step: author the current card (its text appears), then advance to
    // the next unauthored subtopic, or finish when every subtopic is covered.
    function authorNext(): void {
        if (completed) {
            return;
        }
        fillCurrent();
        const next = firstUnfilled();
        if (next === -1) {
            finish();
        } else {
            index = next;
        }
    }

    function fillAll(): void {
        stopAuto();
        filled = filled.map(() => true);
        finish();
    }

    function reset(): void {
        stopAuto();
        filled = TOPICS.map(() => false);
        index = 0;
        completed = false;
    }

    // Auto-play runs a leisurely two-phase loop so the editor is seen filling, then
    // moving on: fill the current card, pause, advance, pause, until complete.
    function autoLoop(): void {
        if (!auto || completed) {
            return;
        }
        const beat = reduceMotion ? 0 : 560;
        if (!filled[index]) {
            fillCurrent();
            timer = setTimeout(autoLoop, beat);
            return;
        }
        const next = firstUnfilled();
        if (next === -1) {
            finish();
            return;
        }
        index = next;
        timer = setTimeout(autoLoop, Math.max(120, beat * 0.6));
    }

    function startAuto(): void {
        if (completed) {
            reset();
        }
        auto = true;
        autoLoop();
    }

    function stopAuto(): void {
        auto = false;
        if (timer) {
            clearTimeout(timer);
            timer = null;
        }
    }

    function toggleAuto(): void {
        if (auto) {
            stopAuto();
        } else {
            startAuto();
        }
    }

    // The gallery does not route; record the choice so the wheel button reads wired.
    let studied = "";
    function studySet(category: string): void {
        studied = category;
    }
    function addCard(): void {
        // Read-only demo: the wheel's add tile is shown but not persisted here.
    }

    onDestroy(stopAuto);
</script>

<div class="head">
    <h1>Calibration walkthrough</h1>
    <p>
        The redesigned first-run calibration, end to end on synthetic data. It walks the <strong
        >
            20 blueprint subtopics
        </strong>
        one card at a time, each with its real focus line, authoring one card per subtopic.
        Click
        <strong>Author &amp; next</strong>
        to step through it, or
        <strong>Auto-play</strong>
        to watch it run to completion, and the Library card sets deal in. Rusty categories
        (from a mock diagnostic) ask for extra focus.
    </p>
</div>

<div class="pgrep demo-root" class:night-mode={theme === "dark"}>
    <div class="controls">
        <div class="controls-main">
            {#if !completed}
                <button class="btn primary" on:click={authorNext} disabled={auto}>
                    Author &amp; next
                </button>
                <button class="btn" on:click={toggleAuto}>
                    {auto ? "Stop" : "Auto-play"}
                </button>
                <button class="btn" on:click={fillAll} disabled={auto}>Fill all</button>
            {:else}
                <button class="btn primary" on:click={reset}>Replay demo</button>
            {/if}
            <button class="btn ghost" on:click={reset}>Reset</button>
        </div>
        <div class="controls-aside">
            <label class="check">
                <input type="checkbox" bind:checked={reduceMotion} />
                Reduced motion
            </label>
            <div class="chips">
                <button
                    class="chip"
                    class:selected={theme === "light"}
                    on:click={() => (theme = "light")}
                >
                    Light
                </button>
                <button
                    class="chip"
                    class:selected={theme === "dark"}
                    on:click={() => (theme = "dark")}
                >
                    Dark
                </button>
            </div>
        </div>
    </div>

    <div class="progress" aria-hidden="true">
        <div class="progress-track">
            <div class="progress-fill" style="width: {pct}%"></div>
        </div>
        <span class="progress-label">{doneCount} of {total} subtopics authored</span>
    </div>

    {#if !completed}
        <div class="cols">
            <!-- The guided editor: the current subtopic, its focus line, and the
                 card being authored for it. -->
            <section class="editor" aria-label="Author a flashcard">
                <div class="guide">
                    <div class="guide-top">
                        <span class="eyebrow">Card {index + 1} of {total}</span>
                        <span class="cat-pill">{CATEGORY_NAMES[current.category]}</span>
                    </div>
                    <div class="guide-topic">
                        <span class="dot" aria-hidden="true"></span>
                        <span class="guide-topic-label">{current.label}</span>
                        {#if current.rusty}
                            <span class="rusty-pill">Rusty · extra focus</span>
                        {/if}
                    </div>
                    <p class="focus">Focus: {current.focus}</p>
                </div>

                <label class="field">
                    <span class="eyebrow">Front</span>
                    <textarea
                        rows="2"
                        readonly
                        class:filled={filled[index]}
                        placeholder="What does this concept test?"
                        value={shownFront}
                    ></textarea>
                </label>
                <label class="field">
                    <span class="eyebrow">Back</span>
                    <textarea
                        rows="3"
                        readonly
                        class:filled={filled[index]}
                        placeholder="Your concise answer, in your own words."
                        value={shownBack}
                    ></textarea>
                </label>

                {#if filled[index]}
                    <p class="typeset">
                        Typeset front: <span>{@html renderMath(current.front)}</span>
                    </p>
                {/if}

                <p class="note">
                    Writing one in your own words is the generation-effect act. The card
                    enters your deck; with AI on, it also seeds the matching set.
                </p>
            </section>

            <!-- Coverage: the gate made visible. Every subtopic across the nine
                 categories checks off as it is authored. -->
            <aside class="coverage" aria-label="Coverage">
                <span class="coverage-title">Coverage</span>
                <div class="groups">
                    {#each groups as g (g.cat)}
                        <div class="group">
                            <div class="group-head">
                                <span class="group-name">{g.name}</span>
                                <span class="group-count">
                                    {g.done}/{g.items.length}
                                </span>
                            </div>
                            <div class="items">
                                {#each g.items as it (it.t.tag)}
                                    <span
                                        class="item"
                                        class:done={filled[it.i]}
                                        class:active={it.i === index && !completed}
                                    >
                                        <span class="tick" aria-hidden="true">
                                            {#if filled[it.i]}✓{/if}
                                        </span>
                                        {it.t.label}
                                        {#if it.t.rusty}
                                            <span
                                                class="rusty-dot"
                                                aria-hidden="true"
                                            ></span>
                                        {/if}
                                    </span>
                                {/each}
                            </div>
                        </div>
                    {/each}
                </div>
            </aside>
        </div>
    {:else}
        <div class="done-banner" in:fly={{ y: 8, duration: reduceMotion ? 0 : 300 }}>
            <div class="done-copy">
                <span class="done-title">Calibration complete</span>
                <span class="done-sub">
                    One card in every subtopic. Study unlocks and your Library becomes
                    the card sets.
                </span>
            </div>
            {#if studied}
                <span class="studied">
                    Would study: <code>{studied}</code>
                </span>
            {/if}
        </div>
        {#key completed}
            <div class="wheel-holder">
                <CardWheel
                    sets={wheelSets}
                    onStudySet={studySet}
                    onAddCard={addCard}
                    forceReduce={reduceMotion}
                />
            </div>
        {/key}
    {/if}
</div>

<style lang="scss">
    .head {
        margin-bottom: var(--space-3);

        h1 {
            margin: 0 0 var(--space-1);
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        p {
            margin: 0;
            max-width: 82ch;
            font-size: var(--text-body);
            line-height: 1.55;
            color: var(--muted);
        }

        strong {
            color: var(--text);
            font-weight: 600;
        }
    }

    .demo-root {
        border: var(--hairline);
        border-radius: var(--radius-frame);
        background: var(--canvas);
        color: var(--text);
        padding: var(--space-3);
        font-family: var(--font-ui);
    }

    .controls {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-2);
        margin-bottom: var(--space-2);
    }

    .controls-main,
    .controls-aside {
        display: inline-flex;
        align-items: center;
        flex-wrap: wrap;
        gap: var(--space-1);
    }

    .controls-aside {
        gap: var(--space-2);
    }

    .btn {
        padding: 9px 16px;
        font-family: var(--font-ui);
        font-size: var(--text-body);
        font-weight: 500;
        border: var(--hairline);
        border-radius: var(--radius-control);
        background: var(--surface);
        color: var(--text);
        cursor: pointer;
        transition: var(--transition-calm);

        &:hover:not(:disabled) {
            border-color: var(--muted);
            background: var(--hover-wash);
        }

        &.primary {
            background: var(--action-bg);
            color: var(--action-fg);
            border-color: var(--action-bg);

            &:hover:not(:disabled) {
                background: var(--action-bg-hover);
                border-color: var(--action-bg-hover);
            }
        }

        &.ghost {
            background: none;
            color: var(--muted);
            border-color: transparent;
        }

        &:disabled {
            opacity: 0.5;
            cursor: default;
        }
    }

    .check {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: var(--text-small);
        color: var(--text);
        cursor: pointer;

        input {
            accent-color: var(--action-bg);
            cursor: pointer;
        }
    }

    .chips {
        display: inline-flex;
        gap: var(--space-1);
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
            color: var(--action-fg);
            background: var(--action-bg);
            border-color: var(--action-bg);
        }
    }

    .progress {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        margin-bottom: var(--space-3);
    }

    .progress-track {
        flex: 1 1 auto;
        height: 8px;
        border-radius: var(--radius-pill);
        background: var(--elevated);
        overflow: hidden;
    }

    .progress-fill {
        height: 100%;
        border-radius: var(--radius-pill);
        background: var(--memory);
        transition: width var(--duration-calm) var(--ease-spring);
    }

    .progress-label {
        flex: 0 0 auto;
        font-size: var(--text-small);
        color: var(--muted);
        font-variant-numeric: tabular-nums;
    }

    .cols {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 320px;
        gap: var(--space-3);
        align-items: start;
    }

    /* Editor */
    .editor {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);
        padding: var(--space-3);
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
    }

    .guide {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
    }

    .guide-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-2);
    }

    .cat-pill {
        font-size: var(--text-caption);
        font-weight: 500;
        color: var(--muted);
        border: var(--hairline);
        border-radius: var(--radius-pill);
        padding: 3px 10px;
        white-space: nowrap;
    }

    .guide-topic {
        display: inline-flex;
        align-items: center;
        gap: var(--space-1);
        min-width: 0;

        .dot {
            flex: 0 0 7px;
            width: 7px;
            height: 7px;
            border-radius: var(--radius-pill);
            background: var(--memory);
        }
    }

    .guide-topic-label {
        font-size: var(--text-emphasis);
        font-weight: 600;
        letter-spacing: -0.01em;
        color: var(--memory-text);
    }

    .rusty-pill {
        font-size: var(--text-caption);
        font-weight: 500;
        color: var(--caution);
        border: 1px solid var(--caution);
        border-radius: var(--radius-pill);
        padding: 2px 8px;
        white-space: nowrap;
    }

    .focus {
        margin: 0;
        font-size: var(--text-small);
        line-height: 1.5;
        color: var(--muted);
    }

    .eyebrow {
        font-size: var(--text-caption);
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
    }

    .field {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);

        textarea {
            font: inherit;
            font-size: var(--text-emphasis);
            line-height: 1.6;
            color: var(--text);
            background: var(--elevated);
            border: var(--hairline);
            border-radius: var(--radius-control);
            padding: 12px 14px;
            resize: vertical;
            transition: var(--transition-calm);

            &::placeholder {
                color: var(--muted);
            }

            &.filled {
                border-color: var(--memory);
                background: var(--surface);
            }
        }
    }

    .typeset {
        margin: 0;
        font-size: var(--text-small);
        color: var(--muted);
        display: flex;
        gap: 8px;
        align-items: baseline;
        flex-wrap: wrap;

        span {
            color: var(--text);
            font-size: var(--text-body);
        }
    }

    .note {
        margin: 0;
        font-size: var(--text-small);
        line-height: 1.5;
        color: var(--muted);
    }

    /* Coverage checklist */
    .coverage {
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        padding: var(--space-3);
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
    }

    .coverage-title {
        font-size: var(--text-caption);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--muted);
    }

    .groups {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
    }

    .group {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .group-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--space-1);
    }

    .group-name {
        font-size: var(--text-small);
        font-weight: 600;
        color: var(--text);
    }

    .group-count {
        font-size: var(--text-caption);
        color: var(--muted);
        font-variant-numeric: tabular-nums;
    }

    .items {
        display: flex;
        flex-direction: column;
        gap: 3px;
    }

    .item {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        font-size: var(--text-small);
        line-height: 1.35;
        color: var(--muted);
        transition: var(--transition-calm);

        .tick {
            flex: 0 0 14px;
            width: 14px;
            height: 14px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            border: var(--hairline);
            border-radius: var(--radius-pill);
            color: var(--action-fg);
        }

        &.done {
            color: var(--text);

            .tick {
                background: var(--memory);
                border-color: var(--memory);
                color: var(--action-fg);
            }
        }

        &.active {
            color: var(--memory-text);
            font-weight: 600;
        }
    }

    .rusty-dot {
        width: 5px;
        height: 5px;
        border-radius: var(--radius-pill);
        background: var(--caution);
    }

    /* Completion + wheel */
    .done-banner {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-2);
        padding: 14px 18px;
        margin-bottom: var(--space-2);
        background: var(--surface);
        border: var(--hairline);
        border-radius: var(--radius-card);
        box-shadow: var(--shadow-card);
    }

    .done-copy {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .done-title {
        font-size: var(--text-emphasis);
        font-weight: 600;
        color: var(--text);
    }

    .done-sub {
        font-size: var(--text-small);
        color: var(--muted);
    }

    .studied {
        font-size: var(--text-small);
        color: var(--muted);

        code {
            font-family: var(--font-mono);
        }
    }

    .wheel-holder {
        height: min(72vh, 620px);
        border: var(--hairline);
        border-radius: var(--radius-frame);
        overflow: hidden;
    }

    @media (max-width: 900px) {
        .cols {
            grid-template-columns: minmax(0, 1fr);
        }
    }
</style>
