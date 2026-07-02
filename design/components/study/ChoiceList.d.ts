export interface Choice {
  /** "A" through "E" */
  key: string;
  /** Text or MathJax-bearing node */
  content: React.ReactNode;
  state?: 'default' | 'selected' | 'committed';
}
export interface ChoiceListProps {
  choices: Choice[];
  onSelect?: (key: string) => void;
  style?: React.CSSProperties;
}
export declare function ChoiceList(props: ChoiceListProps): JSX.Element;
