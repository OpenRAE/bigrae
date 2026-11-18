import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";
import type { Bootstrap } from "@/api/types";
import { router } from "@/router";
import { STAFF_BOOTSTRAP } from "@/test/utils";

const PARTICIPANT: Bootstrap = {
  ...STAFF_BOOTSTRAP,
  permissions: { ...STAFF_BOOTSTRAP.permissions, is_ctf_participant: true },
  modes: { participant: true, operator: false, default: "participant" },
};

const TEAM_EVENT = { event: { id: "e1", name: "Spring CTF", team_mode: true }, participant: { id: "p1" } };

/** Resolve the session and workspace reads; the board read returns rows for the requested kind only. */
function mockWorkspace() {
  vi.mocked(apiFetch).mockImplementation(async (path?: string, options?: { query?: Record<string, unknown> }) => {
    if (path === "/bootstrap/") return PARTICIPANT;
    if (path === "/ctf/me/event/") return TEAM_EVENT;
    if (path === "/ctf/events/e1/scoreboard/") {
      const team = options?.query?.kind === "team";
      return {
        scoreboard_hidden: false,
        event_id: "e1",
        team_mode: true,
        frozen: false,
        rankings: [{ rank: 1, name: team ? "Red Team" : "Alice", score: 100, solve_count: 2 }],
        bracket_rankings: null,
        brackets: [],
      };
    }
    return {};
  });
}

function renderAt(path: string) {
  const memoryRouter = createMemoryRouter(router.routes, { initialEntries: [path] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={memoryRouter} />
    </QueryClientProvider>,
  );
  return memoryRouter;
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  mockWorkspace();
});

describe("team-mode scoreboard routes (#2968)", () => {
  it("opens each board from its sidebar entry", async () => {
    const user = userEvent.setup();
    const memoryRouter = renderAt("/ctf/");
    const nav = await screen.findByRole("navigation", { name: "Primary" });

    await user.click(await within(nav).findByRole("link", { name: "Team scoreboard" }));
    expect(await screen.findByRole("heading", { name: "Team scoreboard" })).toBeInTheDocument();
    expect(await screen.findByText("Red Team")).toBeInTheDocument();
    expect(memoryRouter.state.location.pathname).toBe("/ctf/team-scoreboard/");
    expect(within(nav).getByRole("link", { name: "Team scoreboard" })).toHaveAttribute("aria-current", "page");

    await user.click(within(nav).getByRole("link", { name: "Individual scoreboard" }));
    expect(await screen.findByRole("heading", { name: "Individual scoreboard" })).toBeInTheDocument();
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.queryByText("Red Team")).not.toBeInTheDocument();
    expect(memoryRouter.state.location.pathname).toBe("/ctf/individual-scoreboard/");
    expect(within(nav).getByRole("link", { name: "Individual scoreboard" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Team scoreboard" })).not.toHaveAttribute("aria-current");
  });

  it("opens the team board from a deep link", async () => {
    renderAt("/ctf/team-scoreboard/");
    expect(await screen.findByRole("heading", { name: "Team scoreboard" })).toBeInTheDocument();
    expect(await screen.findByText("Red Team")).toBeInTheDocument();
  });
});
