import { describe, expect, it } from "vitest";

import {
  adjacentChallenges,
  groupChallenges,
  isSolved,
  parseSort,
  parseView,
  readListView,
  sortChallenges,
} from "./challenge-list";

interface Row {
  id: string;
  name: string;
  category: string;
  points: number;
  difficulty: string;
  order: number;
  solved: boolean;
  team_solved: boolean;
  tags: string[];
  topics: string[];
}

function row(overrides: Partial<Row> = {}): Row {
  return {
    id: "c1",
    name: "Alpha",
    category: "web",
    points: 100,
    difficulty: "easy",
    order: 0,
    solved: false,
    team_solved: false,
    tags: [],
    topics: [],
    ...overrides,
  };
}

const ids = (items: readonly { id: string }[]) => items.map((item) => item.id);

describe("parseView and parseSort", () => {
  it("accept only the closed sets and fall back to the default", () => {
    expect(parseView("status")).toBe("status");
    expect(parseView("all")).toBe("all");
    expect(parseView(null)).toBe("category");
    expect(parseView("<script>")).toBe("category");
    expect(parseSort("points-desc")).toBe("points-desc");
    expect(parseSort(null)).toBe("order");
    expect(parseSort("constructor")).toBe("order");
  });
});

describe("isSolved", () => {
  it("counts a personal or a team solve", () => {
    expect(isSolved(row())).toBe(false);
    expect(isSolved(row({ solved: true }))).toBe(true);
    expect(isSolved(row({ team_solved: true }))).toBe(true);
  });
});

describe("sortChallenges", () => {
  const items = [
    row({ id: "a", name: "Charlie", points: 300, difficulty: "hard", order: 2 }),
    row({ id: "b", name: "alpha", points: 100, difficulty: "expert", order: 1 }),
    row({ id: "c", name: "Bravo", points: 200, difficulty: "easy", order: 0 }),
    row({ id: "d", name: "Delta", points: 200, difficulty: "unrated", order: 3 }),
    row({ id: "e", name: "Echo", points: 50, difficulty: "medium", order: 4 }),
  ];

  it("sorts by each key", () => {
    expect(ids(sortChallenges(items, "order"))).toEqual(["c", "b", "a", "d", "e"]);
    expect(ids(sortChallenges(items, "name"))).toEqual(["b", "c", "a", "d", "e"]);
    expect(ids(sortChallenges(items, "points-asc"))).toEqual(["e", "b", "c", "d", "a"]);
    expect(ids(sortChallenges(items, "points-desc"))).toEqual(["a", "c", "d", "b", "e"]);
    expect(ids(sortChallenges(items, "difficulty"))).toEqual(["c", "e", "a", "b", "d"]);
  });

  it("breaks full ties by ID", () => {
    const tied = [row({ id: "z" }), row({ id: "m" }), row({ id: "a" })];
    for (const sort of ["order", "name", "points-asc", "points-desc", "difficulty"] as const) {
      expect(ids(sortChallenges(tied, sort))).toEqual(["a", "m", "z"]);
    }
  });

  it("does not change the input array", () => {
    const input = Object.freeze([...items]);
    sortChallenges(input, "points-desc");
    expect(ids(input)).toEqual(["a", "b", "c", "d", "e"]);
  });
});

describe("groupChallenges", () => {
  const items = [
    row({ id: "m2", category: "Mission 2 — Example", order: 0 }),
    row({ id: "w", category: "Start Here", solved: true }),
    row({ id: "m10", category: "Mission 10 — Finale", team_solved: true }),
    row({ id: "u1", category: "", points: 500 }),
    row({ id: "m2b", category: "Mission 2 — Example", order: 1, points: 900 }),
  ];

  it("groups by category in the authored category order", () => {
    const groups = groupChallenges(items, "category", "order");
    expect(groups.map((group) => group.label)).toEqual([
      "Start Here",
      "Mission 2 — Example",
      "Mission 10 — Finale",
      "Uncategorized",
    ]);
    expect(ids(groups[1].items)).toEqual(["m2", "m2b"]);
  });

  it("applies the selected sort inside each category", () => {
    const groups = groupChallenges(items, "category", "points-desc");
    expect(ids(groups[1].items)).toEqual(["m2b", "m2"]);
  });

  it("partitions by solve state with not solved first", () => {
    const groups = groupChallenges(items, "status", "order");
    expect(groups.map((group) => group.label)).toEqual(["Not solved", "Solved"]);
    const notSolved = new Set(ids(groups[0].items));
    const solved = new Set(ids(groups[1].items));
    expect([...notSolved].filter((id) => solved.has(id))).toEqual([]);
    expect([...notSolved, ...solved].sort()).toEqual(ids(items).sort());
    expect(solved).toEqual(new Set(["w", "m10"]));
  });

  it("omits an empty status group", () => {
    const groups = groupChallenges([row({ id: "x" })], "status", "order");
    expect(groups.map((group) => group.label)).toEqual(["Not solved"]);
  });

  it("shows one unlabeled list sorted across categories", () => {
    const groups = groupChallenges(items, "all", "points-desc");
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBeNull();
    expect(ids(groups[0].items)).toEqual(["m2b", "u1", "m10", "m2", "w"]);
  });

  it("returns no group for an empty list", () => {
    expect(groupChallenges([], "all", "order")).toEqual([]);
    expect(groupChallenges([], "status", "order")).toEqual([]);
  });
});

describe("readListView", () => {
  const rows = [
    row({ id: "m2", name: "Mission two", category: "Mission 2", order: 0, tags: ["web"] }),
    row({ id: "s1", name: "Start", category: "Start Here", order: 0 }),
    row({ id: "m10", name: "Mission ten", category: "Mission 10", order: 0, tags: ["web"] }),
    row({ id: "m1b", name: "Mission one b", category: "Mission 1", order: 2 }),
    row({ id: "m1a", name: "Mission one a", category: "Mission 1", order: 1, tags: ["web"] }),
  ];
  const flat = (params: string) => readListView(rows, new URLSearchParams(params)).groups.flatMap((group) => ids(group.items));

  it("gives the chain order by default", () => {
    expect(flat("")).toEqual(["s1", "m1a", "m1b", "m2", "m10"]);
  });

  it("applies the view, the sort, and a known tag from the query parameters", () => {
    const view = readListView(rows, new URLSearchParams("view=all&sort=name&tag=web"));
    expect(view.view).toBe("all");
    expect(view.sort).toBe("name");
    expect(view.activeTag).toBe("web");
    expect(view.tagLabels).toEqual(["web"]);
    expect(view.groups.flatMap((group) => ids(group.items))).toEqual(["m1a", "m10", "m2"]);
  });

  it("ignores a tag or topic that no listed challenge has", () => {
    const view = readListView(rows, new URLSearchParams("tag=<b>x</b>&topic=missing"));
    expect(view.activeTag).toBeNull();
    expect(view.activeTopic).toBeNull();
    expect(view.groups.flatMap((group) => ids(group.items))).toEqual(["s1", "m1a", "m1b", "m2", "m10"]);
  });
});

describe("adjacentChallenges", () => {
  const groups = groupChallenges(
    [
      row({ id: "a", name: "A", category: "Mission 1", order: 0 }),
      row({ id: "b", name: "B", category: "Mission 1", order: 1 }),
      row({ id: "c", name: "C", category: "Mission 2", order: 0 }),
    ],
    "category",
    "order",
  );
  const neighbors = (id: string) => {
    const result = adjacentChallenges(groups, id);
    return [result.previous?.id ?? null, result.next?.id ?? null];
  };

  it("crosses group boundaries in the shown order", () => {
    expect(neighbors("b")).toEqual(["a", "c"]);
  });

  it("does not wrap at the start or the end", () => {
    expect(neighbors("a")).toEqual([null, "b"]);
    expect(neighbors("c")).toEqual(["b", null]);
  });

  it("gives no neighbors for one challenge or a challenge that is not shown", () => {
    expect(neighbors("missing")).toEqual([null, null]);
    const single = groupChallenges([row({ id: "only" })], "all", "order");
    expect(adjacentChallenges(single, "only")).toEqual({ previous: null, next: null });
    expect(adjacentChallenges([], "only")).toEqual({ previous: null, next: null });
  });
});
