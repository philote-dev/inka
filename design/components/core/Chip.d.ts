export interface ChipProps {
  /** Score tones only when the chip carries that meaning. States for verification statuses. */
  tone?: 'neutral' | 'memory' | 'performance' | 'readiness' | 'success' | 'caution' | 'error';
  /** Leading 6px dot in the tone color */
  dot?: boolean;
  size?: 'md' | 'sm';
  children: React.ReactNode;
  style?: React.CSSProperties;
}
export declare function Chip(props: ChipProps): JSX.Element;
