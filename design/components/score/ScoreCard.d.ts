/** @startingPoint section="Components" subtitle="Number, range, how sure, updated, abstain" viewport="700x260" */
export interface ScoreCardProps {
  /** Fixes the reserved hue and glyph */
  kind: 'memory' | 'performance' | 'readiness';
  /** Defaults to the capitalized kind */
  label?: string;
  /** Point number, 0 to 100 */
  value?: number;
  /** Likely range, renders "Likely lo to hi" */
  range?: [number, number];
  /** e.g. "Fairly sure", "Somewhat sure", "Low confidence" */
  howSure?: string;
  /** e.g. "Updated 2h ago" */
  updated?: string;
  /** 0..1 values for the tiny accent sparkline */
  sparkline?: number[];
  /** When data is thin the card abstains instead of showing a number */
  abstain?: { message?: string; missing?: string; linkLabel?: string; onLink?: () => void };
  style?: React.CSSProperties;
}
export declare function ScoreCard(props: ScoreCardProps): JSX.Element;
