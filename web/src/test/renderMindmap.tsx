import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";

export function renderMindmap(ui: ReactElement): RenderResult {
  return render(<div style={{ width: 1280, height: 720 }}>{ui}</div>);
}
