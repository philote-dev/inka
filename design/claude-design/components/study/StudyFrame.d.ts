export interface StudyFrameProps {
    /** Current item number, 1-based */
    progress: number;
    total: number;
    topic: string;
    /** memory for the cards door, performance for the problems door */
    topicTone?: "neutral" | "memory" | "performance";
    onClose?: () => void;
    /** Width of the focused center column, default 640 */
    columnWidth?: number;
    children: React.ReactNode;
    style?: React.CSSProperties;
}
export declare function StudyFrame(props: StudyFrameProps): JSX.Element;
