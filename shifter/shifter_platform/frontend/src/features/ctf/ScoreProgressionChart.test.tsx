import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";

import { ScoreProgressionChart, type ScoreSeries } from "./ScoreProgressionChart";

const START = "2026-11-21T10:00:00Z";
const END = "2026-11-21T14:00:00Z";

function chart(series: ScoreSeries[], endsAt = END) {
  return render(
    <ScoreProgressionChart
      startsAt={START}
      endsAt={endsAt}
      series={series}
      title="Score over time"
      description="Cumulative score of the top teams."
    />,
  );
}

function linePaths(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("path:not([data-marker])")).map((path) => path.getAttribute("d") ?? "");
}

/** Marker centers in SVG user units, parsed from each `M x,y h0` marker stroke. */
function markers(container: HTMLElement): Array<{ x: number; y: number }> {
  return Array.from(container.querySelectorAll("path[data-marker]")).map((path) => {
    const [, x, y] = /^M([\d.-]+),([\d.-]+)h0$/.exec(path.getAttribute("d") ?? "") ?? [];
    return { x: Number(x), y: Number(y) };
  });
}

function scoreLabels(container: HTMLElement): number[] {
  return Array.from(container.querySelectorAll('[data-axis="score"] span span')).map((label) =>
    Number(label.textContent?.replaceAll(",", "")),
  );
}

describe("ScoreProgressionChart", () => {
  it("draws one step line per series, extended to the end of the axis", () => {
    const { container } = chart([
      { id: "a", name: "Alpha", rank: 1, points: [{ at: START, score: 0 }, { at: "2026-11-21T12:00:00Z", score: 300 }] },
      { id: "b", name: "Bravo", rank: 2, points: [{ at: START, score: 0 }, { at: "2026-11-21T13:00:00Z", score: 100 }] },
    ]);

    const paths = linePaths(container);
    expect(paths).toHaveLength(2);
    // Alpha: flat at zero to the 12:00 midpoint, up to 300 (the top tick), flat to the right edge.
    expect(paths[0]).toBe("M0,220H360V0H720");
    expect(paths[1]).toMatch(/^M0,220H540V\d+(\.\d+)?H720$/);
    expect(screen.getByRole("img", { name: "Score over time" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Graph legend" })).toHaveTextContent("1. Alpha2. Bravo");
    // Axis labels are HTML text outside the SVG: axe cannot check contrast of
    // SVG text inside an image, and SVG text would shrink with the plot.
    expect(container.querySelectorAll("svg text")).toHaveLength(0);
    expect(scoreLabels(container)).toEqual([0, 100, 200, 300]);
    expect(container.querySelectorAll('[data-axis="time"] span span')).toHaveLength(5);
  });

  it("keeps a negative score below a visible zero baseline", () => {
    const { container } = chart([
      { id: "a", name: "Alpha", rank: 1, points: [{ at: START, score: 0 }, { at: "2026-11-21T11:00:00Z", score: -40 }] },
    ]);

    const zeroY = Number(container.querySelector("line.stroke-muted-foreground")?.getAttribute("y1"));
    const lastY = Number(/V([\d.]+)H720$/.exec(linePaths(container)[0])?.[1]);
    expect(scoreLabels(container)).toContain(0);
    expect(lastY).toBeGreaterThan(zeroY);
  });

  it.each([
    { name: "a maximum between ticks", scores: [0, 120] },
    { name: "mixed positive and negative scores", scores: [0, -35, 120] },
  ])("keeps every score inside the plot for $name", ({ scores }) => {
    const points = scores.map((score, index) => ({ at: new Date(Date.parse(START) + index * 3_600_000).toISOString(), score }));
    const { container } = chart([{ id: "a", name: "Alpha", rank: 1, points }]);

    const ys = markers(container).map((marker) => marker.y);
    const ticks = scoreLabels(container);
    expect(ys.length).toBe(scores.length - 1);
    for (const y of ys) {
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(220);
    }
    expect(Math.max(...ticks)).toBeGreaterThanOrEqual(Math.max(...scores));
    expect(Math.min(...ticks)).toBeLessThanOrEqual(Math.min(...scores));
  });

  it("names each score step in a marker title", () => {
    const { container } = chart([
      { id: "a", name: "Alpha", rank: 1, points: [{ at: START, score: 0 }, { at: "2026-11-21T12:00:00Z", score: 300 }] },
    ]);

    const titles = Array.from(container.querySelectorAll("path[data-marker] title")).map((title) => title.textContent);
    expect(titles).toHaveLength(1);
    expect(titles[0]).toMatch(/^Alpha: 300 at /);
  });

  it("skips malformed points instead of plotting them as zero", () => {
    const { container } = chart([
      {
        id: "a",
        name: "Alpha",
        rank: 1,
        points: [
          { at: START, score: 0 },
          { at: "not-a-time", score: 50 },
          { at: "2026-11-21T12:00:00Z", score: Number.NaN },
        ],
      },
    ]);

    expect(linePaths(container)).toEqual(["M0,220H720"]);
    expect(markers(container)).toHaveLength(0);
  });

  it("renders nothing for an empty time range", () => {
    const { container } = chart([{ id: "a", name: "Alpha", rank: 1, points: [{ at: START, score: 0 }] }], START);
    expect(container).toBeEmptyDOMElement();
  });

  it("omits the legend for a single unranked series", () => {
    chart([{ id: "a", name: "Alpha", points: [{ at: START, score: 0 }, { at: END, score: 10 }] }]);
    expect(screen.queryByRole("list", { name: "Graph legend" })).not.toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    const { container } = chart([
      { id: "a", name: "Alpha", rank: 1, points: [{ at: START, score: 0 }, { at: "2026-11-21T12:00:00Z", score: 300 }] },
    ]);
    expect((await axe(container)).violations).toEqual([]);
  });
});
