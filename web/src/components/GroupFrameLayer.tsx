import type { GroupFrameRect } from "../utils/groupFrames";

interface GroupFrameLayerProps {
  frames: GroupFrameRect[];
}

export function GroupFrameLayer({ frames }: GroupFrameLayerProps) {
  return (
    <svg className="group-frame-layer" aria-hidden="true">
      {frames.map((f) => (
        <g key={f.id}>
          <rect
            x={f.x}
            y={f.y}
            width={f.width}
            height={f.height}
            rx={8}
            className="group-frame__rect"
          />
          <text x={f.x + 12} y={f.y + 16} className="group-frame__label">
            {f.label}
          </text>
        </g>
      ))}
    </svg>
  );
}
