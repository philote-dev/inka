// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// pgrep nav shell state. The left rail collapses on its own in two cases: when a
// surface enters a focused learning mode (a study session, a running exam, the
// diagnostic), and when the viewport is at phone width, where a fixed 216px rail
// would crowd the content off the screen. When collapsed a top-left button and a
// left-edge handle bring it back; on phone it returns as an overlay drawer.
//
// Surfaces own their own "am I learning" truth and call setLearning at the
// transitions, rather than the shell guessing from the URL, because the study
// session runs inline on /pgrep/study (a screen state, not its own route). The
// shell owns the "am I narrow" truth and calls setNarrow from a matchMedia
// listener.

import { derived, get, writable } from "svelte/store";

// True while a surface is in a focused learning mode.
export const learning = writable(false);

// True while the viewport is at phone width (see the layout's matchMedia wiring).
export const narrow = writable(false);

// A manual override of the rail's open state. null defers to the auto signals;
// true or false pins the rail until the next learning or width transition.
const railOverride = writable<boolean | null>(null);

// The effective rail state. A manual override wins; otherwise the rail is open
// unless a learning surface or a phone-width viewport has collapsed it.
export const railOpen = derived(
    [learning, narrow, railOverride],
    ([$learning, $narrow, $override]) => $override ?? !($learning || $narrow),
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

// Cross the phone-width boundary. Like setLearning, a real change clears any
// manual override so each width regime starts from its honest default (collapsed
// on phone, open on wider screens) rather than carrying a pinned state across.
export function setNarrow(value: boolean): void {
    if (get(narrow) !== value) {
        railOverride.set(null);
    }
    narrow.set(value);
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
