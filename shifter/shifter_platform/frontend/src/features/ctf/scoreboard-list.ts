/**
 * Browser-side sort and name filter for a participant scoreboard (#3001). The
 * scoreboard API stays the disclosure boundary: these functions only filter
 * and reorder the rows it returned, and never change their input arrays.
 */

import { rankingNumber, rankingString } from "./format";

export const SCOREBOARD_SORTS = [
  { value: "rank", label: "Rank" },
  { value: "name", label: "Name, A to Z" },
  { value: "solves", label: "Solves, most first" },
] as const;

export type ScoreboardSort = (typeof SCOREBOARD_SORTS)[number]["value"];

type Row = Record<string, unknown>;

/** Return the allowlisted sort, or the default for a missing or unknown value. */
export function parseScoreboardSort(value: string | null): ScoreboardSort {
  return SCOREBOARD_SORTS.find((sort) => sort.value === value)?.value ?? "rank";
}

/** A finite numeric field, or null; a missing or malformed value never reaches a comparison. */
function finiteNumber(row: Row, key: string): number | null {
  const value = rankingNumber(row, key);
  return value !== null && Number.isFinite(value) ? value : null;
}

type Compare = (left: Row, right: Row) => number;

const byName: Compare = (left, right) => rankingString(left, "name").localeCompare(rankingString(right, "name"));

/** Solve count, high to low; a missing count sorts after every valid count. */
const bySolvesDesc: Compare = (left, right) => {
  const leftCount = finiteNumber(left, "solve_count");
  const rightCount = finiteNumber(right, "solve_count");
  if (leftCount === null || rightCount === null) return Number(leftCount === null) - Number(rightCount === null);
  return rightCount - leftCount;
};

// The server returns rows in rank order. `rank` keeps that order, and the
// stable sort keeps it for ties on the other keys.
const COMPARES: Readonly<Record<ScoreboardSort, Compare | null>> = {
  rank: null,
  name: byName,
  solves: bySolvesDesc,
};

/** Rows whose shown name contains the trimmed text, without case. Empty text matches every row. */
export function filterScoreboardRows<T extends Row>(rows: readonly T[], text: string): T[] {
  const term = text.trim().toLocaleLowerCase();
  if (!term) return [...rows];
  return rows.filter((row) => rankingString(row, "name").toLocaleLowerCase().includes(term));
}

/** Return a sorted copy of the rows. */
export function sortScoreboardRows<T extends Row>(rows: readonly T[], sort: ScoreboardSort): T[] {
  const compare = COMPARES[sort];
  return compare ? [...rows].sort(compare) : [...rows];
}
