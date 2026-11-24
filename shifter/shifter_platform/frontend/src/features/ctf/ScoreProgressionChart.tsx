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
  { line: "stroke-series-1", dot: "fill-series-1", swatch: "bg-series-1" },
  { line: "stroke-series-2", dot: "fill-series-2", swatch: "bg-series-2" },
  { line: "stroke-series-3", dot: "fill-series-3", swatch: "bg-series-3" },
  { line: "stroke-series-4", dot: "fill-series-4", swatch: "bg-series-4" },
  { line: "stroke-series-5", dot: "fill-series-5", swatch: "bg-series-5" },
  { line: "stroke-series-6", dot: "fill-series-6", swatch: "bg-series-6" },
  { line: "stroke-series-7", dot: "fill-series-7", swatch: "bg-series-7" },
  { line: "stroke-series-8", dot: "fill-series-8", swatch: "bg-series-8" },
] as const;

const WIDTH = 720;
const HEIGHT = 260;
const PAD = { left: 52, right: 16, top: 12, bottom: 28 };
const PLOT_W = WIDTH - PAD.left - PAD.right;
const PLOT_H = HEIGHT - PAD.top - PAD.bottom;
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
  return factor * magnitude;
}

/** Ticks from a step at or below `low` to a step at or above `high`, so every score stays inside the plot. */
function scoreTicks(low: number, high: number): number[] {
  const step = niceStep(high - low);
  const first = Math.floor(low / step);
  const last = Math.ceil(high / step);
  return Array.from({ length: last - first + 1 }, (_, index) => (first + index) * step);
}

function tickAnchor(index: number): "start" | "middle" | "end" {
  if (index === 0) return "start";
  return index === X_TICKS ? "end" : "middle";
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
  const x = (t: number) => PAD.left + ((Math.min(Math.max(t, start), end) - start) / (end - start)) * PLOT_W;
  const y = (score: number) => PAD.top + PLOT_H - ((score - low) / (high - low || 1)) * PLOT_H;
  const showLegend = plotted.length > 1 || plotted[0].entry.rank !== undefined;
  const timeTicks = Array.from({ length: X_TICKS + 1 }, (_, index) => start + ((end - start) * index) / X_TICKS);

  return (
    <figure className="m-0">
      <figcaption className="text-sm font-semibold">{title}</figcaption>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="mt-2 h-auto w-full"
        role="img"
        aria-labelledby={titleId}
        aria-describedby={descId}
      >
        <title id={titleId}>{title}</title>
        <desc id={descId}>{description}</desc>
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={y(tick)}
              y2={y(tick)}
              className={tick === 0 ? "stroke-muted-foreground" : "stroke-border"}
              strokeWidth={1}
            />
            <text x={PAD.left - 8} y={y(tick)} textAnchor="end" dominantBaseline="middle" className="fill-muted-foreground text-[11px]">
              {tick.toLocaleString()}
            </text>
          </g>
        ))}
        {timeTicks.map((tick, index) => (
          <text
            key={tick}
            x={x(tick)}
            y={HEIGHT - 8}
            textAnchor={tickAnchor(index)}
            className="fill-muted-foreground text-[11px]"
          >
            {timeLabel(tick, end - start)}
          </text>
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
              <path d={`${path}H${x(end)}`} fill="none" strokeWidth={2} className={style.line} />
              {steps.slice(1).map((step, stepIndex) => (
                <circle key={`${step.t}-${stepIndex}`} cx={x(step.t)} cy={y(step.score)} r={4} className={style.dot}>
                  <title>{`${entry.name}: ${step.score.toLocaleString()} at ${new Date(step.t).toLocaleString()}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>
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
