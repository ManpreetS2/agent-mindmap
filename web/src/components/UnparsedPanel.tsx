import { useState } from "react";
import type { Event } from "@shared/types";
import { formatSourceTime } from "../utils/format";
import { isUndatedSourceTime } from "../utils/eventTime";
import { isHttpSourceUrl } from "../utils/sourceUrl";
import { plainTextForDisplay } from "../utils/plainText";
import { UnsourcedTag } from "./UnsourcedTag";

interface UnparsedPanelProps {
  lines: Event[];
}

function timeLabel(line: Event): string {
  if (isUndatedSourceTime(line.source_time)) return "Undated";
  return formatSourceTime(line.source_time);
}

export function UnparsedPanel({ lines }: UnparsedPanelProps) {
  const [open, setOpen] = useState(false);
  if (lines.length === 0) return null;

  return (
    <section className="debug-drawer" aria-label="Unparsed ledger debug">
      <button
        type="button"
        className="debug-drawer__toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        Debug ({lines.length})
      </button>
      {open && (
        <div className="debug-drawer__body" role="region" aria-label="Unparsed ledger lines">
          <ul className="debug-drawer__list">
            {lines.map((line) => (
              <li key={line.id} className="debug-drawer__item">
                {isHttpSourceUrl(line.source_url) ? (
                  <a href={line.source_url}>{timeLabel(line)}</a>
                ) : (
                  <span>
                    {timeLabel(line)}{" "}
                    <UnsourcedTag />
                  </span>
                )}
                <span className="debug-drawer__raw">
                  {plainTextForDisplay(line.raw)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
