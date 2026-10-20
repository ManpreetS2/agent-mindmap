import type { Event } from "@shared/types";
import { formatSourceTime } from "../utils/format";
import { isHttpSourceUrl } from "../utils/sourceUrl";
import { UnsourcedTag } from "./UnsourcedTag";

interface UnparsedPanelProps {
  lines: Event[];
}

export function UnparsedPanel({ lines }: UnparsedPanelProps) {
  if (lines.length === 0) return null;
  return (
    <section className="unparsed-panel" role="region" aria-label="Unparsed ledger lines">
      <h2 className="unparsed-panel__title">Unparsed ledger lines</h2>
      <ul className="unparsed-panel__list">
        {lines.map((line) => (
          <li key={line.id} className="unparsed-panel__item">
            {isHttpSourceUrl(line.source_url) ? (
              <a href={line.source_url}>{formatSourceTime(line.source_time)}</a>
            ) : (
              <span>
                {formatSourceTime(line.source_time)}{" "}
                <UnsourcedTag />
              </span>
            )}
            <span className="unparsed-panel__raw">{line.raw}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
