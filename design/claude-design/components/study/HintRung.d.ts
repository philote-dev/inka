export interface HintRungProps {
    /** Rung title, e.g. "Break it down" (L2), "Nudge" (L1) */
    title?: string;
    /** Sub-goal position within the decomposition */
    step?: number;
    steps?: number;
    hintsUsed?: number;
    budget?: number;
    /** The sub-goal posed as a question. Never the answer. */
    question: React.ReactNode;
    placeholder?: string;
    actionLabel?: string;
    onAction?: () => void;
    /** Quiet supportive line under the card; null to hide */
    footer?: string | null;
    style?: React.CSSProperties;
}
export declare function HintRung(props: HintRungProps): JSX.Element;
