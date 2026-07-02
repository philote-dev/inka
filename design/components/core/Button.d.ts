/** @startingPoint section="Components" subtitle="Monochrome primary, secondary, ghost" viewport="700x160" */
export interface ButtonProps {
  /** primary is filled monochrome, secondary is outlined, ghost is bare text */
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'md' | 'sm';
  disabled?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
  style?: React.CSSProperties;
}
export declare function Button(props: ButtonProps): JSX.Element;
