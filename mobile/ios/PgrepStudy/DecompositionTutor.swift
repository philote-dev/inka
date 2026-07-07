// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// The gated decomposition tutor (AI off), a native port of
// pylib/anki/pgrep/decomposition.py (load_tutor, check_mcq, _variant,
// _usable_subproblems, _valid_variant, has_tutor) and the desktop handlers
// pgrep_tutor_load / pgrep_tutor_mcq in qt/aqt/pgrep.py. A miss on a Problem that
// carries stored tutor data opens a short sequence of subproblems (mini MCQs)
// that walk the learner to the idea one step at a time. The parent problem's own
// answer is never revealed on a miss.
//
// AI off: the desktop gates each step behind the MCQ and, only with AI on, a
// graded free-text "explain why" (decomposition.grade_explanation, handler
// pgrep_tutor_explain). This app is AI off by construction, so that gate is
// skipped (needs_explanation stays false) and the MCQ alone gates. There are no
// LLM calls; the tutor is deterministic, walking the stored pre-generated numeric
// variants.
//
// This is the pure, testable core (no SwiftUI, no engine): it parses the stored
// decomposition_tutor JSON, selects a variant deterministically, and grades an
// MCQ pick. Engine.loadTutor reads the note field and hands the JSON here;
// SubproblemCardView renders a step and StudySessionView drives the flow, exactly
// the ChoiceList/ChoiceListView + StudySession/StudySessionView split the codebase
// uses so the host-less test bundle can pin the logic.

import Foundation

/// One numeric variant of a subproblem: a self-contained five-choice MCQ with a
/// correct key, per-distractor rationales, and a model rationale. Mirrors a
/// variant entry in the stored `decomposition_tutor` blob (problem.py) and the
/// fields decomposition._valid_variant requires.
struct TutorVariant: Sendable, Equatable {
    var stem: String
    var choices: [String]
    var key: String
    /// Letter -> rationale for that distractor (never the correct key).
    var distractorRationales: [String: String]
    var explainWhy: String
    var sourceRef: String
}

/// One subproblem (a solution sub-goal) with its pre-generated numeric variants.
/// Only well-formed variants are kept at parse time (decomposition._valid_variant),
/// so a subproblem present here always has at least one variant to serve.
struct TutorSubproblem: Sendable, Equatable {
    var prompt: String
    var variants: [TutorVariant]
}

/// The withheld view of one subproblem handed to the UI, an entry in
/// decomposition.load_tutor's output: the stem and choices to attempt, with the
/// key, distractor rationales, and model rationale kept back until the MCQ is
/// answered.
struct TutorStep: Sendable, Equatable, Identifiable {
    /// 0-based subproblem index (the subgoal_index to grade against).
    var index: Int
    /// Which variant was served (the variant_index to grade against).
    var variantIndex: Int
    /// The short subgoal label (the subproblem's `prompt`).
    var prompt: String
    /// The variant's question stem (HTML with LaTeX math).
    var stemHtml: String
    var choices: [String]

    var id: Int { index }
}

/// The graded outcome of one subproblem MCQ pick, a port of
/// decomposition.check_mcq. A wrong pick returns only that distractor's rationale
/// and withholds the key (retries stay honest); a correct pick reveals the model
/// rationale. `needsExplanation` mirrors the AI-on explain gate and stays false
/// here (AI off), so the MCQ alone gates.
enum TutorMcqOutcome: Sendable, Equatable {
    case correct(correctChoice: String, explainWhyHtml: String, needsExplanation: Bool)
    case incorrect(rationaleHtml: String)
}

/// The option letters a subproblem variant may use (problem.CHOICE_LETTERS).
private let tutorChoiceLetters: Set<String> = ["A", "B", "C", "D", "E"]

/// Parsed, usable tutor data for one Problem, a port of the readers in
/// decomposition.py (_load_tutor_data + _usable_subproblems). Parsing keeps only
/// well-formed variants (exactly five choices and a key in A..E) and only
/// subproblems that carry at least one, so `hasTutor`, `load`, and the grader
/// mirror the Python semantics exactly.
struct DecompositionTutor: Sendable, Equatable {
    /// Usable subproblems in order (each carries at least one valid variant).
    var subproblems: [TutorSubproblem]
    /// Renumbered parent stems for a re-served problem (`parent_variants`),
    /// parsed for fidelity. The iOS session runs a single linear pass and does
    /// not re-queue a miss, so these are currently unused (see StudySessionView).
    var parentVariants: [TutorVariant]

    /// The empty tutor a problem without a usable decomposition reads as.
    static let empty = DecompositionTutor(subproblems: [], parentVariants: [])

    /// Whether the problem has any usable decomposition to run on a miss
    /// (decomposition.has_tutor).
    var hasTutor: Bool { !subproblems.isEmpty }

    /// The number of subproblems the learner will work (load_tutor "count").
    var count: Int { subproblems.count }

    // MARK: - Parsing

    /// Parse a stored `decomposition_tutor` JSON blob. Always well-formed: a blob
    /// that is empty, malformed, or the wrong shape reads as an empty tutor
    /// rather than throwing, so the caller degrades gracefully (mirrors
    /// decomposition._load_tutor_data + _usable_subproblems).
    static func parse(json: String) -> DecompositionTutor {
        guard let data = json.data(using: .utf8),
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return .empty
        }
        let rawSubs = root["subproblems"] as? [Any] ?? []
        var subs: [TutorSubproblem] = []
        for entry in rawSubs {
            guard let dict = entry as? [String: Any] else { continue }
            let variants = parseVariants(dict["variants"])
            // Usable: the subproblem carries at least one well-formed variant.
            guard !variants.isEmpty else { continue }
            subs.append(TutorSubproblem(prompt: dict["prompt"] as? String ?? "", variants: variants))
        }
        return DecompositionTutor(subproblems: subs, parentVariants: parseVariants(root["parent_variants"]))
    }

    /// Build the valid variants from a raw `variants` array, dropping malformed
    /// ones (decomposition._valid_variant: five choices and a key in A..E).
    private static func parseVariants(_ raw: Any?) -> [TutorVariant] {
        guard let array = raw as? [Any] else { return [] }
        return array.compactMap { parseVariant($0) }
    }

    private static func parseVariant(_ raw: Any) -> TutorVariant? {
        guard let dict = raw as? [String: Any] else { return nil }
        let choices = parseChoices(dict["choices"])
        let key = (dict["key"] as? String ?? "").trimmingCharacters(in: .whitespaces).uppercased()
        // _valid_variant: exactly five choices and a key letter in A..E.
        guard choices.count == 5, tutorChoiceLetters.contains(key) else { return nil }
        return TutorVariant(
            stem: dict["stem"] as? String ?? "",
            choices: choices,
            key: key,
            distractorRationales: parseRationaleMap(dict["distractor_rationales"]),
            explainWhy: dict["explain_why"] as? String ?? "",
            sourceRef: dict["source_ref"] as? String ?? ""
        )
    }

    private static func parseChoices(_ raw: Any?) -> [String] {
        guard let array = raw as? [Any] else { return [] }
        return array.map { $0 as? String ?? String(describing: $0) }
    }

    /// A letter -> text map with uppercased keys (decomposition._rationale_map).
    private static func parseRationaleMap(_ raw: Any?) -> [String: String] {
        guard let dict = raw as? [String: Any] else { return [:] }
        var out: [String: String] = [:]
        for (key, value) in dict {
            out[key.uppercased()] = value as? String ?? String(describing: value)
        }
        return out
    }

    // MARK: - Variant selection + load

    /// The specific variant to grade, or nil when out of range
    /// (decomposition._variant). `variantIndex` wraps modulo the variant count,
    /// matching the Python.
    func variant(subgoalIndex: Int, variantIndex: Int) -> TutorVariant? {
        guard subproblems.indices.contains(subgoalIndex) else { return nil }
        let variants = subproblems[subgoalIndex].variants
        guard !variants.isEmpty else { return nil }
        return variants[wrap(variantIndex, count: variants.count)]
    }

    /// The subproblems to work with the answer and help withheld, a port of
    /// decomposition.load_tutor. `roundIndex` selects the numeric variant of every
    /// subproblem (0 on the first miss), so a repeat never reuses the same numbers.
    func load(roundIndex: Int = 0) -> [TutorStep] {
        subproblems.enumerated().map { index, sub in
            let variantIndex = wrap(roundIndex, count: sub.variants.count)
            let variant = sub.variants[variantIndex]
            return TutorStep(
                index: index,
                variantIndex: variantIndex,
                prompt: sub.prompt,
                stemHtml: variant.stem,
                choices: variant.choices
            )
        }
    }

    // MARK: - Grading (the MCQ gate)

    /// Grade one subproblem's MCQ pick (unlimited retries), a port of
    /// decomposition.check_mcq. A wrong or empty pick returns that distractor's
    /// rationale and never names the key; a correct pick reveals the model
    /// rationale and reports whether the AI-on explain gate applies (`aiEnabled`,
    /// false in this app). Returns nil for an out-of-range subproblem (the
    /// Python "no such subproblem" error).
    func checkMcq(
        subgoalIndex: Int,
        variantIndex: Int,
        selected: String,
        aiEnabled: Bool = false
    ) -> TutorMcqOutcome? {
        guard let variant = variant(subgoalIndex: subgoalIndex, variantIndex: variantIndex) else {
            return nil
        }
        let picked = selected.trimmingCharacters(in: .whitespaces).uppercased()
        if picked.isEmpty || picked != variant.key {
            return .incorrect(rationaleHtml: variant.distractorRationales[picked] ?? "")
        }
        return .correct(
            correctChoice: variant.key,
            explainWhyHtml: variant.explainWhy,
            needsExplanation: aiEnabled
        )
    }

    /// Non-negative modulo, so a variant index always lands in range (Python's
    /// `%` is non-negative for a positive divisor).
    private func wrap(_ index: Int, count: Int) -> Int {
        let m = index % count
        return m < 0 ? m + count : m
    }
}
