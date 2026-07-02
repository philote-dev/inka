// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! pgrep (Physics-GRE fork) "points at stake" review selector.
//!
//! Stock Anki orders review cards with an SQL `ORDER BY` at gather time and
//! applies the daily review limit *during* that SQL iteration. A naive
//! post-sort is therefore insufficient: the limit would already have cut the
//! "wrong" cards before we could score them.
//!
//! This module is the second half of a gather-then-limit pass. When a deck's
//! review order is [`ReviewCardOrder::PointsAtStake`], the gather step (see
//! `gathering.rs`) collects *all* non-buried due reviews; here we score them,
//! reorder within the due set, and truncate to exactly the daily review limit
//! stock Anki would have applied.
//!
//! Graded invariants:
//! - We only *reorder* the in-memory `Vec<DueCard>`. We never mutate `due`,
//!   `interval`, or `memory_state`, and never write collection data or create
//!   an undo entry. FSRS scheduling state is a read-only input to the scorer,
//!   so scheduling, undo, and sync are untouched.
//! - An untagged card (category `unknown`, blueprint 0) scores 0 and sorts
//!   last, but is never dropped beyond the normal daily truncation.
//!
//! [`ReviewCardOrder::PointsAtStake`]: crate::deckconfig::ReviewCardOrder

use std::cmp::Ordering;
use std::collections::HashMap;

use fsrs::FSRS;
use fsrs::FSRS5_DEFAULT_DECAY;

use super::DueCard;
use super::DueCardKind;
use super::QueueBuilder;
use crate::decks::limits::LimitKind;
use crate::prelude::*;
use crate::scheduler::timing::SchedTimingToday;
use crate::tags::split_tags;

/// Anti-blocking: never emit more than this many consecutive cards of the same
/// category, provided a different category is available to break the run.
const MAX_CONSECUTIVE_SAME_CATEGORY: usize = 3;
/// Score multiplier applied to cards outside the desirable-difficulty band.
const OUT_OF_BAND_FACTOR: f64 = 0.5;
/// Desirable-difficulty band, expressed as predicted retrievability R.
const IN_BAND_LOW: f64 = 0.60;
const IN_BAND_HIGH: f64 = 0.85;
/// Hierarchical topic tag prefix (matched case-insensitively).
const TOPIC_PREFIX: &str = "topic::";
/// Category assigned to cards with no (recognisable) topic tag.
const UNKNOWN_CATEGORY: &str = "unknown";

/// PGRE blueprint weight for a category, as a fraction (the official PGRE topic
/// percentages / 100). Per the L1 coordination contract this static table is
/// duplicated per language on purpose; do not factor it into a shared file.
fn blueprint_for_category(category: &str) -> f64 {
    match category {
        "mechanics" => 0.20,
        "electromagnetism" => 0.18,
        "quantum" => 0.13,
        "thermodynamics" => 0.10,
        "atomic" => 0.10,
        "optics_waves" => 0.08,
        "special_relativity" => 0.06,
        "lab" => 0.06,
        "specialized" => 0.09,
        _ => 0.0,
    }
}

/// Parse a note's tag string into its (finest topic, category) per the L1
/// contract: the first `topic::…` tag wins; category is its 2nd `::` segment.
/// Returns `(None, "unknown")` when there is no topic tag.
fn parse_topic(tags: &str) -> (Option<String>, String) {
    for tag in split_tags(tags) {
        let lower = tag.to_ascii_lowercase();
        if let Some(rest) = lower.strip_prefix(TOPIC_PREFIX) {
            let category = match rest.split("::").next() {
                Some(c) if !c.is_empty() => c.to_string(),
                _ => UNKNOWN_CATEGORY.to_string(),
            };
            return (Some(lower), category);
        }
    }
    (None, UNKNOWN_CATEGORY.to_string())
}

/// FSRS retrievability *now* for a card, or `None` when the card has no FSRS
/// memory state. Mirrors `stats::card` / the `extract_fsrs_retrievability` SQL
/// UDF exactly, but performs no writes (unlike `card_stats`, which may persist
/// a backfilled `last_review_time`).
fn card_retrievability(card: &Card, timing: SchedTimingToday) -> Option<f64> {
    let state = card.memory_state?;
    let now = timing.now.0;
    let due = if card.original_due != 0 {
        card.original_due
    } else {
        card.due
    };
    let ivl = card.interval;
    // These `as u32` casts (and the saturating_subs on them) mirror the SQL UDF
    // precisely; see the comment in storage::sqlite for why the cast must happen
    // before the subtraction.
    let seconds_elapsed = if let Some(last_review_time) = card.last_review_time {
        (now as u32).saturating_sub(last_review_time.0 as u32)
    } else if due > 365_000 {
        // (re)learning card with due stored in seconds
        let last_review_time = (due as u32).saturating_sub(ivl);
        (now as u32).saturating_sub(last_review_time)
    } else {
        let review_day = (due as u32).saturating_sub(ivl);
        timing.days_elapsed.saturating_sub(review_day) * 86_400
    };
    let decay = card.decay.unwrap_or(FSRS5_DEFAULT_DECAY);
    let r = FSRS::new(None).unwrap().current_retrievability_seconds(
        state.into(),
        seconds_elapsed,
        decay,
    );
    Some(r as f64)
}

/// True when retrievability sits within the desirable-difficulty band.
fn is_in_band(r: f64) -> bool {
    (IN_BAND_LOW..=IN_BAND_HIGH).contains(&r)
}

/// Band multiplier: 1.0 in-band, [`OUT_OF_BAND_FACTOR`] otherwise (including
/// when R is unknown).
fn band_factor(r: Option<f64>) -> f64 {
    match r {
        Some(r) if is_in_band(r) => 1.0,
        _ => OUT_OF_BAND_FACTOR,
    }
}

/// Per-card scoring inputs, kept independent of the collection so the scorer is
/// unit-testable without a full collection.
#[derive(Clone, Debug)]
struct ScoringInput {
    id: CardId,
    /// Original gather order; the primary deterministic tiebreak.
    gather_index: usize,
    category: String,
    /// Finest topic tag (weakness grouping key); `None` when untagged.
    topic: Option<String>,
    blueprint: f64,
    r: Option<f64>,
}

/// A scored card ready for greedy ordering.
#[derive(Clone, Debug)]
struct Scored {
    id: CardId,
    gather_index: usize,
    category: String,
    score: f64,
}

/// worth = blueprint% × weakness(topic). The "points at stake" for a card
/// before the band adjustment.
fn worth(blueprint: f64, weakness: f64) -> f64 {
    blueprint * weakness
}

/// weakness(topic) = 1 − mean(R over that topic's due cards). Only cards with a
/// defined R contribute; a topic with no defined R gets weakness 0 (we can't
/// call it weak). Computed once over the whole due set.
fn weakness_by_topic(inputs: &[ScoringInput]) -> HashMap<String, f64> {
    let mut sums: HashMap<&str, (f64, usize)> = HashMap::new();
    for inp in inputs {
        if let (Some(topic), Some(r)) = (inp.topic.as_deref(), inp.r) {
            let entry = sums.entry(topic).or_insert((0.0, 0));
            entry.0 += r;
            entry.1 += 1;
        }
    }
    sums.into_iter()
        .map(|(topic, (sum, count))| (topic.to_string(), 1.0 - sum / count as f64))
        .collect()
}

/// Score every card: worth = blueprint% × weakness(topic); score = worth ×
/// band factor.
fn score_inputs(inputs: &[ScoringInput]) -> Vec<Scored> {
    let weakness = weakness_by_topic(inputs);
    inputs
        .iter()
        .map(|inp| {
            let w = inp
                .topic
                .as_deref()
                .and_then(|t| weakness.get(t))
                .copied()
                .unwrap_or(0.0);
            let score = worth(inp.blueprint, w) * band_factor(inp.r);
            Scored {
                id: inp.id,
                gather_index: inp.gather_index,
                category: inp.category.clone(),
                score,
            }
        })
        .collect()
}

/// Would appending a card of `category` create a run longer than
/// [`MAX_CONSECUTIVE_SAME_CATEGORY`]?
fn would_block(ordered: &[Scored], category: &str) -> bool {
    ordered.len() >= MAX_CONSECUTIVE_SAME_CATEGORY
        && ordered
            .iter()
            .rev()
            .take(MAX_CONSECUTIVE_SAME_CATEGORY)
            .all(|s| s.category == category)
}

/// Greedy final ordering: repeatedly take the highest-scoring remaining card
/// whose append wouldn't exceed the anti-blocking run; if the best candidate
/// would, take the next best that wouldn't; if none avoids it, allow the best.
/// Ties break by gather order then card id (stable, deterministic).
fn greedy_order(mut scored: Vec<Scored>) -> Vec<Scored> {
    scored.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(Ordering::Equal)
            .then(a.gather_index.cmp(&b.gather_index))
            .then(a.id.cmp(&b.id))
    });
    let mut ordered: Vec<Scored> = Vec::with_capacity(scored.len());
    let mut remaining = scored;
    while !remaining.is_empty() {
        let pick = remaining
            .iter()
            .position(|s| !would_block(&ordered, &s.category))
            .unwrap_or(0);
        ordered.push(remaining.remove(pick));
    }
    ordered
}

impl QueueBuilder {
    /// Reorder `self.review` (all gathered due reviews) by points-at-stake,
    /// then select down to the daily limit. Read-only with respect to the
    /// collection.
    pub(super) fn sort_reviews_points_at_stake(&mut self, col: &mut Collection) -> Result<()> {
        if self.review.is_empty() {
            return Ok(());
        }
        let timing = self.context.timing;

        // Batch-load note tags for the gathered reviews (read-only). Sibling
        // cards share a note id, so dedupe first: the search_nids temp table
        // backing get_note_tags_by_id_list requires unique ids.
        let mut note_ids: Vec<NoteId> = self.review.iter().map(|c| c.note_id).collect();
        note_ids.sort_unstable();
        note_ids.dedup();
        let tags_by_note: HashMap<NoteId, String> = col
            .storage
            .get_note_tags_by_id_list(&note_ids)?
            .into_iter()
            .map(|nt| (nt.id, nt.tags))
            .collect();

        // Build scoring inputs. Retrievability is read straight from each card's
        // FSRS state; nothing is written back.
        let mut inputs = Vec::with_capacity(self.review.len());
        for (gather_index, due) in self.review.iter().enumerate() {
            let tags = tags_by_note
                .get(&due.note_id)
                .map(String::as_str)
                .unwrap_or("");
            let (topic, category) = parse_topic(tags);
            let blueprint = blueprint_for_category(&category);
            let card = col.storage.get_card(due.id)?.or_not_found(due.id)?;
            let r = card_retrievability(&card, timing);
            inputs.push(ScoringInput {
                id: due.id,
                gather_index,
                category,
                topic,
                blueprint,
                r,
            });
        }

        let ordered = greedy_order(score_inputs(&inputs));

        // Apply the daily limits and sibling burying in worth order, exactly as
        // stock Anki would during gather: honour the root + per-deck review
        // limits (including the way review decrements cap the shared new-card
        // limit) and bury same-note siblings, but keep the highest-worth cards
        // first. This yields the same review/new counts as stock while reordering
        // the due set. `by_id` maps back to the untouched DueCard values; the
        // DueCards themselves are never modified.
        let by_id: HashMap<CardId, DueCard> = self.review.iter().map(|c| (c.id, *c)).collect();
        let mut selected = Vec::with_capacity(ordered.len());
        for scored in ordered {
            if self.limits.root_limit_reached(LimitKind::Review) {
                break;
            }
            let card = by_id[&scored.id];
            // Per-deck limit gate FIRST, mirroring stock's short-circuit: an
            // over-limit card must not take part in sibling-bury tracking, or it
            // could bury an eligible sibling in another deck and drop the note.
            if self
                .limits
                .limit_reached(card.current_deck_id, LimitKind::Review)?
            {
                continue;
            }
            // Sibling burying, deferred from gather to here so it runs in worth
            // order over limit-eligible cards only. `get_and_update_bury_mode_for_note`
            // marks the note "seen" as a side effect, so a note's later (lower-worth)
            // siblings get buried, while the highest-worth eligible sibling survives.
            // Reusing the shared `seen_note_ids` map preserves stock's cross-kind
            // burying (e.g. a review buried by an earlier interday-learning sibling)
            // and the accumulated flags that later gate new-card burying.
            let buried = self
                .get_and_update_bury_mode_for_note(card.into())
                .map(|mode| match card.kind {
                    DueCardKind::Review => mode.bury_reviews,
                    DueCardKind::Learning => mode.bury_interday_learning,
                })
                .unwrap_or_default();
            if buried {
                continue;
            }
            self.limits
                .decrement_deck_and_parent_limits(card.current_deck_id, LimitKind::Review)?;
            selected.push(card);
        }
        self.review = selected;

        Ok(())
    }
}

#[cfg(test)]
mod test {
    use super::*;

    fn input(
        id: i64,
        gather_index: usize,
        category: &str,
        topic: Option<&str>,
        blueprint: f64,
        r: Option<f64>,
    ) -> ScoringInput {
        ScoringInput {
            id: CardId(id),
            gather_index,
            category: category.to_string(),
            topic: topic.map(str::to_string),
            blueprint,
            r,
        }
    }

    fn scored(id: i64, gather_index: usize, category: &str, score: f64) -> Scored {
        Scored {
            id: CardId(id),
            gather_index,
            category: category.to_string(),
            score,
        }
    }

    #[track_caller]
    fn approx(a: f64, b: f64) {
        assert!((a - b).abs() < 1e-9, "{a} != {b}");
    }

    fn max_consecutive_same_category(ordered: &[Scored]) -> usize {
        let mut max = 0;
        let mut run = 0;
        let mut prev: Option<&str> = None;
        for s in ordered {
            if prev == Some(s.category.as_str()) {
                run += 1;
            } else {
                run = 1;
                prev = Some(s.category.as_str());
            }
            max = max.max(run);
        }
        max
    }

    #[test]
    fn parse_topic_rules() {
        assert_eq!(
            parse_topic(" topic::mechanics::lagrangian foo "),
            (
                Some("topic::mechanics::lagrangian".to_string()),
                "mechanics".to_string()
            )
        );
        assert_eq!(
            parse_topic(" topic::quantum "),
            (Some("topic::quantum".to_string()), "quantum".to_string())
        );
        // prefix match is case-insensitive; the stored form is lowercased
        assert_eq!(
            parse_topic(" Topic::Mechanics "),
            (
                Some("topic::mechanics".to_string()),
                "mechanics".to_string()
            )
        );
        // first topic tag wins when several are present
        assert_eq!(
            parse_topic(" topic::lab topic::mechanics "),
            (Some("topic::lab".to_string()), "lab".to_string())
        );
        // no topic tag -> unknown, and unknown has zero blueprint weight
        assert_eq!(parse_topic(" other::tag "), (None, "unknown".to_string()));
        assert_eq!(parse_topic(""), (None, "unknown".to_string()));
        approx(blueprint_for_category("unknown"), 0.0);
        approx(blueprint_for_category("mechanics"), 0.20);
    }

    #[test]
    fn band_factor_boundaries() {
        approx(band_factor(Some(0.60)), 1.0);
        approx(band_factor(Some(0.85)), 1.0);
        approx(band_factor(Some(0.75)), 1.0);
        approx(band_factor(Some(0.5999)), OUT_OF_BAND_FACTOR);
        approx(band_factor(Some(0.8501)), OUT_OF_BAND_FACTOR);
        approx(band_factor(None), OUT_OF_BAND_FACTOR);
    }

    /// Rust test 2 — pure scoring: worth = blueprint% × weakness, plus band.
    #[test]
    fn scoring_worth_and_band() {
        let inputs = vec![
            // mechanics topic: two due cards, R 0.5 and 0.7 -> mean 0.6 -> weakness 0.4
            input(
                1,
                0,
                "mechanics",
                Some("topic::mechanics::a"),
                0.20,
                Some(0.5),
            ),
            input(
                2,
                1,
                "mechanics",
                Some("topic::mechanics::a"),
                0.20,
                Some(0.7),
            ),
            // quantum topic: one due card, R 0.9 -> weakness 0.1
            input(3, 2, "quantum", Some("topic::quantum::b"), 0.13, Some(0.9)),
        ];

        let weakness = weakness_by_topic(&inputs);
        approx(weakness["topic::mechanics::a"], 0.4);
        approx(weakness["topic::quantum::b"], 0.1);

        // worth = blueprint% × weakness (band-independent)
        approx(worth(0.20, weakness["topic::mechanics::a"]), 0.20 * 0.4);
        approx(worth(0.13, weakness["topic::quantum::b"]), 0.13 * 0.1);
        // worth ranking follows blueprint × weakness
        assert!(worth(0.20, 0.4) > worth(0.13, 0.1));

        let scored = score_inputs(&inputs);
        let get = |id: i64| scored.iter().find(|s| s.id == CardId(id)).unwrap();
        // score applies the band factor: card1 R=0.5 out, card2 R=0.7 in, card3 R=0.9
        // out
        approx(get(1).score, worth(0.20, 0.4) * OUT_OF_BAND_FACTOR);
        approx(get(2).score, worth(0.20, 0.4));
        approx(get(3).score, worth(0.13, 0.1) * OUT_OF_BAND_FACTOR);
    }

    /// Rust test 3a — anti-blocking caps consecutive same-category runs at K=3.
    #[test]
    fn anti_blocking_caps_runs() {
        let cards = vec![
            scored(1, 0, "mechanics", 10.0),
            scored(2, 1, "mechanics", 9.0),
            scored(3, 2, "mechanics", 8.0),
            scored(4, 3, "mechanics", 7.0),
            scored(5, 4, "electromagnetism", 6.0),
            scored(6, 5, "electromagnetism", 5.0),
        ];
        let ordered = greedy_order(cards);
        assert!(max_consecutive_same_category(&ordered) <= MAX_CONSECUTIVE_SAME_CATEGORY);
        // a lower-scored different-category card is pulled up to break the run
        assert_eq!(ordered[3].category, "electromagnetism");
    }

    /// Rust test 3b — an in-band card beats an equal-worth out-of-band card.
    #[test]
    fn in_band_preferred_over_equal_worth() {
        let inputs = vec![
            // same topic + category => identical worth; only the band differs
            input(
                1,
                0,
                "mechanics",
                Some("topic::mechanics::x"),
                0.20,
                Some(0.70),
            ),
            input(
                2,
                1,
                "mechanics",
                Some("topic::mechanics::x"),
                0.20,
                Some(0.95),
            ),
        ];
        let base_worth = worth(0.20, weakness_by_topic(&inputs)["topic::mechanics::x"]);

        let scored = score_inputs(&inputs);
        let get = |id: i64| scored.iter().find(|s| s.id == CardId(id)).unwrap().score;
        // identical worth, but the band factor separates them
        approx(get(1), base_worth);
        approx(get(2), base_worth * OUT_OF_BAND_FACTOR);
        assert!(get(1) > get(2));

        // so the in-band card is ordered first
        let ordered = greedy_order(scored);
        assert_eq!(ordered[0].id, CardId(1));
    }

    /// Rust test 3c — truncation keeps the top-N by score, not the first-N in
    /// SQL gather order.
    #[test]
    fn truncation_keeps_top_scores_not_gather_order() {
        // Distinct categories so anti-blocking never reorders; score rises with
        // gather index, i.e. gather order is the reverse of score order.
        let cards = vec![
            scored(1, 0, "mechanics", 1.0),
            scored(2, 1, "electromagnetism", 2.0),
            scored(3, 2, "quantum", 3.0),
            scored(4, 3, "thermodynamics", 4.0),
            scored(5, 4, "atomic", 5.0),
            scored(6, 5, "lab", 6.0),
        ];
        let ordered = greedy_order(cards);
        let retained: Vec<i64> = ordered.iter().take(3).map(|s| s.id.0).collect();
        // top-3 by score are ids 6,5,4 — NOT the first-3 gathered (1,2,3)
        assert_eq!(retained, vec![6, 5, 4]);
    }
}
