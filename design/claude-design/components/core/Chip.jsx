import React from "react";

const TONES = {
    neutral: { color: "var(--muted)", border: "var(--border)" },
    memory: { color: "var(--memory-text)", border: "rgba(235,203,139,0.35)" },
    performance: { color: "var(--performance-text)", border: "rgba(129,161,193,0.45)" },
    readiness: { color: "var(--readiness-text)", border: "rgba(196,167,214,0.45)" },
    success: { color: "var(--success)", border: "rgba(163,190,140,0.4)" },
    caution: { color: "var(--caution)", border: "rgba(208,135,112,0.4)" },
    error: { color: "var(--error)", border: "rgba(191,97,106,0.4)" },
};

/** Pill chip for topics and statuses. Tone follows the reserved color language. */
export function Chip({ tone = "neutral", dot = false, size = "md", children, style }) {
    const t = TONES[tone] || TONES.neutral;
    return (
        <span
            style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                fontFamily: "var(--font-ui)",
                fontSize: size === "sm" ? 11 : 12,
                fontWeight: 500,
                color: t.color,
                border: `1px solid ${t.border}`,
                borderRadius: "var(--radius-pill)",
                padding: size === "sm" ? "3px 10px" : "4px 12px",
                whiteSpace: "nowrap",
                ...style,
            }}
        >
            {dot && <span style={{ width: 6, height: 6, borderRadius: 999, background: "currentColor" }} />}
            {children}
        </span>
    );
}
