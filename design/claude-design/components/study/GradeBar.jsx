import React from "react";

const DEFAULT_GRADES = [
    { label: "Again", interval: "10m" },
    { label: "Hard", interval: "2d" },
    { label: "Good", interval: "4d" },
    { label: "Easy", interval: "8d" },
];

/** FSRS grade row for the cards door. Four equal monochrome buttons. */
export function GradeBar({ grades = DEFAULT_GRADES, showIntervals = true, onGrade, style }) {
    return (
        <div
            style={{
                display: "grid",
                gridTemplateColumns: `repeat(${grades.length}, 1fr)`,
                gap: 12,
                fontFamily: "var(--font-ui)",
                ...style,
            }}
        >
            {grades.map((g) => (
                <button
                    key={g.label}
                    onClick={() => onGrade && onGrade(g.label)}
                    style={{
                        background: "none",
                        border: "1px solid var(--border)",
                        borderRadius: "var(--radius-control)",
                        padding: "12px 0 10px",
                        color: "var(--text)",
                        cursor: "pointer",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        gap: 3,
                        fontFamily: "inherit",
                        transition: "background 240ms ease, border-color 240ms ease, color 240ms ease",
                    }}
                >
                    <span style={{ fontSize: 14, fontWeight: 500 }}>{g.label}</span>
                    {showIntervals && (
                        <span
                            style={{
                                fontFamily: "var(--font-mono)",
                                fontSize: 11,
                                color: "var(--muted)",
                                fontVariantNumeric: "tabular-nums",
                            }}
                        >
                            {g.interval}
                        </span>
                    )}
                </button>
            ))}
        </div>
    );
}
