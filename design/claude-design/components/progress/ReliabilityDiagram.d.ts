export interface ReliabilityPoint {
    /** Predicted probability, 0..1 */
    p: number;
    /** Observed frequency, 0..1 */
    o: number;
}
export interface ReliabilityDiagramProps {
    points: ReliabilityPoint[];
    /** Brier score, e.g. 0.14 */
    brier?: number;
    /** Plain-language read, e.g. "well calibrated", "underconfident" */
    read?: string;
    /** Which model's calibration this shows */
    tone?: "memory" | "performance";
    size?: number;
    style?: React.CSSProperties;
}
export declare function ReliabilityDiagram(props: ReliabilityDiagramProps): JSX.Element;
