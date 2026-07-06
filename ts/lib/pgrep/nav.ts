// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// pgrep nav shell state. The left rail collapses on its own whenever a surface
// enters a focused learning mode (a study session, a running exam, the
// diagnostic), so the content gets the full width. When collapsed a top-left
// button and a left-edge handle bring it back. Leaving learning restores it.
//
// Surfaces own their own "am I learning" truth and call setLearning at the
// transitions, rather than the shell guessing from the URL, because the study
// session runs inline on /pgrep/study (a screen state, not its own route).

import { derived, get, writable } from "svelte/store";

// True while a surface is in a focused learning mode.
export const learning = writable(false);

// A manual override of the rail's open state. null defers to the learning
// signal; true or false pins the rail until the next learning transition.
const railOverride = writable<boolean | null>(null);

// The effective rail state. A manual override wins; otherwise the rail is open
// unless a learning surface has collapsed it.
export const railOpen = derived(
    [learning, railOverride],
    ([$learning, $override]) => $override ?? !$learning,
);

// Enter or leave a focused learning mode. A real change clears any manual
// override so each context starts from the honest auto default (collapsed while
// learning, open otherwise).
export function setLearning(value: boolean): void {
    if (get(learning) !== value) {
        railOverride.set(null);
    }
    learning.set(value);
}

// Restore the rail (the top-left button and the edge handle).
export function openRail(): void {
    railOverride.set(true);
}

// Collapse the rail (the in-rail chevron).
export function closeRail(): void {
    railOverride.set(false);
}

// Flip the rail from its current effective state.
export function toggleRail(): void {
    railOverride.set(!get(railOpen));
}
