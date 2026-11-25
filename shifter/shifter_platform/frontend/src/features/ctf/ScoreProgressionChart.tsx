import { useId } from "react";

import type { CtfScoreProgression } from "@/api/types";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { formatDateTime } from "./format";

/** One competitor's score steps; `rank` is absent for a single-participant timeline. */
export interface ScoreSeries {
  id: string;
  name: string;
  rank?: number;
  points: ReadonlyArray<{ at: string; score: number }>;
}

// Fixed categorical order; a series keeps its slot by position (#3004).
const SERIES_STYLES = [
  { line: "stroke-series-1", swatch: "bg-series-1" },
  { line: "stroke-series-2", swatch: "bg-series-2" },
  { line: "stroke-series-3", swatch: "bg-series-3" },
  { line: "stroke-series-4", swatch: "bg-series-4" },
  { line: "stroke-series-5", swatch: "bg-series-5" },
  { line: "stroke-series-6", swatch: "bg-series-6" },
  { line: "stroke-series-7", swatch: "bg-series-7" },
  { line: "stroke-series-8", swatch: "bg-series-8" },
] as const;

// Plot geometry in SVG user units. The plot stretches to the SVG box, and strokes
// do not scale, so lines stay 2px and markers stay round at every width.
const WIDTH = 720;
const HEIGHT = 220;
const X_TICKS = 4;

interface Step {
  t: number;
  score: number;
}

/** Drop points with an unparseable time or a non-finite score; keep time order. */
function validSteps(series: ScoreSeries): Step[] {
  return series.points
    .map((point) => ({ t: Date.parse(point.at), score: point.score }))
    .filter((step) => Number.isFinite(step.t) && Number.isFinite(step.score));
}

/** A 1-2-5 tick step that gives about four intervals over `span`. */
function niceStep(span: number): number {
  const raw = Math.max(span, 1) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const factor = [1, 2, 5, 10].find((candidate) => candidate * magnitude >= raw) ?? 10;
  return Math.max(1, factor * magnitude);
}

/** Ticks from a step at or below `low` to a step at or above `high`, so every score stays inside the plot. */
function scoreTicks(low: number, high: number): number[] {
  const step = niceStep(high - low);
  const first = Math.floor(low / step);
  const last = Math.ceil(high / step);
  return Array.from({ length: last - first + 1 }, (_, index) => (first + index) * step);
}

/**
 * Zero-width time label box: the first label runs right, the last runs left,
 * others center. Narrow screens show only the start, middle, and end labels.
 */
function timeLabelClass(index: number): string {
  if (index === 0) return "flex justify-start";
  if (index === X_TICKS) return "flex justify-end";
  return index % 2 === 0 ? "flex justify-center" : "hidden justify-center sm:flex";
}

function timeLabel(t: number, spanMs: number): string {
  const options: Intl.DateTimeFormatOptions =
    spanMs > 86_400_000
      ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
      : { hour: "2-digit", minute: "2-digit" };
  return new Date(t).toLocaleString(undefined, options);
}

/**
 * Step graph of cumulative score over time (#3004). Exact values stay in the
 * page's table; this graph shows the race between the plotted competitors.
 */
export function ScoreProgressionChart({
  startsAt,
  endsAt,
  series,
  title,
  description,
}: Readonly<{
  startsAt: string;
  endsAt: string;
  series: ReadonlyArray<ScoreSeries>;
  title: string;
  description: string;
}>) {
  const titleId = useId();
  const descId = useId();
  const start = Date.parse(startsAt);
  const end = Date.parse(endsAt);
  const plotted = series.slice(0, SERIES_STYLES.length).map((entry) => ({ entry, steps: validSteps(entry) }));
  const scores = plotted.flatMap(({ steps }) => steps.map((step) => step.score));

  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || scores.length === 0) return null;

  const ticks = scoreTicks(Math.min(0, ...scores), Math.max(1, ...scores));
  const low = ticks[0];
  const high = ticks.at(-1) ?? 1;
  const x = (t: number) => ((Math.min(Math.max(t, start), end) - start) / (end - start)) * WIDTH;
  const y = (score: number) => HEIGHT - ((score - low) / (high - low || 1)) * HEIGHT;
  const showLegend = plotted.length > 1 || plotted[0].entry.rank !== undefined;
  const timeTicks = Array.from({ length: X_TICKS + 1 }, (_, index) => start + ((end - start) * index) / X_TICKS);

  // Axis labels are HTML text beside the SVG, so they keep their size on narrow
  // screens. Ticks are evenly spaced, so zero-size flex items put each label on
  // its gridline without inline positions. The label column and the SVG wrapper
  // share the same vertical padding, so edge labels stay inside their box.
  return (
    <figure className="m-0">
      <figcaption className="text-sm font-semibold">{title}</figcaption>
      <div className="mt-4 grid grid-cols-[auto_1fr] gap-x-2 text-[11px] text-muted-foreground">
        <div aria-hidden="true" data-axis="score" className="flex flex-col-reverse justify-between py-2 text-right">
          {ticks.map((tick) => (
            <span key={tick} className="flex h-0 items-center justify-end">
              <span>{tick.toLocaleString()}</span>
            </span>
          ))}
        </div>
        <div className="py-2">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          preserveAspectRatio="none"
          className="block h-56 w-full overflow-visible"
          role="img"
          aria-labelledby={titleId}
          aria-describedby={descId}
        >
          <title id={titleId}>{title}</title>
          <desc id={descId}>{description}</desc>
          {ticks.map((tick) => (
            <line
              key={tick}
              x1={0}
              x2={WIDTH}
              y1={y(tick)}
              y2={y(tick)}
              className={tick === 0 ? "stroke-muted-foreground" : "stroke-border"}
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {plotted.map(({ entry, steps }, index) => {
            if (steps.length === 0) return null;
            const style = SERIES_STYLES[index];
            const path = steps.reduce(
              (d, step, i) => (i === 0 ? `M${x(step.t)},${y(step.score)}` : `${d}H${x(step.t)}V${y(step.score)}`),
              "",
            );
            return (
              <g key={entry.id}>
                <path
                  d={`${path}H${x(end)}`}
                  fill="none"
                  strokeWidth={2}
                  vectorEffect="non-scaling-stroke"
                  className={style.line}
                />
                {steps.slice(1).map((step, stepIndex) => (
                  // A zero-length round-capped stroke draws an 8px dot that stays round when the plot stretches.
                  <path
                    key={`${step.t}-${stepIndex}`}
                    data-marker=""
                    d={`M${x(step.t)},${y(step.score)}h0`}
                    strokeWidth={8}
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                    className={style.line}
                  >
                    <title>{`${entry.name}: ${step.score.toLocaleString()} at ${new Date(step.t).toLocaleString()}`}</title>
                  </path>
                ))}
              </g>
            );
          })}
        </svg>
        </div>
        <span />
        <div aria-hidden="true" data-axis="time" className="flex justify-between">
          {timeTicks.map((tick, index) => (
            <span key={tick} className={`w-0 whitespace-nowrap ${timeLabelClass(index)}`}>
              <span>{timeLabel(tick, end - start)}</span>
            </span>
          ))}
        </div>
      </div>
      {showLegend ? (
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Graph legend">
          {plotted.map(({ entry }, index) => (
            <li key={entry.id} className="flex items-center gap-1.5">
              <span aria-hidden="true" className={`inline-block size-2.5 rounded-full ${SERIES_STYLES[index].swatch}`} />
              {entry.rank === undefined ? entry.name : `${entry.rank}. ${entry.name}`}
            </li>
          ))}
        </ul>
      ) : null}
    </figure>
  );
}

/** Text alternative for the graph: every plotted score change as a table row. */
function ScoreHistoryTable({ series }: Readonly<{ series: ReadonlyArray<ScoreSeries> }>) {
  return (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Score history</summary>
      <Table className="mt-2">
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>{series[0]?.rank === undefined ? "Name" : "Entry"}</TableHead>
            <TableHead>When</TableHead>
            <TableHead className="w-[120px] text-right">Score</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {series.flatMap((entry) =>
            entry.points.map((point, index) => (
              <TableRow key={`${entry.id}-${index}`}>
                <TableCell>{entry.rank === undefined ? entry.name : `${entry.rank}. ${entry.name}`}</TableCell>
                <TableCell className="text-muted-foreground">{formatDateTime(point.at)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{point.score.toLocaleString()}</TableCell>
              </TableRow>
            )),
          )}
        </TableBody>
      </Table>
    </details>
  );
}

/** The leaderboard graph card shared by the participant and organizer scoreboards. */
export function ScoreboardGraph({
  progression,
  teamMode,
  frozen,
}: Readonly<{ progression: CtfScoreProgression | null | undefined; teamMode: boolean; frozen: boolean }>) {
  if (!progression?.series.length) return null;
  const who = teamMode ? "teams" : "participants";
  const cutoff = frozen ? " up to the freeze" : "";
  return (
    <Card className="mb-4">
      <CardContent>
        <ScoreProgressionChart
          startsAt={progression.starts_at}
          endsAt={progression.ends_at}
          series={progression.series}
          title="Score over time"
          description={`Cumulative score of the top ${progression.series.length} ${who}${cutoff}. Open Score history below the graph for each value.`}
        />
        <ScoreHistoryTable series={progression.series} />
      </CardContent>
    </Card>
  );
}
