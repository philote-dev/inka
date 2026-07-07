import React from "react";

/** One rung of the wrong-answer ladder. Calm card, hint budget dots,
    self-explanation input, never leaks the final answer. */
export function HintRung(
    {
        title = "Break it down",
        step = 1,
        steps = 3,
        hintsUsed = 1,
        budget = 3,
        question,
        placeholder = "Write your answer and a short reason",
        actionLabel = "Show the step",
        onAction,
        footer = "Working it out yourself is the point.",
        style,
    },
) {
    return (
        <div style={{ fontFamily: "var(--font-ui)", color: "var(--text)", ...style }}>
            <section
                style={{
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-card)",
                    padding: 24,
                    boxShadow: "var(--shadow-card)",
                }}
            >
                <div
                    style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}
                >
                    <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, letterSpacing: "-0.01em" }}>{title}</h2>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                            {Array.from({ length: budget }).map((_, i) => (
                                <span
                                    key={i}
                                    style={i < hintsUsed
                                        ? { width: 7, height: 7, borderRadius: 999, background: "var(--performance)" }
                                        : {
                                            width: 7,
                                            height: 7,
                                            borderRadius: 999,
                                            border: "1px solid var(--muted)",
                                            boxSizing: "border-box",
                                        }}
                                />
                            ))}
                        </div>
                        <span style={{ fontSize: 12, color: "var(--muted)", fontVariantNumeric: "tabular-nums" }}>
                            {hintsUsed} of {budget} hints
                        </span>
                    </div>
                </div>
                <div
                    style={{
                        fontSize: 11,
                        fontWeight: 500,
                        letterSpacing: "0.08em",
                        textTransform: "uppercase",
                        color: "var(--muted)",
                        marginBottom: 8,
                    }}
                >
                    Step {step} of {steps}
                </div>
                <p style={{ margin: "0 0 18px", fontSize: 16, lineHeight: 1.55 }}>{question}</p>
                <textarea
                    rows={3}
                    placeholder={placeholder}
                    style={{
                        width: "100%",
                        boxSizing: "border-box",
                        background: "var(--canvas)",
                        border: "1px solid var(--border)",
                        borderRadius: "var(--radius-control)",
                        padding: "12px 14px",
                        fontFamily: "var(--font-ui)",
                        fontSize: 14,
                        lineHeight: 1.5,
                        color: "var(--text)",
                        resize: "vertical",
                        outline: "none",
                    }}
                />
                <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
                    <button
                        onClick={onAction}
                        style={{
                            background: "none",
                            color: "var(--text)",
                            border: "1px solid var(--muted)",
                            borderRadius: "var(--radius-control)",
                            padding: "11px 20px",
                            fontFamily: "inherit",
                            fontSize: 14,
                            fontWeight: 500,
                            cursor: "pointer",
                            transition: "background 240ms ease, border-color 240ms ease, color 240ms ease",
                        }}
                    >
                        {actionLabel}
                    </button>
                </div>
            </section>
            {footer && (
                <p
                    style={{
                        margin: "24px 0 0",
                        textAlign: "center",
                        fontSize: 12,
                        color: "var(--muted)",
                        opacity: 0.8,
                    }}
                >
                    {footer}
                </p>
            )}
        </div>
    );
}
