// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Study: the primary path is today's interleaved session (Cards and Problems
// woven into one queue, commit before help on problems), mirroring the desktop
// launcher (ts/routes/pgrep/study/+page.svelte) and the two-door loop in
// pylib/anki/pgrep/study.py. A miss on a problem opens the gated decomposition
// tutor (DecompositionTutor + SubproblemCardView) inside the session, which
// replaced the retired static wrong-answer ladder. The running session lives in
// StudySessionView; this screen hosts it plus the one secondary door that stays
// on its own surface: the timed mock (Exam).

import SwiftUI

struct StudyView: View {
    @EnvironmentObject private var app: AppModel
    @State private var showExam = false

    var body: some View {
        VStack(spacing: Theme.Space.l) {
            examEntry
            StudySessionView()
        }
        .padding(Theme.Space.l)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(Theme.canvas.ignoresSafeArea())
        .fullScreenCover(isPresented: $showExam) {
            ExamView().environmentObject(app)
        }
    }

    /// The one secondary door alongside today's interleaved session: the timed
    /// mock. It stays on its own surface; the session is the primary study path.
    private var examEntry: some View {
        Button { showExam = true } label: {
            Label("Take a timed exam", systemImage: "timer")
                .font(Theme.Typography.body)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
                .frame(maxWidth: .infinity)
                .padding(.vertical, Theme.Space.s + Theme.Space.xs)
                .foregroundStyle(Theme.text)
                .overlay(
                    RoundedRectangle(cornerRadius: Theme.Radius.control, style: .continuous)
                        .stroke(Theme.border, lineWidth: 1)
                )
        }
    }
}
