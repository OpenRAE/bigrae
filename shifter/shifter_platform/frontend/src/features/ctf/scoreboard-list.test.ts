import { describe, expect, it } from "vitest";

import { filterScoreboardRows, parseScoreboardSort, sortScoreboardRows } from "./scoreboard-list";

// Server order: ranks with a shared rank (2) and a gap (4), a negative score,
// a duplicate name, and one malformed row.
const ROWS: Record<string, unknown>[] = [
  { rank: 1, participant_id: "a", name: "Mallory", score: 300, solve_count: 3 },
  { rank: 2, participant_id: "b", name: "alice", score: 200, solve_count: 5 },
  { rank: 2, participant_id: "c", name: "Bob", score: 200, solve_count: 5 },
  { rank: 4, participant_id: "d", name: "alice", score: -10, solve_count: 0 },
  { rank: "bad", participant_id: "e", name: "Zed", score: 0, solve_count: Number.NaN },
];

const ids = (rows: Record<string, unknown>[]) => rows.map((row) => row.participant_id);

describe("parseScoreboardSort", () => {
  it("accepts allowlisted values and falls back to rank", () => {
    expect(parseScoreboardSort("name")).toBe("name");
    expect(parseScoreboardSort("solves")).toBe("solves");
    expect(parseScoreboardSort("score; drop")).toBe("rank");
    expect(parseScoreboardSort(null)).toBe("rank");
  });
});

describe("sortScoreboardRows", () => {
  it("keeps the server order for rank", () => {
    expect(ids(sortScoreboardRows(ROWS, "rank"))).toEqual(["a", "b", "c", "d", "e"]);
  });

  it("sorts by name, with ties in server order", () => {
    const rows = sortScoreboardRows(ROWS, "name");
    expect(rows.map((row) => row.name)).toEqual(["alice", "alice", "Bob", "Mallory", "Zed"]);
    // Duplicate names keep the server (rank) order.
    expect(ids(rows).slice(0, 2)).toEqual(["b", "d"]);
  });

  it("sorts by solves, most first, with missing counts last and ties in server order", () => {
    expect(ids(sortScoreboardRows(ROWS, "solves"))).toEqual(["b", "c", "a", "d", "e"]);
  });

  it("does not change the input array or the official ranks", () => {
    const before = structuredClone(ROWS);
    const sorted = sortScoreboardRows(ROWS, "name");
    expect(sorted).not.toBe(ROWS);
    expect(ROWS).toEqual(before);
    expect(sorted.find((row) => row.participant_id === "c")?.rank).toBe(2);
  });
});

describe("filterScoreboardRows", () => {
  it("matches a trimmed substring of the name without case", () => {
    expect(ids(filterScoreboardRows(ROWS, "  ALI "))).toEqual(["b", "d"]);
  });

  it("returns a copy of every row for empty text", () => {
    const rows = filterScoreboardRows(ROWS, "   ");
    expect(rows).toEqual(ROWS);
    expect(rows).not.toBe(ROWS);
  });

  it("treats punctuation as literal text", () => {
    const rows = [
      { rank: 1, name: "<b>x</b>" },
      { rank: 2, name: "a.b" },
    ];
    expect(filterScoreboardRows(rows, ".*")).toEqual([]);
    expect(filterScoreboardRows(rows, "<b>")).toEqual([rows[0]]);
  });
});
