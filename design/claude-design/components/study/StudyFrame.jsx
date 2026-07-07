import React from "react";

/** Minimal session chrome. Progress, topic chip, close. Content goes in a
    focused single column below. */
export function StudyFrame(
    { progress, total, topic, topicTone = "neutral", onClose, columnWidth = 640, children, style },
) {
    const toneColors = {
        neutral: { c: "var(--muted)", b: "var(--border)" },
        memory: { c: "var(--memory-text)", b: "rgba(235,203,139,0.35)" },
        performance: { c: "var(--performance-text)", b: "rgba(129,161,193,0.45)" },
    };
    const t = toneColors[topicTone] || toneColors.neutral;
    return (
        <div
            style={{
                background: "var(--canvas)",
                color: "var(--text)",
                fontFamily: "var(--font-ui)",
                minHeight: "100%",
                display: "flex",
                flexDirection: "column",
                ...style,
            }}
        >
            <div
                style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "20px 28px" }}
            >
                <span
                    style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 13,
                        color: "var(--muted)",
                        fontVariantNumeric: "tabular-nums",
                        whiteSpace: "nowrap",
                    }}
                >
                    {progress} / {total}
                </span>
                <span
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        fontSize: 12,
                        fontWeight: 500,
                        color: t.c,
                        border: `1px solid ${t.b}`,
                        borderRadius: 999,
                        padding: "4px 12px",
                    }}
                >
                    {topicTone !== "neutral" && (
                        <span style={{ width: 6, height: 6, borderRadius: 999, background: "currentColor" }} />
                    )}
                    {topic}
                </span>
                <button
                    aria-label="Close"
                    onClick={onClose}
                    style={{
                        width: 32,
                        height: 32,
                        background: "none",
                        border: "none",
                        borderRadius: 8,
                        color: "var(--muted)",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                    }}
                >
                    <svg
                        width="16"
                        height="16"
                        viewBox="0 0 16 16"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                    >
                        <line x1="4" y1="4" x2="12" y2="12" />
                        <line x1="12" y1="4" x2="4" y2="12" />
                    </svg>
                </button>
            </div>
            <div style={{ width: columnWidth, margin: "0 auto", padding: "32px 0 64px", flex: "1 1 auto" }}>
                {children}
            </div>
        </div>
    );
}
