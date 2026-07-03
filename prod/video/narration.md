# pgrep concept walkthrough — narration and caption script

This is the script for `pgrep-concept-walkthrough-1080p.mp4` (built by
`record.mjs`). The video ships **silent with on-screen captions**, so it reads
fine with no audio. If you want a voiceover, read the **Voiceover** column at the
listed times, or generate it with TTS and mux it in (see the bottom of this
file).

**Honesty note.** This walkthrough is driven from the clickable prototype, not a
compiled build. The video carries a persistent "concept prototype" watermark and
an honest outro. It is a pitch and rehearsal aid, and a "just in case" backup. It
is **not** the graded Wednesday proof (those come from the real forked build, see
`submission-video-kit.md`).

Times are approximate for the ~3:00 render at `PACE=1.3`. Verify against the
final file and nudge if you re-time it.

| Time | Section | On-screen caption | Voiceover (optional) |
|---|---|---|---|
| 0:00 | Intro | pgrep. One engine, two apps, three honest scores. | pgrep is a Physics GRE study app built on the Anki engine. One engine, two apps, and three scores it can actually back up. |
| 0:07 | Home | Home. Your readiness at a glance. | Home is the honest instrument. The manifold shows performance as height, memory as glow, and gaps as holes. |
| 0:14 | Home | Memory is shown honestly. | Memory is a real number, with a likely range and how sure it is, not a bare figure. |
| 0:20 | Home | Performance and Readiness abstain. | Performance and Readiness have no evidence yet, so they abstain instead of guessing. |
| 0:27 | Home | One clear next step. | And one clear thing to do today. |
| 0:30 | Study | Two doors. Cards and Problems. | Study has two doors. Cards for memory, problems for performance, with topics interleaved inside each. |
| 0:42 | Cards | A real review loop. | The Cards door is a real spaced review loop on a Physics GRE deck. |
| 0:48 | Cards | Recall, check, then grade. | You recall, check, and grade. FSRS schedules the next review. |
| 1:00 | Problems | Commit before any help. | The Problems door makes you commit before any help. No confidence rating, no predict before you answer. |
| 1:08 | Problems | The wrong-answer ladder. | A wrong answer opens the ladder, one rung at a time. You write the sub-goal in your own words. |
| 1:16 | Problems | It reveals the step, never the answer. | It reveals the next step, never the final answer. Working it out yourself is the point. |
| 1:23 | Progress | Coverage gates readiness. | Progress is where honesty lives. Coverage is only 58 percent, so readiness abstains. |
| 1:31 | Progress | Model calibration, not a vibe. | Calibration is measured. A reliability diagram and a Brier score, so you know if the numbers can be trusted. |
| 1:38 | Library | With AI off, the app still works. | In the Library you author one seed by hand. With AI off, the app still works and every seed counts. |
| 1:46 | Library | AI on. Cited and gold-set gated. | With AI on, it conforms siblings in your style, each cited to a named source and checked against a gold set. |
| 1:55 | Exam | Exam mode. A full timed mock. | Exam mode is a full timed mock at real Physics GRE proportions, with zero help. |
| 2:08 | Mobile | The same engine, in your pocket. | The same Rust engine runs on the phone. Readiness at a glance, and a session that mirrors the desktop. |
| 2:23 | Theme | Light and dark are both first class. | Light and dark are both first class. |
| 2:30 | Outro | The Wednesday MVP. | For Wednesday, the proof is simple. |
| 2:34 | Outro | (checklist 01 to 05) | Forked Anki building from source. A real Rust engine change with tests. A desktop review loop and an honest Memory score. An installer on a clean machine. And the same engine running on a phone. |
| 2:52 | Outro | pgrep. An honest instrument for the Physics GRE. | pgrep. An honest instrument for the Physics GRE. |

## Adding a voiceover later

1. Record or TTS the lines above into `voice.wav` (aim to hit the listed times).
2. Optional music bed at low volume in `music.m4a`.
3. Mux onto the silent video:

```bash
# voice only
ffmpeg -i pgrep-concept-walkthrough-1080p.mp4 -i voice.wav \
  -c:v copy -c:a aac -b:a 192k -shortest pgrep-concept-narrated.mp4

# voice + music bed (music ducked to -18 dB)
ffmpeg -i pgrep-concept-walkthrough-1080p.mp4 -i voice.wav -i music.m4a \
  -filter_complex "[2:a]volume=-18dB[m];[1:a][m]amix=inputs=2:duration=first[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k pgrep-concept-narrated.mp4
```

## Re-timing

Total length is set by `PACE` in `record.mjs` (default here 1.3 gives about 3:00).
Raise it to slow the whole thing down, lower it to speed up, then re-run
`record.mjs` and `assemble.sh`.
