// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

/**
 * Strip em and en dashes to hold the pgrep voice (no em-dashes; ranges read
 * "68 to 77"). AI-generated content and model feedback often slip dashes in
 * despite the prompt, so surfaces run their displayed text through this.
 *
 * A dash between two numbers becomes " to " (a range); every other em, en,
 * figure, or bar dash becomes a comma, matching "use a comma or a period".
 */
export function noDashes(s: string): string {
    if (!s) {
        return s;
    }
    return s
        .replace(/(\d)\s*[\u2012\u2013\u2014\u2015]\s*(\d)/g, "$1 to $2")
        .replace(/\s*[\u2012\u2014\u2015]\s*/g, ", ")
        .replace(/\s*\u2013\s*/g, ", ");
}
