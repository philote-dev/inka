import React from "react";

/** Monochrome action. The only meaning-bearing color on screen is data. */
export function Button({ variant = "primary", size = "md", disabled = false, onClick, children, style }) {
    const pad = size === "sm" ? "8px 14px" : "12px 20px";
    const fs = size === "sm" ? 13 : 14;
    const base = {
        fontFamily: "var(--font-ui)",
        fontSize: fs,
        fontWeight: 500,
        borderRadius: "var(--radius-control)",
        padding: pad,
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.5 : 1,
        transition: "background 240ms ease, border-color 240ms ease, color 240ms ease",
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
    };
    const variants = {
        primary: { background: "var(--action-bg)", color: "var(--action-fg)", border: "none" },
        secondary: { background: "none", color: "var(--text)", border: "1px solid var(--muted)" },
        ghost: { background: "none", color: "var(--muted)", border: "none" },
    };
    return (
        <button onClick={disabled ? undefined : onClick} style={{ ...base, ...variants[variant], ...style }}>
            {children}
        </button>
    );
}
