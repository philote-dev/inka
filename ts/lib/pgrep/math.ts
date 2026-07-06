// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

// Real math typesetting for the pgrep surfaces, using the MathJax build the app
// already ships (the same one Anki's reviewer uses). MathJax renders proper
// LaTeX: aligned fractions, radicals, Greek, everything. The card and problem
// content carries delimited LaTeX (\( ... \) inline, \[ ... \] display), and we
// turn each delimited span into an inline SVG. tex2svg is synchronous and needs
// no DOM scan, so there is no reflow flash and no typeset race.
//
// pgrep is client-only (ssr = false), so importing the bundle for its side
// effect of setting up globalThis.MathJax is safe.
import "mathjax/es5/tex-svg-full";

function mathjax(): { tex2svg(tex: string, opts: { display: boolean }): Element } | null {
    const mj = (globalThis as { MathJax?: any }).MathJax;
    return mj && typeof mj.tex2svg === "function" ? mj : null;
}

// MathJax wants raw LaTeX; card HTML may carry a few escaped entities inside the
// math, so undo the ones that matter before typesetting.
function unescape(tex: string): string {
    return tex
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&amp;/g, "&");
}

function toSvg(tex: string, display: boolean): string {
    const mj = mathjax();
    if (!mj) {
        return tex;
    }
    try {
        const container = mj.tex2svg(unescape(tex), { display });
        const svg = container.querySelector("svg");
        return svg ? svg.outerHTML : tex;
    } catch {
        return tex;
    }
}

// Replace \[ ... \] (display) and \( ... \) (inline) LaTeX spans in an HTML
// fragment with typeset SVG. Everything outside the delimiters, including the
// surrounding markup and prose, is left untouched.
export function renderMath(html: string): string {
    if (!html || !mathjax()) {
        return html;
    }
    return html
        .replace(
            /\\\[([\s\S]+?)\\\]/g,
            (_m, tex: string) => `<span class="m-block">${toSvg(tex, true)}</span>`,
        )
        .replace(
            /\\\(([\s\S]+?)\\\)/g,
            (_m, tex: string) => `<span class="m-inline">${toSvg(tex, false)}</span>`,
        );
}
