import { describe, expect, it } from "vitest";

import css from "@/index.css?raw";

// Graph strokes, markers, and legend swatches use the series tokens as
// non-text color, so each one needs 3:1 against the card (WCAG 1.4.11, #3004).

function block(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  return css.slice(start, css.indexOf("\n}", start));
}

function token(scope: string, name: string): string {
  const match = new RegExp(String.raw`--${name}:\s*(#[0-9a-fA-F]{6});`).exec(scope);
  if (!match) throw new Error(`missing --${name}`);
  return match[1];
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((offset) => {
    const channel = Number.parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(first: string, second: string): number {
  const [light, dark] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}

describe.each([
  { theme: "light", scope: block(":root") },
  { theme: "dark", scope: block(".dark") },
])("$theme chart series tokens", ({ scope }) => {
  const card = token(scope, "card");

  it.each([1, 2, 3, 4, 5, 6, 7, 8])("series %i has 3:1 contrast against the card", (slot) => {
    expect(contrast(token(scope, `series-${slot}`), card)).toBeGreaterThanOrEqual(3);
  });
});
