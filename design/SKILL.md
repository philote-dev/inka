---
name: pgrep-design
description: Use this skill to generate well-branded interfaces and assets for pgrep, a Physics GRE study app, either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read `readme.md` (the brand system) and `ux-foundation.md` (the authoritative UX spec) in this folder, and study the live implementation in the repo: tokens in `ts/lib/sass/_pgrep.scss`, components in `ts/lib/components`, surfaces in `ts/routes/pgrep`. Reference renders live in `assets/reference/`.
If working on production code, follow those Svelte components and tokens so new surfaces match. If creating a throwaway visual artifact, build a static HTML file that reuses the same tokens and reserved color language.
If the user invokes this skill without other guidance, ask what they want to build or design, ask a few questions, and act as an expert designer who outputs production Svelte or a static HTML mock, depending on the need.

Non-negotiables when designing for pgrep. Amber, blue, and lilac are reserved for Memory, Performance, and Readiness data. Buttons and links are monochrome. Every score shows number, likely range, how sure, and last updated, or abstains and names what is missing. No em-dashes, no colon-heavy phrasing, no emoji, never flatter or punish. Numbers use tabular figures. Math is MathJax. Production is Svelte 5 with SCSS variables, dark via .night-mode.
