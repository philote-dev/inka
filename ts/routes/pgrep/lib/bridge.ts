// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

/**
 * The pgrep frontend to backend bridge (Channel B).
 *
 * POSTs a JSON body to a mediasrv pgrep handler and returns the parsed JSON.
 * Pages loaded in an AnkiWebView have the Authorization bearer token injected
 * automatically, and the "application/binary" content type is required to pass
 * mediasrv's permission check. See docs/pgrep/planning/l2-api-contract.md §1.
 */
export async function pgrepCall<T = any>(fn: string, args: unknown = {}): Promise<T> {
    const res = await fetch(`/_anki/${fn}`, {
        method: "POST",
        headers: { "Content-Type": "application/binary" },
        body: JSON.stringify(args),
    });
    if (!res.ok) {
        let message = `pgrep ${fn} failed`;
        try {
            message = await res.text();
        } catch {
            // keep the fallback message
        }
        throw new Error(`${res.status}: ${message}`);
    }
    return (await res.json()) as T;
}
