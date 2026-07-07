// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// Study: the primary path is today's interleaved session (Cards and Problems
// woven into one queue, commit before help on problems), mirroring the desktop
// launcher (ts/routes/pgrep/study/+page.svelte) and the two-door loop in
// pylib/anki/pgrep/study.py. The running session lives in StudySessionView; this
// screen hosts it plus the two secondary doors that stay on their own surfaces:
// the wrong-answer ladder (Practice problems) and the timed mock (Exam).

import SwiftUI

struct StudyView: View {
    @EnvironmentObject private var app: AppModel
    @State private var showExam = false
    @State private var showLadder = false

    var body: some View {
        VStack(spacing: Theme.Space.l) {
            modesBar
            StudySessionView()
        }
        .padding(Theme.Space.l)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(Theme.canvas.ignoresSafeArea())
        .fullScreenCover(isPresented: $showExam) {
            ExamView().environmentObject(app)
        }
        .fullScreenCover(isPresented: $showLadder) {
            LadderView().environmentObject(app)
        }
    }

    /// The two secondary doors, alongside today's interleaved session: the
    /// wrong-answer ladder (Practice problems) and the timed mock (Exam). They
    /// stay on their own surfaces; the session is the primary study path.
    private var modesBar: some View {
        HStack(spacing: Theme.Space.s) {
            modeButton("Practice problems", systemImage: "list.bullet.rectangle") { showLadder = true }
            modeButton("Take a timed exam", systemImage: "timer") { showExam = true }
        }
    }

    private func modeButton(_ title: String, systemImage: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
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
