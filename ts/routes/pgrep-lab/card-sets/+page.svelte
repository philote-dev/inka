<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Card Sets wheel (review playground). The Library browser, recreated as
     CardWheel.svelte, shown here on synthetic math-rich fixture data so the
     motion can be inspected and tuned without a running collection. Every
     geometry and spring number is a live slider (seeded from the real presets
     the component exports, so they never drift). Pick a preset to load its
     numbers, drag the sliders to feel each one, force reduced motion, flip the
     theme, or replay the intro deal. No bridge calls. -->
<script lang="ts">
    import CardWheel, {
        WHEEL_FEELS,
        WHEEL_SPRING,
    } from "$lib/components/CardWheel.svelte";

    interface WheelCard {
        note_id?: number;
        front: string;
        back?: string;
    }
    interface CardSet {
        category: string;
        name: string;
        cards: WheelCard[];
    }

    const FEELS = ["Ferris", "Shallow", "Deep"] as const;
    type Preset = (typeof FEELS)[number];
    let preset: Preset = "Ferris";

    // Live geometry + spring, seeded from the real preset numbers the component
    // exports. Reassigning `vals` (never mutating in place) keeps the reactive
    // `tune` fresh, which the wheel picks up on the next frame.
    let vals = { ...WHEEL_FEELS.Ferris, ...WHEEL_SPRING };
    $: tune = vals;

    type Knob = keyof typeof vals;
    const KNOBS: {
        key: Knob;
        label: string;
        min: number;
        max: number;
        step: number;
        unit?: string;
        hint: string;
    }[] = [
        {
            key: "R",
            label: "Radius",
            min: 300,
            max: 1100,
            step: 10,
            unit: "px",
            hint: "How far the ring curves into the screen.",
        },
        {
            key: "sp",
            label: "Angular step",
            min: 10,
            max: 60,
            step: 1,
            unit: "°",
            hint: "Degrees between neighbouring sets.",
        },
        {
            key: "maxPhi",
            label: "Max angle",
            min: 40,
            max: 90,
            step: 1,
            unit: "°",
            hint: "Clamp on how far a set can swing to the side.",
        },
        {
            key: "dim",
            label: "Dim falloff",
            min: 0,
            max: 1,
            step: 0.02,
            hint: "How quickly receding sets fade out.",
        },
        {
            key: "push",
            label: "Push back",
            min: 0,
            max: 500,
            step: 10,
            unit: "px",
            hint: "Extra depth pushed onto the neighbours.",
        },
        {
            key: "fwd",
            label: "Forward bump",
            min: 0,
            max: 160,
            step: 5,
            unit: "px",
            hint: "Slight lift toward the viewer at the sides.",
        },
        {
            key: "rotK",
            label: "Rotation",
            min: 0,
            max: 1,
            step: 0.01,
            hint: "How much each set yaws with its angle.",
        },
        {
            key: "follow",
            label: "Spring follow",
            min: 0.02,
            max: 0.6,
            step: 0.01,
            hint: "How quickly the wheel settles after a scroll or drag.",
        },
        {
            key: "spreadRate",
            label: "Fan-out speed",
            min: 0.02,
            max: 0.4,
            step: 0.01,
            hint: "Speed of the intro deal-out (hit Replay to see it).",
        },
    ];

    function setKnob(key: Knob, v: number): void {
        vals = { ...vals, [key]: v };
    }
    function loadPreset(name: Preset): void {
        vals = { ...WHEEL_FEELS[name], ...WHEEL_SPRING };
        preset = name;
    }

    // Untouched means the sliders still match the loaded preset (so the preset
    // chip reads as selected; once you drag a slider it becomes "custom").
    $: pristine =
        JSON.stringify(vals) ===
        JSON.stringify({ ...WHEEL_FEELS[preset], ...WHEEL_SPRING });

    const fmt = (v: number): string =>
        Number.isInteger(v) ? String(v) : v.toFixed(2);
    $: valuesText =
        `{ R: ${vals.R}, sp: ${vals.sp}, dim: ${vals.dim}, maxPhi: ${vals.maxPhi}, ` +
        `push: ${vals.push}, fwd: ${vals.fwd}, rotK: ${vals.rotK} }\n` +
        `spring: { follow: ${vals.follow}, spreadRate: ${vals.spreadRate} }`;

    let theme: "light" | "dark" = "light";
    let reduceMotion = false;
    // Bumping this remounts the wheel, replaying the mount fan-out with the
    // current spread rate.
    let replay = 0;

    // The wheel handles any N; this fixture is the nine blueprint categories with
    // real GRE question fronts (several carrying delimited LaTeX, so the shared
    // renderMath is exercised). Names match the app's canonical category labels.
    const sets: CardSet[] = [
        {
            category: "mechanics",
            name: "Classical Mechanics",
            cards: [
                {
                    front: "A bead slides on a frictionless hoop spinning about a vertical diameter. Where are the equilibria?",
                },
                {
                    front: "Write the Lagrangian for a simple pendulum and derive its equation of motion.",
                },
                {
                    front: "A coordinate is missing from the Lagrangian. What is conserved?",
                },
                {
                    front: "What does the effective potential \\(V_{\\mathrm{eff}}(r)\\) add to the true potential?",
                },
                { front: "Why does a spinning top precess instead of falling over?" },
                {
                    front: "A uniform rod pivots about one end. What is its moment of inertia?",
                },
                {
                    front: "For small oscillations, how do you read the frequency off the potential?",
                },
            ],
        },
        {
            category: "electromagnetism",
            name: "Electromagnetism",
            cards: [
                {
                    front: "Relate the flux of \\(\\mathbf{E}\\) through a closed surface to the charge it encloses.",
                },
                {
                    front: "A point charge sits above a grounded plane. What replaces the plane in the image solution?",
                },
                { front: "Derive the field inside a uniformly charged sphere." },
                { front: "What does Lenz's law say about the sign of an induced EMF?" },
                {
                    front: "What does the Poynting vector measure, and in which direction does it point?",
                },
                {
                    front: "The field of an ideal dipole falls off as which power of \\(r\\)?",
                },
            ],
        },
        {
            category: "quantum",
            name: "Quantum Mechanics",
            cards: [
                {
                    front: "Why does a particle in a box have nonzero energy in its ground state?",
                },
                {
                    front: "What does \\([\\hat{x}, \\hat{p}] = i\\hbar\\) forbid you from measuring?",
                },
                { front: "How do ladder operators act on harmonic oscillator states?" },
                {
                    front: "Write the first order energy shift from a perturbation \\(H'\\).",
                },
                {
                    front: "What probability does the Born rule assign to a measurement outcome?",
                },
                {
                    front: "Why must the wavefunction of two identical fermions be antisymmetric?",
                },
            ],
        },
        {
            category: "thermodynamics",
            name: "Thermo & Stat Mech",
            cards: [
                { front: "Why is entropy extensive while temperature is not?" },
                {
                    front: "What efficiency does a Carnot engine reach between two reservoirs?",
                },
                { front: "Write the partition function for a two level system." },
                { front: "Read a Maxwell relation off \\(dF = -S\\,dT - p\\,dV\\)." },
                { front: "What separates Bose Einstein from Fermi Dirac statistics?" },
            ],
        },
        {
            category: "atomic",
            name: "Atomic Physics",
            cards: [
                { front: "Bohr energy levels scale as which power of \\(n\\)?" },
                { front: "Which interactions produce the fine structure splitting?" },
                {
                    front: "State the selection rule on \\(\\Delta \\ell\\) for dipole transitions.",
                },
                { front: "Why does a Stern Gerlach beam split into exactly two?" },
                { front: "Unpack the term symbol \\(^{2}P_{3/2}\\)." },
            ],
        },
        {
            category: "optics_waves",
            name: "Optics & Waves",
            cards: [
                { front: "Where do the maxima land in two slit interference?" },
                {
                    front: "What does a quarter wave plate do to linearly polarized light?",
                },
                {
                    front: "State the Rayleigh criterion for resolving two point sources.",
                },
                {
                    front: "Group velocity or phase velocity. Which one carries the signal?",
                },
                { front: "Where do the minima of single slit diffraction fall?" },
            ],
        },
        {
            category: "special_relativity",
            name: "Special Relativity",
            cards: [
                { front: "Why is simultaneity frame dependent?" },
                { front: "What stays fixed in the invariant interval between frames?" },
                {
                    front: "Why can relativistic velocity addition never exceed \\(c\\)?",
                },
                {
                    front: "What does \\(E^{2} = (pc)^{2} + (mc^{2})^{2}\\) give for a photon?",
                },
                { front: "What breaks the symmetry between the twins?" },
            ],
        },
        {
            category: "lab",
            name: "Laboratory Methods",
            cards: [
                { front: "Propagate the uncertainty through \\(f = x / y\\)." },
                {
                    front: "You count \\(N\\) events. What is the Poisson error on the count?",
                },
                {
                    front: "Chi squared per degree of freedom sits near one. What does that mean?",
                },
                { front: "When is a straight line on a log log plot the right fit?" },
            ],
        },
        {
            category: "specialized",
            name: "Specialized Topics",
            cards: [
                {
                    front: "In a semiconductor, what sets the size of the band gap you can excite across?",
                },
                { front: "Sketch the dispersion relation for a monatomic 1D lattice." },
                {
                    front: "What conserved quantity does a nuclear beta decay appear to violate until the neutrino is added?",
                },
                { front: "Why does a superconductor expel a weak magnetic field?" },
            ],
        },
    ];

    // The gallery does not route; record the choice so the button reads as wired.
    let studied = "";
    function studySet(category: string): void {
        studied = category;
    }

    // No backend here: append to the fixture so the composer round-trip (add,
    // count bump, new grid card) can be reviewed on synthetic data.
    let mutable = sets;
    function addCard(category: string, front: string, back: string): void {
        mutable = mutable.map((s) =>
            s.category === category
                ? { ...s, cards: [...s.cards, { front, back }] }
                : s,
        );
    }
</script>

<div class="head">
    <h1>Card sets wheel</h1>
    <p>
        The Library browser as a live playground. Topic sets ride a 3D wheel you
        scroll, drag, arrow through, or click open into a dealt grid. Every geometry
        and spring number below is wired straight into
        <code>CardWheel.svelte</code>, so drag a slider and watch the motion change.
        Reduced motion snaps instead of springing; the loop idles when the wheel is
        at rest.
    </p>
</div>

<div class="playground">
    <aside class="panel">
        <div class="panel-group">
            <span class="panel-label">Preset</span>
            <div class="chips">
                {#each FEELS as f (f)}
                    <button
                        class="chip"
                        class:selected={f === preset && pristine}
                        on:click={() => loadPreset(f)}
                    >
                        {f}
                    </button>
                {/each}
                {#if !pristine}
                    <button class="chip ghost" on:click={() => loadPreset(preset)}>
                        Reset
                    </button>
                {/if}
            </div>
        </div>

        <div class="knobs">
            {#each KNOBS as k (k.key)}
                <label class="knob" title={k.hint}>
                    <span class="knob-name">{k.label}</span>
                    <input
                        type="range"
                        min={k.min}
                        max={k.max}
                        step={k.step}
                        value={vals[k.key]}
                        on:input={(e) => setKnob(k.key, +e.currentTarget.value)}
                    />
                    <span class="knob-val">{fmt(vals[k.key])}{k.unit ?? ""}</span>
                </label>
            {/each}
        </div>

        <div class="panel-group">
            <span class="panel-label">Theme</span>
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

        <div class="panel-group actions">
            <label class="check">
                <input type="checkbox" bind:checked={reduceMotion} />
                Reduced motion
            </label>
            <button class="chip" on:click={() => (replay += 1)}>Replay intro</button>
        </div>

        <details class="readout">
            <summary>Current values</summary>
            <pre>{valuesText}</pre>
        </details>

        {#if studied}
            <p class="studied">Would study: <code>{studied}</code></p>
        {/if}
    </aside>

    <div class="stage-wrap">
        {#key replay}
            <div class="pgrep wheel-demo" class:night-mode={theme === "dark"}>
                <CardWheel
                    sets={mutable}
                    wheelFeel={preset}
                    {tune}
                    forceReduce={reduceMotion}
                    onStudySet={studySet}
                    onAddCard={addCard}
                />
            </div>
        {/key}
    </div>
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
            max-width: 78ch;
            font-size: var(--text-body);
            line-height: 1.55;
            color: var(--muted);
        }

        code {
            font-family: var(--font-mono);
            font-size: var(--text-small);
        }
    }

    /* Controls beside the stage; stacks on narrow viewports. */
    .playground {
        display: grid;
        grid-template-columns: 288px minmax(0, 1fr);
        gap: var(--space-4);
        align-items: start;
    }

    .panel {
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
        padding: var(--space-3);
        border: var(--hairline);
        border-radius: var(--radius-frame);
        background: var(--surface);
        position: sticky;
        top: var(--space-2);
    }

    .panel-group {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
    }

    .panel-label {
        font-size: var(--text-caption);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--muted);
    }

    .chips {
        display: inline-flex;
        flex-wrap: wrap;
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

        &.ghost {
            font-style: italic;
        }
    }

    /* One slider row: label / track / value, aligned in a tidy grid. */
    .knobs {
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .knob {
        display: grid;
        grid-template-columns: 92px 1fr 52px;
        align-items: center;
        gap: var(--space-2);
        cursor: pointer;
    }

    .knob-name {
        font-size: var(--text-small);
        color: var(--text);
    }

    .knob input[type="range"] {
        width: 100%;
        accent-color: var(--action-bg);
        cursor: pointer;
    }

    .knob-val {
        font-family: var(--font-mono);
        font-size: var(--text-small);
        color: var(--muted);
        text-align: right;
        font-variant-numeric: tabular-nums;
    }

    .actions {
        flex-direction: row;
        align-items: center;
        justify-content: space-between;
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

    .readout {
        font-size: var(--text-small);
        color: var(--muted);

        summary {
            cursor: pointer;
            user-select: none;
        }

        pre {
            margin: var(--space-1) 0 0;
            padding: var(--space-2);
            background: var(--elevated);
            border-radius: var(--radius-control);
            font-family: var(--font-mono);
            font-size: var(--text-caption);
            line-height: 1.5;
            color: var(--text);
            white-space: pre-wrap;
            word-break: break-word;
        }
    }

    .studied {
        margin: 0;
        font-size: var(--text-small);
        color: var(--muted);

        code {
            font-family: var(--font-mono);
        }
    }

    /* Bound the wheel in a framed panel (it fills its parent's height). Tall
       enough for the perspective stage to read; the frame clips the receding
       decks the way the app surface does. */
    .stage-wrap {
        min-width: 0;
    }

    .wheel-demo {
        height: min(78vh, 680px);
        border: var(--hairline);
        border-radius: var(--radius-frame);
        overflow: hidden;
    }

    @media (max-width: 900px) {
        .playground {
            grid-template-columns: 1fr;
        }

        .panel {
            position: static;
        }
    }
</style>
