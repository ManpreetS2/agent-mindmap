/**
 * QA-MM020e-6: display-only plain text — never interpret event raw as HTML.
 */
export function plainTextForDisplay(value: string): string {
  return value.replace(/<[^>]*>/g, "");
}
