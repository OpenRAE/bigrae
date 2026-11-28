import { beforeEach, describe, expect, it, vi } from "vitest";
import { focusManager } from "@tanstack/react-query";
import { act, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute, setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ScoreboardPage } from "./ScoreboardPage";

const mockApi = vi.mocked(apiFetch);

const EVENT = { event: { id: "e1", name: "Spring CTF" }, participant: { id: "p1" } };
const TEAM_EVENT = { event: { id: "e1", name: "Spring CTF", team_mode: true }, participant: { id: "p1" } };

// Resolve both reads the page makes: the current event (for its id) and the
// event scoreboard. `path` is optional-guarded because vitest's afterEach mock
// cleanup can invoke the spy once with no arguments; that return value is
// discarded, so it safely falls through to the scoreboard payload.
function mockScoreboard(payload: Record<string, unknown>) {
  mockApi.mockImplementation(async (path?: string) => {
    if (path?.includes("/me/event/")) return EVENT;
    return payload;
  });
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("ScoreboardPage", () => {
  it("renders rankings", async () => {
    mockScoreboard({
      scoreboard_hidden: false,
      event_id: "e1",
      team_mode: false,
      frozen: false,
      rankings: [{ rank: 1, participant_id: "p1", name: "Alice", score: 100, solve_count: 2 }],
      bracket_rankings: null,
      brackets: [],
    });
    renderRoute(<ScoreboardPage />);
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
  });

  it("shows a freeze indicator when the board is frozen", async () => {
    mockScoreboard({
      scoreboard_hidden: false,
      event_id: "e1",
      team_mode: false,
      frozen: true,
      rankings: [{ rank: 1, participant_id: "p1", name: "Alice", score: 100, solve_count: 2 }],
      bracket_rankings: null,
      brackets: [],
    });
    renderRoute(<ScoreboardPage />);
    expect(await screen.findByText("Frozen")).toBeInTheDocument();
  });

  it("shows the hidden sentinel when the scoreboard is hidden", async () => {
    mockScoreboard({
      scoreboard_hidden: true,
      event_id: "e1",
      team_mode: false,
      frozen: false,
      rankings: [],
      bracket_rankings: null,
      brackets: [],
    });
    renderRoute(<ScoreboardPage />);
    expect(await screen.findByText("Scoreboard hidden")).toBeInTheDocument();
  });

  it("graphs the published score progression above the table", async () => {
    mockScoreboard({
      scoreboard_hidden: false,
      event_id: "e1",
      team_mode: false,
      frozen: true,
      rankings: [{ rank: 1, participant_id: "p1", name: "Alice", score: 100, solve_count: 2 }],
      bracket_rankings: null,
      brackets: [],
      progression: {
        starts_at: "2026-11-21T10:00:00Z",
        ends_at: "2026-11-21T12:00:00Z",
        series: [
          {
            id: "p1",
            name: "Alice",
            rank: 1,
            points: [
              { at: "2026-11-21T10:00:00Z", score: 0 },
              { at: "2026-11-21T11:00:00Z", score: 100 },
            ],
          },
        ],
      },
    });
    const { container } = renderRoute(<ScoreboardPage />);
    const graph = await screen.findByRole("img", { name: "Score over time" });
    expect(graph).toHaveAccessibleDescription(
      "Cumulative score of the top 1 participants up to the freeze. Open Score history below the graph for each value.",
    );
    expect(screen.getByRole("list", { name: "Graph legend" })).toHaveTextContent("1. Alice");

    // The history is readable without the SVG: a native disclosure (keyboard-operable
    // in browsers; jsdom only activates it by click) holding a table.
    const user = setupUser();
    const summary = screen.getByText("Score history");
    expect(summary.tagName).toBe("SUMMARY");
    await user.click(summary);
    expect(summary.closest("details")).toHaveAttribute("open");
    const rows = within(summary.closest("details") as HTMLElement).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("cell").at(-1)?.textContent)).toEqual(["0", "100"]);
    expect(rows[1]).toHaveTextContent("1. Alice");
    expect((await axe(container)).violations).toEqual([]);
  });

  it("shows no graph when the board publishes no progression", async () => {
    mockScoreboard({
      scoreboard_hidden: false,
      event_id: "e1",
      team_mode: false,
      frozen: false,
      rankings: [{ rank: 1, participant_id: "p1", name: "Alice", score: 100, solve_count: 2 }],
      bracket_rankings: null,
      brackets: [],
      progression: null,
    });
    renderRoute(<ScoreboardPage />);
    await screen.findByText("Alice");
    expect(screen.queryByRole("img", { name: "Score over time" })).not.toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockScoreboard({
      scoreboard_hidden: false,
      event_id: "e1",
      team_mode: false,
      frozen: false,
      rankings: [{ rank: 1, participant_id: "p1", name: "Alice", score: 100, solve_count: 2 }],
      bracket_rankings: null,
      brackets: [],
    });
    const { container } = renderRoute(<ScoreboardPage />);
    await screen.findByText("Alice");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

describe("ScoreboardPage kinds (#2968)", () => {
  const BOARD = {
    scoreboard_hidden: false,
    event_id: "e1",
    team_mode: true,
    frozen: false,
    bracket_rankings: null,
    brackets: [],
  };

  function mockTeamEvent() {
    mockApi.mockImplementation(async (path?: string, options?: { query?: Record<string, unknown> }) => {
      if (path?.includes("/me/event/")) return TEAM_EVENT;
      const name = options?.query?.kind === "team" ? "Red Team" : "Alice";
      return { ...BOARD, rankings: [{ rank: 1, name, score: 100, solve_count: 2 }] };
    });
  }

  it("opens the individual board of a team-mode event", async () => {
    mockTeamEvent();
    renderRoute(<ScoreboardPage kind="individual" />);
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Individual scoreboard" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
  });

  it("opens the team board of a team-mode event", async () => {
    mockTeamEvent();
    renderRoute(<ScoreboardPage kind="team" />);
    expect(await screen.findByText("Red Team")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Team scoreboard" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Team" })).toBeInTheDocument();
  });

  it("shows a notice and reads no board for the team board of a solo event", async () => {
    mockApi.mockImplementation(async (path?: string) => {
      if (path?.includes("/me/event/")) return EVENT;
      throw new Error("unexpected scoreboard read");
    });
    renderRoute(<ScoreboardPage kind="team" />);
    expect(await screen.findByText("No team scoreboard")).toBeInTheDocument();
    expect(mockApi.mock.calls.some(([path]) => path?.includes("/scoreboard/"))).toBe(false);
  });
});

describe("ScoreboardPage sort and filter (#3001)", () => {
  const BOARD = {
    scoreboard_hidden: false,
    event_id: "e1",
    team_mode: false,
    frozen: false,
    brackets: [{ id: "b1", name: "Students" }],
    // Server rank order, with a shared rank and a gap.
    rankings: [
      { rank: 1, participant_id: "p1", name: "Mallory", score: 300, solve_count: 1 },
      { rank: 2, participant_id: "p2", name: "Bob", score: 200, solve_count: 4 },
      { rank: 2, participant_id: "p3", name: "Alice", score: 200, solve_count: 4 },
      { rank: 4, participant_id: "p4", name: "Alicia", score: -5, solve_count: 0 },
    ],
  };
  const BRACKET_ROWS = [
    { rank: 1, participant_id: "p3", name: "Alice", score: 200, solve_count: 4 },
    { rank: 2, participant_id: "p5", name: "Carol", score: 50, solve_count: 1 },
  ];

  function mockBoard() {
    mockApi.mockImplementation(async (path?: string, options?: { query?: Record<string, unknown> }) => {
      if (path?.includes("/me/event/")) return EVENT;
      const bracket = options?.query?.bracket;
      return { ...BOARD, bracket_rankings: bracket ? BRACKET_ROWS : null };
    });
  }

  /** Name and rank of each body row, in display order. */
  function shownRows() {
    return screen
      .getAllByRole("row")
      .slice(1)
      .map((row) => {
        const cells = within(row).getAllByRole("cell");
        return `${cells[0].textContent} ${cells[1].textContent}`;
      });
  }

  async function chooseSort(user: ReturnType<typeof setupUser>, label: string) {
    await user.click(screen.getByRole("combobox", { name: "Sort by" }));
    await user.click(await screen.findByRole("option", { name: label }));
  }

  it("sorts the rows and keeps the official ranks", async () => {
    mockBoard();
    const user = setupUser();
    renderRoute(<ScoreboardPage />);
    await screen.findByText("Mallory");
    expect(shownRows()).toEqual(["1 Mallory", "2 Bob", "2 Alice", "4 Alicia"]);

    await chooseSort(user, "Name, A to Z");
    expect(shownRows()).toEqual(["2 Alice", "4 Alicia", "2 Bob", "1 Mallory"]);

    await chooseSort(user, "Solves, most first");
    expect(shownRows()).toEqual(["2 Bob", "2 Alice", "1 Mallory", "4 Alicia"]);

    await chooseSort(user, "Rank");
    expect(shownRows()).toEqual(["1 Mallory", "2 Bob", "2 Alice", "4 Alicia"]);
  });

  it("filters the rows by name and shows a no-match state with the controls", async () => {
    mockBoard();
    const user = setupUser();
    renderRoute(<ScoreboardPage />);
    await screen.findByText("Mallory");

    const filter = screen.getByLabelText("Filter participants");
    await user.type(filter, "  ALI");
    expect(shownRows()).toEqual(["2 Alice", "4 Alicia"]);

    await user.clear(filter);
    await user.type(filter, "<img src=x>");
    expect(screen.getByText("No entries match this filter")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByLabelText("Filter participants")).toHaveValue("<img src=x>");

    await user.clear(filter);
    expect(shownRows()).toHaveLength(4);
  });

  it("applies the filter and sort to the selected bracket rows", async () => {
    mockBoard();
    const user = setupUser();
    renderRoute(<ScoreboardPage />);
    await screen.findByText("Mallory");
    await user.type(screen.getByLabelText("Filter participants"), "a");
    await chooseSort(user, "Name, A to Z");

    await user.click(screen.getByRole("combobox", { name: "Filter by bracket" }));
    await user.click(await screen.findByRole("option", { name: "Students" }));

    expect(await screen.findByText("Carol")).toBeInTheDocument();
    expect(shownRows()).toEqual(["1 Alice", "2 Carol"]);
    expect(screen.getByLabelText("Filter participants")).toHaveValue("a");
  });

  it("labels the filter for the team board", async () => {
    mockApi.mockImplementation(async (path?: string) => {
      if (path?.includes("/me/event/")) return TEAM_EVENT;
      return { ...BOARD, team_mode: true, brackets: [], rankings: [{ rank: 1, team_id: "t1", name: "Red Team" }] };
    });
    renderRoute(<ScoreboardPage kind="team" />);
    await screen.findByText("Red Team");
    expect(screen.getByLabelText("Filter teams")).toBeInTheDocument();
  });

  it("shows a dash, not a position, for a row without a rank", async () => {
    mockApi.mockImplementation(async (path?: string) => {
      if (path?.includes("/me/event/")) return EVENT;
      return { ...BOARD, brackets: [], rankings: [{ participant_id: "p9", name: "Nora", score: 1, solve_count: 1 }] };
    });
    renderRoute(<ScoreboardPage />);
    await screen.findByText("Nora");
    expect(shownRows()).toEqual(["— Nora"]);
  });

  /** Refetch every stale query, as a window focus or a poll does. */
  async function refetchOnFocus() {
    await act(async () => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    focusManager.setFocused(undefined);
  }

  it("keeps the controls across a refresh and applies them to the new rows", async () => {
    let reads = 0;
    mockApi.mockImplementation(async (path?: string) => {
      if (path?.includes("/me/event/")) return EVENT;
      reads += 1;
      const extra = reads > 1 ? [{ rank: 5, participant_id: "p6", name: "Alina", score: 1, solve_count: 9 }] : [];
      return { ...BOARD, brackets: [], bracket_rankings: null, rankings: [...BOARD.rankings, ...extra] };
    });
    const user = setupUser();
    renderRoute(<ScoreboardPage />);
    await screen.findByText("Mallory");
    await user.type(screen.getByLabelText("Filter participants"), "ali");
    await chooseSort(user, "Solves, most first");

    await refetchOnFocus();

    expect(await screen.findByText("Alina")).toBeInTheDocument();
    expect(shownRows()).toEqual(["5 Alina", "2 Alice", "4 Alicia"]);
    expect(screen.getByLabelText("Filter participants")).toHaveValue("ali");
  });

  it("resets the controls when the current event changes", async () => {
    let eventReads = 0;
    mockApi.mockImplementation(async (path?: string) => {
      if (path?.includes("/me/event/")) {
        eventReads += 1;
        return eventReads > 1 ? { ...EVENT, event: { id: "e2", name: "Fall CTF" } } : EVENT;
      }
      return { ...BOARD, brackets: [], bracket_rankings: null };
    });
    const user = setupUser();
    renderRoute(<ScoreboardPage />);
    await screen.findByText("Mallory");
    await user.type(screen.getByLabelText("Filter participants"), "bob");
    expect(shownRows()).toEqual(["2 Bob"]);

    await refetchOnFocus();

    expect(await screen.findByText("Mallory")).toBeInTheDocument();
    expect(screen.getByLabelText("Filter participants")).toHaveValue("");
    expect(mockApi.mock.calls.some(([path]) => path?.includes("/events/e2/scoreboard/"))).toBe(true);
  });

  it("has no axe violations with the controls", async () => {
    mockBoard();
    const { container } = renderRoute(<ScoreboardPage />);
    await screen.findByText("Mallory");
    expect((await axe(container)).violations).toEqual([]);
  });
});
