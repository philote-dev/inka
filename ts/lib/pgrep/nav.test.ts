// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import { get } from "svelte/store";
import { beforeEach, expect, test } from "vitest";

import {
    closeRail,
    learning,
    narrow,
    openRail,
    railOpen,
    requestReset,
    resetSignal,
    setLearning,
    setNarrow,
    toggleRail,
} from "./nav";

beforeEach(() => {
    // The stores are module state, so each test starts from the auto defaults.
    setLearning(false);
    setNarrow(false);
    openRail();
    setLearning(false);
});

test("the rail is open by default and collapses for the auto signals", () => {
    expect(get(railOpen)).toBe(true);

    setLearning(true);
    expect(get(railOpen)).toBe(false);

    setLearning(false);
    expect(get(railOpen)).toBe(true);

    setNarrow(true);
    expect(get(railOpen)).toBe(false);
});

test("a manual override beats the auto signals", () => {
    setLearning(true);
    openRail();
    expect(get(railOpen)).toBe(true);

    setLearning(false);
    closeRail();
    expect(get(railOpen)).toBe(false);
});

test("a real learning transition clears the override", () => {
    closeRail();
    expect(get(railOpen)).toBe(false);

    setLearning(true);
    expect(get(railOpen)).toBe(false); // auto default while learning

    setLearning(false);
    expect(get(railOpen)).toBe(true); // back to the open default
});

test("re-asserting the same state keeps a pinned rail", () => {
    setLearning(true);
    openRail();

    setLearning(true); // not a transition
    expect(get(railOpen)).toBe(true);

    setNarrow(false); // not a transition either
    expect(get(railOpen)).toBe(true);
});

test("a width transition clears the override the same way", () => {
    openRail();
    setNarrow(true);
    expect(get(railOpen)).toBe(false);

    setNarrow(false);
    expect(get(railOpen)).toBe(true);
});

test("toggle flips the effective state, including an auto-collapsed rail", () => {
    toggleRail();
    expect(get(railOpen)).toBe(false);

    toggleRail();
    expect(get(railOpen)).toBe(true);

    setLearning(true);
    toggleRail();
    expect(get(railOpen)).toBe(true);
});

test("the learning and narrow stores report the state surfaces set", () => {
    setLearning(true);
    setNarrow(true);
    expect(get(learning)).toBe(true);
    expect(get(narrow)).toBe(true);
});

test("each reset request is a distinct change a surface can watch", () => {
    const before = get(resetSignal);

    requestReset();
    requestReset();

    expect(get(resetSignal)).toBe(before + 2);
});
