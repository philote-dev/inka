export interface ManifoldSurface {
    /** Blob radius harmonics [a0, a3, p3, a2, p2] */
    boundary: number[];
    /** Topic peaks. h tracks Performance, s tracks blueprint footprint */
    bumps: { x: number; y: number; h: number; s: number }[];
    /** Rim sinks around gaps */
    dips: { x: number; y: number; h: number; s: number }[];
    /** Knowledge gaps. No data means no surface */
    holes: { x: number; y: number; rx: number; ry: number }[];
    /** Soft under-glow, c is an "r,g,b" string */
    glows: { x: number; y: number; c: string }[];
    labels: { name: string; x: number; y: number; dx: number; dy: number; tf: string }[];
}
export interface ManifoldProps {
    width?: number;
    height?: number;
    /** Projection scale. 182 fits 828x540, ~112 fits a phone */
    scale?: number;
    /** Line brightness 0..1 */
    glow?: number;
    grid?: number;
    lineWidth?: number;
    /** Data-driven surface; defaults to the demo topology */
    surface?: ManifoldSurface;
    showLabels?: boolean;
    style?: React.CSSProperties;
}
export declare function Manifold(props: ManifoldProps): JSX.Element;
