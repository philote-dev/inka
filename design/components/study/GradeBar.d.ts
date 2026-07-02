export interface Grade {
  label: string;
  /** Next interval, e.g. "10m", "4d" */
  interval?: string;
}
export interface GradeBarProps {
  /** Defaults to Again / Hard / Good / Easy with FSRS intervals */
  grades?: Grade[];
  showIntervals?: boolean;
  onGrade?: (label: string) => void;
  style?: React.CSSProperties;
}
export declare function GradeBar(props: GradeBarProps): JSX.Element;
