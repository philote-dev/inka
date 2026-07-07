<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
-->
<!-- Card Sets wheel (review fixture). The Library browser from the design handoff,
     recreated as CardWheel.svelte and shown here on synthetic, math-rich fixture
     data so the motion (spring, deal, hover peek) and both themes can be reviewed
     without a running collection. The wheelFeel toggle switches the three tuned
     geometry presets (TECHNICAL-SPEC §4). Scroll or drag the stage, click the
     centered set to deal it out, Esc or "All sets" to close. No bridge calls. -->
<script lang="ts">
    import CardWheel from "$lib/components/CardWheel.svelte";

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
    let wheelFeel: (typeof FEELS)[number] = "Ferris";

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
        The Library browser: topic sets on a 3D wheel you scroll, drag, and click open
        into a dealt grid. Recreated from the design handoff as
        <code>CardWheel.svelte</code>
        on the shared renderMath. Reduced-motion snaps instead of springing, and the loop
        idles when the wheel is at rest.
    </p>
</div>

<div class="controls">
    <span class="controls-label">Feel</span>
    <div class="chips">
        {#each FEELS as f (f)}
            <button
                class="chip"
                class:selected={f === wheelFeel}
                on:click={() => (wheelFeel = f)}
            >
                {f}
            </button>
        {/each}
    </div>
    {#if studied}
        <span class="studied">Would study: {studied}</span>
    {/if}
</div>

<div class="themes">
    <div class="theme-col">
        <span class="state">Light</span>
        <div class="pgrep wheel-demo">
            <CardWheel
                sets={mutable}
                {wheelFeel}
                onStudySet={studySet}
                onAddCard={addCard}
            />
        </div>
    </div>
    <div class="theme-col">
        <span class="state">Dark</span>
        <div class="pgrep night-mode wheel-demo">
            <CardWheel
                sets={mutable}
                {wheelFeel}
                onStudySet={studySet}
                onAddCard={addCard}
            />
        </div>
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

    .controls {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        margin-bottom: var(--space-3);
        flex-wrap: wrap;
    }

    .controls-label {
        font-size: var(--text-caption);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--muted);
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

    .studied {
        font-family: var(--font-mono);
        font-size: var(--text-small);
        color: var(--muted);
    }

    .themes {
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
    }

    .theme-col {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
    }

    .state {
        font-size: var(--text-caption);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--muted);
    }

    /* Bound the wheel in a framed panel (it fills its parent's height). Tall
       enough for the perspective stage to read; the frame clips the receding
       decks the way the app surface does. */
    .wheel-demo {
        height: 600px;
        border: var(--hairline);
        border-radius: var(--radius-frame);
        overflow: hidden;
    }
</style>
