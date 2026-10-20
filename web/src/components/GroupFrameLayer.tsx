import type { GroupFrameRect } from "../utils/groupFrames";

interface GroupFrameLayerProps {
  frames: GroupFrameRect[];
}

export function GroupFrameLayer({ frames }: GroupFrameLayerProps) {
  return (
    <svg className="group-frame-layer" aria-hidden="true">
      {frames.map((f) => (
        <g key={f.id} className={`group-frame group-frame--${f.groupId}`}>
          <rect
            x={f.x}
            y={f.y}
            width={f.width}
            height={f.height}
            rx={14}
            className="group-frame__rect"
          />
          <text x={f.x + 14} y={f.y + 18} className="group-frame__label">
            {f.label}
          </text>
        </g>
      ))}
    </svg>
  );
}
