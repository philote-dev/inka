export interface CoverageSegment {
  topic: string;
  /** Exam blueprint weight, relative */
  weight: number;
  /** 0..1 fraction covered */
  covered: number;
}
export interface CoverageBarProps {
  segments: CoverageSegment[];
  /** Readiness gate, percent. Default 70 */
  threshold?: number;
  /** Abstain rule note, e.g. why Readiness is quiet */
  note?: string;
  style?: React.CSSProperties;
}
export declare function CoverageBar(props: CoverageBarProps): JSX.Element;
