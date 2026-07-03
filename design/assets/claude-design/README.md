# Claude Design exports (drop zone)

This folder is where the Claude Design output lands before it becomes Svelte in `ts/`.
The agent reconciles whatever is here against `ux-foundation.md` and builds from it.

## What to export from Claude Design and put here

Grab as much of this as Claude Design lets you, most useful first:

1. **Screens and components as images** (PNG or, better, SVG). This is the visual spec.
   Suggested subfolder: `screens/` and `components/`.
2. **Design tokens**, if exportable (JSON or CSS variables for colors, type, spacing).
   Suggested subfolder: `tokens/`.
3. **Vector assets** (the logo, any icons) as SVG. Suggested subfolder: `assets/`.
4. **Optional, the Send to Claude Code handoff bundle** or spec file, if you can save it to disk.
   Suggested subfolder: `handoff/`.

## After you drop the files

Tell the agent. It will:
- inventory what arrived,
- reconcile tokens and components with `ux-foundation.md` (flag any drift),
- then proceed with the build steps in `frontend-execution-guide.md`.

Notes:
- The React or Tailwind code from a handoff bundle is not used directly (pgrep is Svelte plus SCSS). The tokens, the component spec, and the assets are what we use.
- If you cannot export cleanly, that is fine. We can build faithfully from `ux-foundation.md` plus the reference PNGs in `../ux/`.
