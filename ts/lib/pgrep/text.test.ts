// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import { expect, test } from "vitest";

import { noDashes } from "./text";

test("a dash between numbers becomes a spoken range", () => {
    expect(noDashes("scores 68\u201377")).toBe("scores 68 to 77");
    expect(noDashes("scores 68 \u2014 77")).toBe("scores 68 to 77");
});

test("a dash between words becomes a comma", () => {
    expect(noDashes("honest\u2014and useful")).toBe("honest, and useful");
    expect(noDashes("honest \u2013 and useful")).toBe("honest, and useful");
});

test("figure and horizontal bar dashes are covered too", () => {
    expect(noDashes("a\u2012b")).toBe("a, b");
    expect(noDashes("a\u2015b")).toBe("a, b");
});

test("a hyphen is left alone", () => {
    expect(noDashes("well-known 3-4 split")).toBe("well-known 3-4 split");
});

test("empty input is returned unchanged", () => {
    expect(noDashes("")).toBe("");
});
