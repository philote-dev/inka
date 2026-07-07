import React from "react";

/** Reliability diagram for model calibration. Predicted vs observed with a
    diagonal reference and a Brier score. Tone is memory or performance. */
export function ReliabilityDiagram({ points, brier, read, tone = "performance", size = 200, style }) {
    const color = tone === "memory" ? "var(--memory)" : "var(--performance)";
    const pad = 28;
    const s = size - pad - 10;
    const px = (v) => pad + v * s;
    const py = (v) => size - pad - v * s;
    return (
        <div style={{ fontFamily: "var(--font-ui)", color: "var(--text)", display: "inline-block", ...style }}>
            <svg width={size} height={size} style={{ display: "block" }}>
                <line x1={px(0)} y1={py(0)} x2={px(1)} y2={py(0)} stroke="var(--border)" strokeWidth="1" />
                <line x1={px(0)} y1={py(0)} x2={px(0)} y2={py(1)} stroke="var(--border)" strokeWidth="1" />
                <line
                    x1={px(0)}
                    y1={py(0)}
                    x2={px(1)}
                    y2={py(1)}
                    stroke="var(--muted)"
                    strokeWidth="1"
                    strokeDasharray="3 4"
                    opacity="0.6"
                />
                <polyline
                    points={points.map((p) => `${px(p.p)},${py(p.o)}`).join(" ")}
                    fill="none"
                    stroke={color}
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                />
                {points.map((p, i) => <circle key={i} cx={px(p.p)} cy={py(p.o)} r="2.5" fill={color} />)}
                <text
                    x={px(0.5)}
                    y={size - 8}
                    textAnchor="middle"
                    fontSize="10"
                    fill="var(--muted)"
                    fontFamily="var(--font-ui)"
                >
                    predicted
                </text>
                <text
                    x={10}
                    y={py(0.5)}
                    textAnchor="middle"
                    fontSize="10"
                    fill="var(--muted)"
                    fontFamily="var(--font-ui)"
                    transform={`rotate(-90 10 ${py(0.5)})`}
                >
                    observed
                </text>
            </svg>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 6, paddingLeft: pad }}>
                {brier != null && (
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontVariantNumeric: "tabular-nums" }}>
                        Brier {brier}
                    </span>
                )}
                {read && <span style={{ fontSize: 12, color: "var(--muted)" }}>{read}</span>}
            </div>
        </div>
    );
}
