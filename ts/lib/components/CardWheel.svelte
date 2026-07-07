<!--
Copyright: Ankitects Pty Ltd and contributors
License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

The Card Sets "wheel" (Library browser). A faithful Svelte port of the design
handoff (design/claude-design/design_handoff_card_sets): topic sets sit in an
infinite circular queue curving into the screen; the centered set is a stack of
cards you hover, click open into a flat grid, and close back into the stack.

Geometry, spring, timings, and the FLIP deal are the tuned constants from
TECHNICAL-SPEC.md (sections 3, 4, 6, 7). Two pgrep additions the prototype
omits (see the plan, section 5.5): the per-frame loop settles-and-stops when at
rest (the prototype loops forever), and prefers-reduced-motion snaps instead of
springing and skips the deal. The rail is provided by the surface shell, so this
renders only the content area. Card fronts are typeset with the shared renderMath
(the app's MathJax), never a CDN build.
-->
<script lang="ts" context="module">
    // Geometry presets and spring rates, exported so the dev gallery playground
    // can seed its live-tuning sliders from the real numbers instead of copying
    // them (a copy would silently drift). R px, sp/maxPhi degrees; rest px/unitless.
    export interface WheelFeel {
        R: number;
        sp: number;
        dim: number;
        maxPhi: number;
        push: number;
        fwd: number;
        rotK: number;
    }

    // TECHNICAL-SPEC section 4. Ferris is the shipped default; the others exist
    // for the dev gallery to inspect the feel.
    export const WHEEL_FEELS: Record<"Ferris" | "Shallow" | "Deep", WheelFeel> = {
        Ferris: {
            R: 640,
            sp: 34,
            dim: 0.52,
            maxPhi: 76,
            push: 260,
            fwd: 70,
            rotK: 0.45,
        },
        Shallow: {
            R: 920,
            sp: 23,
            dim: 0.38,
            maxPhi: 64,
            push: 180,
            fwd: 50,
            rotK: 0.52,
        },
        Deep: {
            R: 500,
            sp: 45,
            dim: 0.66,
            maxPhi: 86,
            push: 350,
            fwd: 100,
            rotK: 0.42,
        },
    };

    // Per-frame spring rates: how fast the wheel chases its target on release
    // (follow) and how fast the decks fan out on mount (spreadRate).
    export const WHEEL_SPRING = { follow: 0.16, spreadRate: 0.09 };

    // Dev-only live override (the gallery playground). Every field is optional and
    // falls back to the active preset / default spring rate, so production callers
    // pass nothing and get exactly the shipped feel.
    export interface WheelTune {
        R?: number;
        sp?: number;
        dim?: number;
        maxPhi?: number;
        push?: number;
        fwd?: number;
        rotK?: number;
        follow?: number;
        spreadRate?: number;
    }
</script>

<script lang="ts">
    import { onMount, tick } from "svelte";

    import { renderMath } from "$lib/pgrep/math";

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

    export let sets: CardSet[] = [];
    // Three tuned geometry presets (TECHNICAL-SPEC section 4). Ferris is the
    // shipped default; the others exist for the dev gallery to inspect the feel.
    export let wheelFeel: "Ferris" | "Shallow" | "Deep" = "Ferris";
    // The surface decides what "Study this set" does (Library navigates to the
    // topic's focus drill). Left undefined, the button is hidden.
    export let onStudySet: ((category: string) => void) | undefined = undefined;
    // "Add a card" persists the learner's front/back into the open set (Library:
    // pgrepAddCard; the dev gallery appends locally). Left undefined, the add
    // tile is hidden and the wheel stays read-only.
    export let onAddCard:
        | ((category: string, front: string, back: string) => void | Promise<void>)
        | undefined = undefined;
    // Dev gallery only: a live geometry/spring override and a forced reduced-motion
    // mode, so the playground can tune the feel and exercise the reduced path
    // without touching OS settings. Production surfaces leave both unset.
    export let tune: WheelTune | undefined = undefined;
    export let forceReduce: boolean | undefined = undefined;

    // Phone-tuned geometry (used automatically below the phone breakpoint): the
    // centered set fills the screen and a swipe brings the next one in, so the
    // wheel becomes a one-up carousel without losing its motion. Neighbours are
    // pushed well off-screen (large step) so only one set reads at a time.
    const PHONE: WheelFeel = {
        R: 760,
        sp: 47,
        dim: 0.92,
        maxPhi: 88,
        push: 300,
        fwd: 38,
        rotK: 0.4,
    };

    // Back-card offsets (TECHNICAL-SPEC section 6). Index 0 is the card just
    // behind the front, 2 the deepest. Hover (centered deck) lifts them to peek.
    const BASE = [
        "translateY(-5px) translateZ(-1px)",
        "translateY(-10px) translateZ(-2px)",
        "translateY(-15px) translateZ(-3px)",
    ];
    const PEEK = [
        "translateY(-16px) translateZ(-1px)",
        "translateY(-30px) translateZ(-2px)",
        "translateY(-44px) translateZ(-3px)",
    ];

    // Reactive UI state (changes rarely, so Svelte re-renders are cheap).
    let sel = 0;
    let hovered = -1;
    let open: number | null = null;
    let closing = false;
    let dragging = false;
    // OS reduced-motion preference; the effective `reduce` is derived below so the
    // dev gallery can force it on/off.
    let systemReduce = false;
    // Below the phone breakpoint the wheel uses the one-up PHONE geometry.
    let narrow = false;

    // Add-a-card composer state (Phase 2), scoped to the open set.
    let adding = false;
    let addFront = "";
    let addBack = "";
    let addBusy = false;

    // Spring numbers live OFF the reactive graph: the 60fps loop mutates this
    // object directly and writes styles on the deck nodes, so it never schedules
    // a Svelte update. T is the input target, A chases it, spread fans the decks
    // out on mount (0.04 -> 1).
    const motion = { T: 0, A: 0, spread: 0.04 };

    let stageEl: HTMLElement;
    let gridEl: HTMLElement | undefined;
    let scrollEl: HTMLElement | undefined;
    let frontEl: HTMLTextAreaElement | undefined;
    const deckEls: HTMLElement[] = [];

    let drag: { x: number; T: number } | null = null;
    let moved = false;
    let wheelTimer = 0;
    let closeTimer = 0;

    let rafId = 0;
    let running = false;

    // Base geometry from the preset (or the one-up PHONE geometry when narrow),
    // then the dev playground's live override on top (each field optional).
    $: baseFeel = narrow ? PHONE : (WHEEL_FEELS[wheelFeel] ?? WHEEL_FEELS.Ferris);
    $: feel = {
        R: tune?.R ?? baseFeel.R,
        sp: tune?.sp ?? baseFeel.sp,
        dim: tune?.dim ?? baseFeel.dim,
        maxPhi: tune?.maxPhi ?? baseFeel.maxPhi,
        push: tune?.push ?? baseFeel.push,
        fwd: tune?.fwd ?? baseFeel.fwd,
        rotK: tune?.rotK ?? baseFeel.rotK,
    };
    // Spring rates (dev-tunable); default to the shipped constants.
    $: follow = tune?.follow ?? WHEEL_SPRING.follow;
    $: spreadRate = tune?.spreadRate ?? WHEEL_SPRING.spreadRate;
    // Effective reduced motion: the OS preference, unless the gallery forces it.
    $: reduce = forceReduce ?? systemReduce;
    $: n = sets.length;
    $: totalCards = sets.reduce((sum, s) => sum + s.cards.length, 0);
    $: openSetData = open !== null ? (sets[open] ?? null) : null;
    $: openName = openSetData?.name ?? "";
    $: openCount = openSetData?.cards.length ?? 0;
    $: openCards = openSetData?.cards ?? [];
    // Data can arrive after mount; a fresh set list restarts the (possibly idle)
    // loop so the decks lay out.
    $: if (n > 0) {
        ensureRaf();
    }
    // A feel change (dev gallery), a live tune edit, or a forced reduced-motion
    // toggle re-runs the loop so a settled wheel re-lays out instead of freezing.
    $: if (wheelFeel || tune || forceReduce !== undefined) {
        ensureRaf();
    }

    function wrapOff(v: number): number {
        // Wrap to (-n/2, +n/2]: the shortest signed distance around the ring.
        if (n === 0) {
            return 0;
        }
        let o = ((v % n) + n) % n;
        if (o > n / 2) {
            o -= n;
        }
        return o;
    }

    function selIndex(): number {
        if (n === 0) {
            return 0;
        }
        return ((Math.round(motion.T) % n) + n) % n;
    }

    function ensureRaf(): void {
        if (!running) {
            running = true;
            rafId = requestAnimationFrame(frame);
        }
    }

    function settled(): boolean {
        // While a set is fully open (not mid-close) the wheel is hidden, so the
        // deck spring can idle. Otherwise idle only once the spring has come to
        // rest and nothing is in motion.
        if (open !== null && !closing) {
            return true;
        }
        return (
            Math.abs(motion.T - motion.A) < 1e-3 &&
            motion.spread > 0.999 &&
            !dragging &&
            !closing
        );
    }

    // Per-frame wheel transform (TECHNICAL-SPEC section 3), written straight onto
    // the deck nodes. Under reduced motion the spring is skipped (snap to target).
    function frame(): void {
        const cfg = feel;
        if (reduce) {
            motion.A = motion.T;
            motion.spread = 1;
        } else {
            motion.A += (motion.T - motion.A) * (dragging ? 0.4 : follow);
            motion.spread += (1 - motion.spread) * spreadRate;
        }
        const spRad = (cfg.sp * Math.PI) / 180;
        const maxRad = (cfg.maxPhi * Math.PI) / 180;
        for (let i = 0; i < n; i++) {
            const el = deckEls[i];
            if (!el) {
                continue;
            }
            const off = wrapOff(i - motion.A);
            let phi = off * spRad * motion.spread;
            phi = Math.max(-maxRad, Math.min(maxRad, phi));
            const d = Math.abs(off) * motion.spread;
            const dx = cfg.R * Math.sin(phi);
            const dz =
                cfg.R * (Math.cos(phi) - 1) -
                cfg.push * d +
                cfg.fwd * Math.sin(Math.PI * Math.min(d, 1));
            const rot = (phi * cfg.rotK * 180) / Math.PI;
            const op = Math.max(0, Math.min(1, 1 - cfg.dim * (d - 1)));
            el.style.transform = `translate(-50%, -50%) translate3d(${dx.toFixed(2)}px, 0px, ${dz.toFixed(2)}px) rotateY(${rot.toFixed(3)}deg)`;
            el.style.zIndex = String(1000 - Math.round(d * 100));
            el.style.opacity = op.toFixed(3);
            el.style.pointerEvents = op < 0.08 ? "none" : "auto";
        }
        const s = selIndex();
        if (s !== sel) {
            sel = s;
        }
        if (settled()) {
            running = false;
            return;
        }
        rafId = requestAnimationFrame(frame);
    }

    function snapT(): void {
        motion.T = Math.round(motion.T);
        ensureRaf();
    }

    function pxPerIndex(): number {
        const ppi = (feel.R * feel.sp * Math.PI) / 180;
        // Lighter swipe on phone: the one-up geometry has a large step, so a
        // full-width drag would be needed at 1:1. Scale it down so a flick
        // advances one set. Desktop drag stays 1:1 with the geometry.
        return narrow ? ppi * 0.6 : ppi;
    }

    function onWheelInput(e: WheelEvent): void {
        if (open !== null) {
            return;
        }
        e.preventDefault();
        motion.T += (e.deltaY + e.deltaX) * 0.0032;
        clearTimeout(wheelTimer);
        wheelTimer = window.setTimeout(snapT, 150);
        ensureRaf();
    }

    function stageDown(e: PointerEvent): void {
        if (open !== null) {
            return;
        }
        drag = { x: e.clientX, T: motion.T };
        moved = false;
        dragging = true;
        ensureRaf();
    }

    function onMove(e: PointerEvent): void {
        if (!drag) {
            return;
        }
        const dx = e.clientX - drag.x;
        if (Math.abs(dx) > 6) {
            moved = true;
        }
        motion.T = drag.T - dx / pxPerIndex();
        ensureRaf();
    }

    function onUp(): void {
        if (!drag) {
            return;
        }
        drag = null;
        snapT();
        dragging = false;
        // Let the suppressed click pass before clearing the drag flag.
        window.setTimeout(() => {
            moved = false;
        }, 80);
    }

    function onKey(e: KeyboardEvent): void {
        if (e.key === "Escape" && open !== null) {
            // Esc closes the composer first, then the grid (TECHNICAL-SPEC §7).
            if (adding) {
                cancelAdd();
            } else {
                closeGrid();
            }
            return;
        }
        if (open !== null) {
            return;
        }
        if (e.key === "ArrowRight") {
            motion.T = Math.round(motion.T) + 1;
            ensureRaf();
        } else if (e.key === "ArrowLeft") {
            motion.T = Math.round(motion.T) - 1;
            ensureRaf();
        }
    }

    function hoverDeck(i: number): void {
        hovered = i;
        ensureRaf();
    }

    function deckClick(i: number): void {
        if (moved || open !== null) {
            return;
        }
        if (i !== sel) {
            motion.T = Math.round(motion.T) + wrapOff(i - sel);
            ensureRaf();
        } else {
            void openSet(i);
        }
    }

    function deckKey(e: KeyboardEvent, i: number): void {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            deckClick(i);
        }
    }

    function goTo(i: number): void {
        if (open !== null) {
            return;
        }
        motion.T = Math.round(motion.T) + wrapOff(i - selIndex());
        ensureRaf();
    }

    function peek(i: number, k: number): string {
        const isHover = hovered === i && sel === i && open === null;
        return (isHover ? PEEK : BASE)[k];
    }

    async function openSet(k: number): Promise<void> {
        if (open !== null) {
            return;
        }
        open = k;
        closing = false;
        adding = false;
        addFront = "";
        addBack = "";
        await tick();
        if (!reduce) {
            flyIn();
        }
    }

    function deckCenter(): { x: number; y: number } | null {
        const idx = open !== null ? open : sel;
        const el = deckEls[idx];
        if (!el) {
            return null;
        }
        const r = el.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }

    function gridCellEls(): HTMLElement[] {
        // Every dealt cell, including the add tile / composer, so they fly with
        // the cards (TECHNICAL-SPEC §7/§8).
        return gridEl
            ? Array.from(gridEl.querySelectorAll<HTMLElement>(".grid-cell"))
            : [];
    }

    // Whether a cell is currently within the scroll viewport. The deal and the
    // collect only animate cells you can actually see, so a 60-card set costs the
    // same as a handful: off-screen cells are placed (or cleared) instantly.
    function inView(el: HTMLElement): boolean {
        if (!scrollEl) {
            return true;
        }
        const vr = scrollEl.getBoundingClientRect();
        const r = el.getBoundingClientRect();
        return r.bottom > vr.top - 4 && r.top < vr.bottom + 4;
    }

    // Split cells into on-screen and off-screen. Visibility must be sampled
    // before any transform is applied, since moving a cell changes its rect.
    function partitionByView(els: HTMLElement[]): {
        seen: HTMLElement[];
        rest: HTMLElement[];
    } {
        const seen: HTMLElement[] = [];
        const rest: HTMLElement[] = [];
        for (const el of els) {
            (inView(el) ? seen : rest).push(el);
        }
        return { seen, rest };
    }

    async function startAdd(): Promise<void> {
        adding = true;
        await tick();
        frontEl?.focus();
    }

    function cancelAdd(): void {
        adding = false;
        addFront = "";
        addBack = "";
    }

    async function submitAdd(): Promise<void> {
        const front = addFront.trim();
        // Empty front: refocus, do not submit (matches the reference).
        if (!front) {
            frontEl?.focus();
            return;
        }
        if (!openSetData || !onAddCard || addBusy) {
            return;
        }
        addBusy = true;
        try {
            // The surface persists it and appends to the set; the new card then
            // appears in the grid and the counts update reactively.
            await onAddCard(openSetData.category, front, addBack.trim());
            adding = false;
            addFront = "";
            addBack = "";
        } finally {
            addBusy = false;
        }
    }

    // Deal the cards out of the centered stack into the grid (TECHNICAL-SPEC
    // section 7): each card starts at the deck center, scattered and shrunk, then
    // releases to its slot with a staggered spring.
    function flyIn(): void {
        const c = deckCenter();
        if (!c) {
            return;
        }
        // Sample visibility first, then only deal the on-screen cells; the rest
        // sit ready below the fold.
        const { seen, rest } = partitionByView(gridCellEls());
        for (const el of rest) {
            el.style.transition = "none";
            el.style.transform = "none";
            el.style.opacity = "1";
        }
        seen.forEach((el, i) => {
            const r = el.getBoundingClientRect();
            const dx = c.x - (r.left + r.width / 2);
            const dy = c.y - (r.top + r.height / 2);
            const scatter = (((i * 37) % 9) - 4) * 1.6;
            el.style.transition = "none";
            el.style.transform = `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px) rotate(${scatter.toFixed(1)}deg) scale(0.82)`;
            el.style.opacity = "0";
        });
        if (seen[0]) {
            void seen[0].offsetHeight; // force reflow so the from-state commits
        }
        seen.forEach((el, i) => {
            el.style.transition = `transform 460ms var(--ease-spring) ${i * 14}ms, opacity 300ms ease ${i * 14 + 40}ms`;
            el.style.transform = "none";
            el.style.opacity = "1";
        });
    }

    function closeGrid(): void {
        if (open === null || closing) {
            return;
        }
        if (reduce) {
            open = null;
            closing = false;
            adding = false;
            return;
        }
        closing = true;
        ensureRaf();
        void closeFlyBack();
    }

    // Reverse of the deal: the on-screen cards gather back into the stack while
    // the wheel fades in beneath them, then the grid unmounts. Off-screen cards
    // are dropped at once, so the collect stays short (and in step with the wheel
    // reveal) no matter how many cards the set holds.
    async function closeFlyBack(): Promise<void> {
        await tick();
        const c = deckCenter();
        const { seen, rest } = partitionByView(gridCellEls());
        for (const el of rest) {
            el.style.transition = "none";
            el.style.opacity = "0";
        }
        const DUR = 280;
        const STAG = 6;
        seen.forEach((el, i) => {
            const r = el.getBoundingClientRect();
            const dx = c ? c.x - (r.left + r.width / 2) : 0;
            const dy = c ? c.y - (r.top + r.height / 2) : 0;
            const delay = i * STAG;
            const scatter = (((i * 29) % 7) - 3) * 1.6;
            el.style.transition = `transform ${DUR}ms var(--ease-spring) ${delay}ms, opacity ${Math.round(DUR * 0.7)}ms ease ${delay}ms`;
            el.style.transform = `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px) rotate(${scatter.toFixed(1)}deg) scale(0.8)`;
            el.style.opacity = "0";
        });
        clearTimeout(closeTimer);
        const total = DUR + Math.max(0, seen.length - 1) * STAG + 60;
        closeTimer = window.setTimeout(() => {
            open = null;
            closing = false;
            adding = false;
        }, total);
    }

    function studyOpen(): void {
        if (openSetData && onStudySet) {
            onStudySet(openSetData.category);
        }
    }

    onMount(() => {
        const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
        systemReduce = mq.matches;
        const onMq = (): void => {
            systemReduce = mq.matches;
            ensureRaf();
        };
        mq.addEventListener("change", onMq);

        // Phone breakpoint (matches the app rail-drawer): switch to the one-up
        // PHONE geometry and re-run the loop so the layout re-flows.
        const mqNarrow = window.matchMedia("(max-width: 640px)");
        narrow = mqNarrow.matches;
        const onNarrow = (): void => {
            narrow = mqNarrow.matches;
            ensureRaf();
        };
        mqNarrow.addEventListener("change", onNarrow);

        ensureRaf();
        return () => {
            mq.removeEventListener("change", onMq);
            mqNarrow.removeEventListener("change", onNarrow);
            if (rafId) {
                cancelAnimationFrame(rafId);
            }
            running = false;
            clearTimeout(wheelTimer);
            clearTimeout(closeTimer);
        };
    });
</script>

<svelte:window on:pointermove={onMove} on:pointerup={onUp} on:keydown={onKey} />

<div class="wheel-frame" class:reduced={reduce}>
    {#if n === 0}
        <div class="empty">
            <h1>Your sets</h1>
            <p>
                No card sets yet. Seed the sample content or author a card, and your
                topics will appear here to browse.
            </p>
        </div>
    {:else}
        <!-- Wheel layer -->
        <div
            class="wheel-layer"
            class:hidden={open !== null && !closing}
            class:revealing={closing}
        >
            <header class="wheel-head">
                <h1>Your sets</h1>
                <p class="subline">
                    {n}
                    {n === 1 ? "topic" : "topics"}, {totalCards} cards. Scroll or drag, click
                    the front set to open it.
                </p>
            </header>

            <!-- The stage is a custom drag/scroll surface; its interactive parts
                 (decks, dots) carry their own roles and labels. -->
            <div
                class="stage"
                bind:this={stageEl}
                role="group"
                aria-label="Card sets carousel"
                style="cursor: {dragging ? 'grabbing' : 'grab'};"
                on:pointerdown={stageDown}
                on:wheel|nonpassive={onWheelInput}
            >
                {#each sets as s, i (s.category)}
                    <div class="deck-wrap" bind:this={deckEls[i]}>
                        <div
                            class="deck"
                            role="button"
                            tabindex={i === sel ? 0 : -1}
                            aria-label={`${s.name}, ${s.cards.length} ${s.cards.length === 1 ? "card" : "cards"}`}
                            on:click={() => deckClick(i)}
                            on:keydown={(e) => deckKey(e, i)}
                            on:mouseenter={() => hoverDeck(i)}
                            on:mouseleave={() => (hovered = -1)}
                        >
                            <div class="back" style="transform: {peek(i, 2)};"></div>
                            <div class="back" style="transform: {peek(i, 1)};"></div>
                            <div class="back" style="transform: {peek(i, 0)};"></div>
                            <div
                                class="front"
                                class:hovered={hovered === i &&
                                    sel === i &&
                                    open === null}
                            >
                                <span class="deck-label">{s.name}</span>
                                <div class="deck-preview">
                                    <p>{@html renderMath(s.cards[0]?.front ?? "")}</p>
                                </div>
                                <div class="deck-foot">
                                    <span class="deck-count">
                                        {s.cards.length}
                                        {s.cards.length === 1 ? "card" : "cards"}
                                    </span>
                                    {#if i === sel && open === null}
                                        <span class="deck-open">Click to open</span>
                                    {/if}
                                </div>
                            </div>
                        </div>
                    </div>
                {/each}
            </div>

            <div class="dots">
                {#each sets as s, i (s.category)}
                    <button
                        class="dot-btn"
                        aria-label={`Go to ${s.name}`}
                        on:click={() => goTo(i)}
                    >
                        <span class="dot" class:active={i === sel}></span>
                    </button>
                {/each}
            </div>
        </div>

        <!-- Opened set grid -->
        {#if open !== null}
            <div class="grid-layer" class:closing>
                <div class="grid-chrome">
                    <button class="back-pill" on:click={closeGrid}>
                        <svg
                            width="14"
                            height="14"
                            viewBox="0 0 16 16"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="1.5"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            aria-hidden="true"
                        >
                            <line x1="13" y1="8" x2="3" y2="8" />
                            <polyline points="7,4 3,8 7,12" />
                        </svg>
                        All sets
                    </button>
                    <div class="grid-title">
                        <h2>{openName}</h2>
                        <p class="grid-sub">
                            <span class="count">{openCount}</span>
                            cards. Esc returns you to your sets.
                        </p>
                    </div>
                    {#if onStudySet}
                        <button class="study-btn" on:click={studyOpen}>
                            Study this set
                        </button>
                    {/if}
                </div>
                <div class="grid-scroll" bind:this={scrollEl}>
                    <div class="grid" bind:this={gridEl}>
                        {#each openCards as c, i (c.note_id ?? i)}
                            <article class="grid-cell grid-card">
                                <p>{@html renderMath(c.front)}</p>
                            </article>
                        {/each}
                        {#if onAddCard}
                            {#if adding}
                                <div class="grid-cell composer">
                                    <textarea
                                        bind:this={frontEl}
                                        bind:value={addFront}
                                        rows="2"
                                        placeholder="Front. Write it in your own words."
                                    ></textarea>
                                    <textarea
                                        bind:value={addBack}
                                        rows="1"
                                        placeholder="Back. The answer, stated plainly."
                                    ></textarea>
                                    <div class="composer-foot">
                                        <button
                                            type="button"
                                            class="composer-cancel"
                                            on:click={cancelAdd}
                                        >
                                            Cancel
                                        </button>
                                        <button
                                            type="button"
                                            class="composer-add"
                                            on:click={submitAdd}
                                            disabled={addBusy}
                                        >
                                            Add card
                                        </button>
                                    </div>
                                </div>
                            {:else}
                                <button
                                    type="button"
                                    class="grid-cell add-tile"
                                    on:click={startAdd}
                                >
                                    <svg
                                        width="18"
                                        height="18"
                                        viewBox="0 0 16 16"
                                        fill="none"
                                        stroke="currentColor"
                                        stroke-width="1.5"
                                        stroke-linecap="round"
                                        aria-hidden="true"
                                    >
                                        <line x1="8" y1="2.5" x2="8" y2="13.5" />
                                        <line x1="2.5" y1="8" x2="13.5" y2="8" />
                                    </svg>
                                    Add a card
                                </button>
                            {/if}
                        {/if}
                    </div>
                </div>
            </div>
        {/if}
    {/if}
</div>

<style lang="scss">
    /* Fills its parent, which owns the height: the Library gives it the full
       surface (100dvh); the dev gallery bounds it in a framed panel. */
    .wheel-frame {
        position: relative;
        display: flex;
        flex-direction: column;
        height: 100%;
        overflow: hidden;
        background: var(--canvas);
        color: var(--text);
        font-family: var(--font-ui);
    }

    /* Empty state: calm, never a broken carousel. */
    .empty {
        margin: auto;
        max-width: 42ch;
        padding: var(--space-6) var(--space-4);
        text-align: center;

        h1 {
            margin: 0 0 var(--space-1);
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        p {
            margin: 0;
            font-size: var(--text-body);
            line-height: 1.6;
            color: var(--muted);
        }
    }

    /* Wheel layer fades/shrinks behind the opened grid. On close it fades back in
       after a short delay so it lands in step with the cards gathering into the
       stack, rather than appearing while they are still collecting. */
    .wheel-layer {
        position: absolute;
        inset: 0;
        display: flex;
        flex-direction: column;
        opacity: 1;
        transform: scale(1);
        transition:
            opacity 300ms var(--ease-spring),
            transform 300ms var(--ease-spring);

        &.hidden {
            opacity: 0;
            transform: scale(0.965);
            pointer-events: none;
        }

        &.revealing {
            transition-delay: 90ms;
        }
    }

    .wheel-head {
        padding: 26px 44px 0;
        position: relative;
        z-index: 2;

        h1 {
            margin: 0;
            font-size: var(--text-title);
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        .subline {
            margin: 8px 0 0;
            font-size: var(--text-body);
            color: var(--muted);
        }
    }

    /* Stage: perspective applies per deck; the stage itself is NOT preserve-3d,
       so sibling overlap is controlled by the per-frame z-index. */
    .stage {
        flex: 1 1 auto;
        position: relative;
        z-index: 1;
        touch-action: none;
        user-select: none;
        -webkit-user-select: none;
        perspective: 1500px;
        perspective-origin: 50% 45%;
    }

    .deck-wrap {
        position: absolute;
        left: 50%;
        top: 52%;
        /* 300px on desktop; shrinks to fit narrow phones so the centered set
           always has a margin and reads as one-up. */
        width: min(300px, calc(100vw - 44px));
        height: 380px;
        transform: translate(-50%, -50%);
        transform-style: preserve-3d;
        will-change: transform;
    }

    .deck {
        position: relative;
        width: 100%;
        height: 100%;
        cursor: pointer;
        transform-style: preserve-3d;

        &:focus-visible {
            outline: none;
        }

        &:focus-visible .front {
            border-color: var(--muted);
        }
    }

    .back {
        position: absolute;
        inset: 0;
        background: var(--elevated);
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        transition: transform 280ms var(--ease-spring);
    }

    .front {
        position: absolute;
        inset: 0;
        display: flex;
        flex-direction: column;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        padding: 22px 24px;
        box-shadow: var(--shadow-card);
        transition:
            border-color 240ms var(--ease-spring),
            transform 240ms var(--ease-spring);

        &.hovered {
            border-color: var(--muted);
            transform: translateY(-3px);
        }
    }

    .deck-label {
        font-size: var(--text-caption);
        font-weight: 500;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
    }

    .deck-preview {
        flex: 1 1 auto;
        display: flex;
        align-items: center;
        min-height: 0;

        p {
            margin: 0;
            font-size: 15px;
            line-height: 1.55;
            display: -webkit-box;
            -webkit-line-clamp: 5;
            line-clamp: 5;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
    }

    .deck-foot {
        display: flex;
        align-items: center;
        justify-content: space-between;
    }

    .deck-count {
        font-family: var(--font-mono);
        font-size: var(--text-small);
        color: var(--muted);
        font-variant-numeric: tabular-nums;
    }

    .deck-open {
        font-size: var(--text-small);
        color: var(--muted);
    }

    .dots {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
        padding: 0 0 30px;
        position: relative;
        z-index: 2;
    }

    .dot-btn {
        width: 20px;
        height: 20px;
        padding: 0;
        background: none;
        border: none;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;

        /* No square hit-area box; the affordance lives on the dot itself. */
        &:focus {
            outline: none;
        }

        &:focus-visible .dot {
            box-shadow: 0 0 0 3px var(--focus-ring);
        }

        &:hover .dot {
            background: var(--text);
        }
    }

    .dot {
        width: 6px;
        height: 6px;
        border-radius: var(--radius-pill);
        background: var(--muted);
        transform: scale(1);
        transition:
            background 240ms var(--ease-spring),
            box-shadow 240ms var(--ease-spring),
            transform 240ms var(--ease-spring);

        &.active {
            background: var(--text);
            transform: scale(1.3);
        }
    }

    /* Opened grid overlays the wheel. */
    .grid-layer {
        position: absolute;
        inset: 0;
        z-index: 10;
        display: flex;
        flex-direction: column;

        &.closing {
            pointer-events: none;
        }
    }

    .grid-chrome {
        display: flex;
        align-items: center;
        gap: 20px;
        padding: 30px 64px 22px;
        transition: opacity 220ms ease;

        .grid-layer.closing & {
            opacity: 0;
        }
    }

    .back-pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: none;
        border: 1px solid var(--border);
        border-radius: var(--radius-control);
        padding: 9px 14px 9px 11px;
        color: var(--muted);
        font-family: var(--font-ui);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition:
            border-color 240ms var(--ease-spring),
            color 240ms var(--ease-spring);

        &:hover {
            border-color: var(--muted);
            color: var(--text);
        }
    }

    .grid-title {
        flex: 1 1 auto;
        min-width: 0;

        h2 {
            margin: 0;
            font-size: 22px;
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        .grid-sub {
            margin: 5px 0 0;
            font-size: 13px;
            color: var(--muted);

            .count {
                font-family: var(--font-mono);
                font-variant-numeric: tabular-nums;
            }
        }
    }

    .study-btn {
        flex: 0 0 auto;
        background: var(--action-bg);
        color: var(--action-fg);
        border: none;
        border-radius: var(--radius-control);
        padding: 11px 22px;
        font-family: var(--font-ui);
        font-size: var(--text-body);
        font-weight: 500;
        cursor: pointer;
        transition: background 240ms var(--ease-spring);

        &:hover {
            background: var(--action-bg-hover);
        }
    }

    .grid-scroll {
        flex: 1 1 auto;
        overflow-y: auto;
        padding: 6px 64px 44px;
    }

    .grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 14px;
        width: 100%;
        max-width: 1240px;
        margin: 0 auto;
    }

    /* Every dealt cell (card, add tile, composer) animates during the deal. */
    .grid-cell {
        will-change: transform;
    }

    .grid-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 18px 20px;
        min-height: 136px;
        box-shadow: var(--shadow-card);
        transition: border-color 240ms var(--ease-spring);

        &:hover {
            border-color: var(--muted);
        }

        p {
            margin: 0;
            font-size: var(--text-body);
            line-height: 1.6;
        }
    }

    /* Add-a-card: a dashed tile that becomes an inline front/back composer
       (TECHNICAL-SPEC §8). Author-as-is, no AI. */
    .add-tile {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 10px;
        min-height: 136px;
        background: none;
        border: 1px dashed var(--border);
        border-radius: 14px;
        color: var(--muted);
        font-family: var(--font-ui);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition:
            border-color 240ms var(--ease-spring),
            color 240ms var(--ease-spring);

        &:hover {
            border-color: var(--muted);
            color: var(--text);
        }
    }

    .composer {
        display: flex;
        flex-direction: column;
        gap: 8px;
        min-height: 136px;
        padding: 12px;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 14px;

        textarea {
            width: 100%;
            background: var(--elevated);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 9px 11px;
            font-family: var(--font-ui);
            font-size: 13px;
            line-height: 1.5;
            color: var(--text);
            resize: none;
            outline: none;
            transition: border-color 240ms var(--ease-spring);

            &::placeholder {
                color: var(--muted);
            }

            &:focus {
                border-color: var(--text);
            }
        }
    }

    .composer-foot {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 8px;
        margin-top: auto;
    }

    .composer-cancel {
        background: none;
        border: none;
        border-radius: 8px;
        padding: 8px 12px;
        color: var(--muted);
        font-family: var(--font-ui);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: color 240ms var(--ease-spring);

        &:hover {
            color: var(--text);
        }
    }

    .composer-add {
        background: none;
        border: 1px solid var(--muted);
        border-radius: 8px;
        padding: 8px 14px;
        color: var(--text);
        font-family: var(--font-ui);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: border-color 240ms var(--ease-spring);

        &:hover:not(:disabled) {
            border-color: var(--text);
        }

        &:disabled {
            opacity: 0.55;
            cursor: default;
        }
    }

    /* Reduced motion: no fade/scale on the wheel layer; the spring and the deal
       are already skipped in JS. Cards simply appear and disappear in place. */
    @media (prefers-reduced-motion: reduce) {
        .wheel-layer,
        .back,
        .front,
        .dot,
        .grid-chrome,
        .grid-card {
            transition: none;
        }
    }

    /* Phone: the wheel becomes a one-up carousel (PHONE geometry in JS). Tighten
       the chrome so the stage gets the height, and drop the grid to one column so
       an opened set reads as a simple scroll. */
    @media (max-width: 640px) {
        /* Clear the shell's floating menu button (fixed top-left) so it never
           overlaps the header. */
        .wheel-head {
            padding: 16px 20px 0 62px;
        }

        .wheel-head h1 {
            font-size: 20px;
        }

        .wheel-head .subline {
            margin-top: 4px;
            font-size: var(--text-small);
        }

        .dots {
            padding-bottom: 18px;
        }

        .grid-chrome {
            padding: 16px 18px 14px;
            gap: 12px;
        }

        .grid-title h2 {
            font-size: 18px;
        }

        .study-btn {
            padding: 9px 14px;
        }

        .grid-scroll {
            padding: 6px 18px 28px;
        }

        .grid {
            grid-template-columns: 1fr;
        }
    }
</style>
