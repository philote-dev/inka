// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Minimal SwiftUI review screen driven entirely by the shared Rust engine via
// AnkiBackend. It stages the bundled sample deck, opens the collection, and
// walks the queue: show Front -> tap to reveal Back -> "Answer: Good" advances
// to the next card. The pgrep seam marker is shown in the footer to visibly
// tie the running Rust engine to the app.

import SwiftUI

/// Drives the review loop against the shared engine. Runs on the main actor;
/// the sample deck is tiny so the synchronous FFI calls are fine here.
@MainActor
final class ReviewModel: ObservableObject {
    enum Phase: Equatable {
        case loading
        case reviewing
        case done
        case failed(String)
    }

    @Published private(set) var phase: Phase = .loading
    @Published private(set) var front: String = ""
    @Published private(set) var back: String = ""
    @Published private(set) var showBack: Bool = false
    @Published private(set) var remaining: Int = 0
    @Published private(set) var seamStatus: String = "checking Rust seam…"

    private var backend: AnkiBackend?
    private var current: Anki_Scheduler_QueuedCards.QueuedCard?

    /// Open the engine, stage + open the collection, and load the first card.
    func start() {
        do {
            let backend = try AnkiBackend()
            self.backend = backend

            guard let deckURL = StudySandbox.bundledDeckURL(in: .main) else {
                phase = .failed("Bundled collection.anki2 not found in app bundle")
                return
            }
            let documents = try FileManager.default.url(
                for: .documentDirectory,
                in: .userDomainMask,
                appropriateFor: nil,
                create: true
            )
            let directory = documents.appendingPathComponent("PgrepStudy", isDirectory: true)
            let staged = try StudySandbox.stage(from: deckURL, in: directory, freshCopy: false)
            try backend.openCollection(
                path: staged.collectionPath,
                mediaFolder: staged.mediaFolderPath
            )
            // A freshly opened collection defaults to the empty "Default" deck;
            // select the PGRE deck so the scheduler queues its cards.
            try backend.selectDeck(named: StudySandbox.studyDeckName)
            // pgrep_seam_check is a CollectionService RPC, so it must run after
            // the collection is open (the same order the smoke test uses).
            seamStatus = (try? backend.pgrepSeamCheck()) ?? "seam check failed"
            loadNextCard()
        } catch {
            phase = .failed(String(describing: error))
        }
    }

    func revealBack() {
        showBack = true
    }

    /// Answer the current card "Good" and advance the queue.
    func answerGood() {
        guard let backend, let card = current else { return }
        do {
            var answer = Anki_Scheduler_CardAnswer()
            answer.cardID = card.card.id
            answer.currentState = card.states.current
            answer.newState = card.states.good
            answer.rating = .good
            answer.answeredAtMillis = Int64(Date().timeIntervalSince1970 * 1000)
            answer.millisecondsTaken = 1000
            try backend.answerCard(answer)
            loadNextCard()
        } catch {
            phase = .failed(String(describing: error))
        }
    }

    private func loadNextCard() {
        guard let backend else { return }
        do {
            let queued = try backend.getQueuedCards(fetchLimit: 10)
            remaining = Int(queued.newCount + queued.learningCount + queued.reviewCount)
            guard let first = queued.cards.first else {
                current = nil
                phase = .done
                return
            }
            current = first
            let note = try backend.getNote(noteId: first.card.noteID)
            front = note.fields.first ?? "(no front)"
            back = note.fields.count > 1 ? note.fields[1] : "(no back)"
            showBack = false
            phase = .reviewing
        } catch {
            phase = .failed(String(describing: error))
        }
    }
}

struct ContentView: View {
    @StateObject private var model = ReviewModel()
    @State private var started = false

    var body: some View {
        VStack(spacing: 24) {
            header
            Spacer(minLength: 0)
            content
            Spacer(minLength: 0)
            footer
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemGroupedBackground))
        .onAppear {
            guard !started else { return }
            started = true
            model.start()
        }
    }

    private var header: some View {
        VStack(spacing: 4) {
            Text("PGRE Study")
                .font(.largeTitle.bold())
            Text("Physics GRE · powered by the shared Anki engine")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private var content: some View {
        switch model.phase {
        case .loading:
            ProgressView("Opening collection…")
        case .reviewing:
            reviewCard
        case .done:
            statusCard(
                title: "All done",
                message: "No more cards in the queue.",
                systemImage: "checkmark.circle.fill",
                tint: .green
            )
        case let .failed(message):
            statusCard(
                title: "Something went wrong",
                message: message,
                systemImage: "exclamationmark.triangle.fill",
                tint: .red
            )
        }
    }

    private var reviewCard: some View {
        VStack(spacing: 20) {
            HStack {
                Label("\(model.remaining) in queue", systemImage: "tray.full")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Spacer()
            }

            VStack(spacing: 16) {
                Text(model.front)
                    .font(.title2.weight(.semibold))
                    .multilineTextAlignment(.center)

                if model.showBack {
                    Divider()
                    Text(model.back)
                        .font(.title3)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(28)
            .background(Color(.secondarySystemGroupedBackground))
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .shadow(color: .black.opacity(0.08), radius: 12, y: 6)

            if model.showBack {
                Button(action: model.answerGood) {
                    Text("Answer: Good")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            } else {
                Button(action: model.revealBack) {
                    Text("Show Answer")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
            }
        }
    }

    private func statusCard(title: String, message: String, systemImage: String, tint: Color) -> some View {
        VStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.system(size: 44))
                .foregroundStyle(tint)
            Text(title)
                .font(.title2.bold())
            Text(message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(28)
        .frame(maxWidth: .infinity)
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

    private var footer: some View {
        Text(model.seamStatus)
            .font(.caption.monospaced())
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity)
    }
}

#Preview {
    ContentView()
}
