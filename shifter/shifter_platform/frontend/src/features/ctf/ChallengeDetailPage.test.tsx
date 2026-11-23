import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";
import { ctfKeys } from "@/api/ctf";

import { ChallengeDetailPage } from "./ChallengeDetailPage";

const mockApi = vi.mocked(apiFetch);

const LIST_PATH = "/ctf/me/challenges/";
type Handler = (path: string, options?: { method?: string }) => unknown;

/** Answer the challenge list read with `list`, and send every other request to `handle`. */
function mockApiRoutes(handle: Handler, list: unknown = []) {
  mockApi.mockImplementation(async (path: string, options?: { method?: string }) => {
    if (path === LIST_PATH) {
      if (list instanceof Error) throw list;
      return list;
    }
    return handle(path, options);
  });
}

const ROUTE = { path: "/ctf/challenges/:id", initialEntries: ["/ctf/challenges/c1"] };

function detail(overrides: Record<string, unknown> = {}) {
  return {
    id: "c1",
    name: "SQL Injection",
    description: "Exploit the login form.",
    category: "web",
    points: 100,
    difficulty: "easy",
    max_attempts: 0,
    attempt_limit_mode: "unlimited",
    solved: false,
    team_solved: false,
    locked: false,
    attempt_count: 0,
    attempts_remaining: null,
    timeout_retry_after: null,
    hints: [],
    next_hint_id: null,
    next_hint_cost: 0,
    points_after_next_hint: 100,
    total_hint_penalty: 0,
    total_hint_penalty_points: 0,
    files: [],
    prerequisites_met: true,
    unmet_prerequisites: [],
    connection_info: null,
    show_solution: false,
    solution: null,
    rating: null,
    ...overrides,
  };
}

// GET the detail, then return a scored result for the submit POST. Both resolve.
function mockDetailThenSubmit(correct: boolean) {
  mockApiRoutes(async (path, options) => {
    if (options?.method === "POST" && path.includes("/submit/")) {
      return {
        correct,
        points_awarded: correct ? 100 : 0,
        attempt_number: 1,
        score: correct ? 100 : 0,
        rank: correct ? 1 : null,
        message: correct ? "Correct!" : "Incorrect flag.",
      };
    }
    return detail();
  });
}

beforeEach(() => {
  mockApi.mockReset();
});

function listed(id: string, name: string, category: string, order: number, points = 100) {
  return { id, name, category, points, difficulty: "easy", order, solved: false, team_solved: false, tags: [], topics: [] };
}

// Default chain order: Start Here, Mission 1 (by order), Mission 2. Points give another order.
const CHAIN = [
  listed("c3", "Pivot", "Mission 2", 0, 50),
  listed("c1", "SQL Injection", "Mission 1", 0, 300),
  listed("s1", "Warm-up", "Start Here", 0, 10),
  listed("c2", "Second Step", "Mission 1", 1, 200),
];
const NAMES: Readonly<Record<string, string>> = Object.fromEntries(CHAIN.map((item) => [item.id, item.name]));

/** Answer each detail read with the requested challenge. */
function mockChain(list: unknown = CHAIN) {
  mockApiRoutes((path) => {
    const id = /\/me\/challenges\/([^/]+)\/$/.exec(path)?.[1] ?? "c1";
    return detail({ id, name: NAMES[id] ?? id });
  }, list);
}

function sequenceNav() {
  return screen.getByRole("navigation", { name: "Challenge sequence" });
}

function chainRoute(entry: string) {
  return { path: "/ctf/challenges/:id/", initialEntries: [entry] };
}

describe("ChallengeDetailPage", () => {
  it("links the previous and next challenges in the default chain order", async () => {
    mockChain();
    renderRoute(<ChallengeDetailPage />, chainRoute("/ctf/challenges/c1/"));
    await screen.findByRole("heading", { name: "SQL Injection" });

    const nav = sequenceNav();
    expect(await within(nav).findByRole("link", { name: /Previous.*Warm-up/ })).toHaveAttribute(
      "href",
      "/ctf/challenges/s1/",
    );
    expect(within(nav).getByRole("link", { name: /Next.*Second Step/ })).toHaveAttribute("href", "/ctf/challenges/c2/");
  });

  it("follows the list order from the query parameters and keeps them", async () => {
    mockChain();
    renderRoute(<ChallengeDetailPage />, chainRoute("/ctf/challenges/c2/?view=all&sort=points-asc"));
    await screen.findByRole("heading", { name: "Second Step" });

    const nav = sequenceNav();
    expect(await within(nav).findByRole("link", { name: /Previous.*Pivot/ })).toHaveAttribute(
      "href",
      "/ctf/challenges/c3/?view=all&sort=points-asc",
    );
    expect(within(nav).getByRole("link", { name: /Next.*SQL Injection/ })).toHaveAttribute(
      "href",
      "/ctf/challenges/c1/?view=all&sort=points-asc",
    );
    expect(screen.getByRole("link", { name: "Challenges" })).toHaveAttribute(
      "href",
      "/ctf/challenges/?view=all&sort=points-asc",
    );
  });

  it("disables the previous button on the first challenge and the next button on the last", async () => {
    mockChain();
    const first = renderRoute(<ChallengeDetailPage />, chainRoute("/ctf/challenges/s1/"));
    await screen.findByRole("heading", { name: "Warm-up" });
    expect(await within(sequenceNav()).findByRole("link", { name: /Next.*SQL Injection/ })).toBeInTheDocument();
    expect(within(sequenceNav()).getByRole("button", { name: "Previous" })).toBeDisabled();
    first.unmount();

    renderRoute(<ChallengeDetailPage />, chainRoute("/ctf/challenges/c3/"));
    await screen.findByRole("heading", { name: "Pivot" });
    expect(await within(sequenceNav()).findByRole("link", { name: /Previous.*Second Step/ })).toBeInTheDocument();
    expect(within(sequenceNav()).getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("disables both buttons for a challenge that the list does not show", async () => {
    mockChain([listed("x1", "Other", "Mission 1", 0), listed("x2", "Another", "Mission 1", 1)]);
    renderRoute(<ChallengeDetailPage />, chainRoute("/ctf/challenges/c1/"));
    await screen.findByRole("heading", { name: "SQL Injection" });
    expect(within(sequenceNav()).getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(within(sequenceNav()).getByRole("button", { name: "Next" })).toBeDisabled();
    expect(within(sequenceNav()).queryByRole("link")).not.toBeInTheDocument();
  });

  it("disables both buttons when the list read fails and keeps the page", async () => {
    mockChain(new TypeError("Failed to fetch"));
    renderRoute(<ChallengeDetailPage />, chainRoute("/ctf/challenges/c1/"));
    await screen.findByRole("heading", { name: "SQL Injection" });
    expect(within(sequenceNav()).getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(within(sequenceNav()).getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByLabelText("Submit flag")).toBeInTheDocument();
  });

  it("disables both buttons when a list refresh fails after a cached read", async () => {
    let listFails = false;
    mockApiRoutes((path) => {
      const id = /\/me\/challenges\/([^/]+)\/$/.exec(path)?.[1] ?? "c1";
      return detail({ id, name: NAMES[id] ?? id });
    }, CHAIN);
    const routed = mockApi.getMockImplementation();
    mockApi.mockImplementation(async (path: string, options?: { method?: string }) => {
      if (path === LIST_PATH && listFails) throw new TypeError("Failed to fetch");
      return routed?.(path, options);
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const router = createMemoryRouter([{ path: "/ctf/challenges/:id/", element: <ChallengeDetailPage /> }], {
      initialEntries: ["/ctf/challenges/c1/"],
    });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await within(await screen.findByRole("navigation", { name: "Challenge sequence" })).findByRole("link", {
      name: /Next.*Second Step/,
    })).toBeInTheDocument();

    listFails = true;
    await act(async () => {
      await client.refetchQueries({ queryKey: ctfKeys.challenges(), exact: true });
    });

    expect(await within(sequenceNav()).findByRole("button", { name: "Previous" })).toBeDisabled();
    expect(within(sequenceNav()).getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("does not keep typed flag text on another challenge", async () => {
    mockChain();
    renderRoute(<ChallengeDetailPage />, chainRoute("/ctf/challenges/c1/"));
    await screen.findByRole("heading", { name: "SQL Injection" });

    fireEvent.click(await within(sequenceNav()).findByRole("link", { name: /Next.*Second Step/ }));
    await screen.findByRole("heading", { name: "Second Step" });
    fireEvent.change(screen.getByLabelText("Submit flag"), { target: { value: "FLAG{second}" } });

    // The first challenge is cached, so the page shows it with no loading state.
    fireEvent.click(within(sequenceNav()).getByRole("link", { name: /Previous.*SQL Injection/ }));
    await screen.findByRole("heading", { name: "SQL Injection" });
    expect(screen.getByLabelText("Submit flag")).toHaveValue("");
  });

  it("has no axe violations with the sequence buttons", async () => {
    mockChain();
    const { container } = renderRoute(<ChallengeDetailPage />, chainRoute("/ctf/challenges/s1/"));
    await screen.findByRole("heading", { name: "Warm-up" });
    await within(sequenceNav()).findByRole("link", { name: /Next/ });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("renders the challenge detail and flag form", async () => {
    mockApiRoutes(() =>detail());
    renderRoute(<ChallengeDetailPage />, ROUTE);
    expect(await screen.findByRole("heading", { name: "SQL Injection" })).toBeInTheDocument();
    expect(screen.getByText("Exploit the login form.")).toBeInTheDocument();
    expect(screen.getByLabelText("Submit flag")).toBeInTheDocument();
  });

  it("shows a team solve notice and keeps the flag form for an individual submit", async () => {
    mockApiRoutes(() =>detail({ team_solved: true }));
    renderRoute(<ChallengeDetailPage />, ROUTE);
    expect(await screen.findByRole("heading", { name: "SQL Injection" })).toBeInTheDocument();
    expect(screen.getAllByText("Solved by your team").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Submit flag")).toBeInTheDocument();
  });

  it("labels each hint with its point cost, not its percentage", async () => {
    mockApiRoutes(() =>
      detail({
        points: 200,
        hints: [
          { id: "h1", order: 0, penalty: 10, cost_points: 20, unlocked: true, text: "Look closer." },
          { id: "h2", order: 1, penalty: 20, cost_points: 40, unlocked: false, text: null },
        ],
        next_hint_id: "h2",
        next_hint_cost: 40,
        points_after_next_hint: 140,
        total_hint_penalty: 10,
        total_hint_penalty_points: 20,
      }),
    );
    renderRoute(<ChallengeDetailPage />, ROUTE);
    expect(await screen.findByText("−20 pts")).toBeInTheDocument();
    expect(screen.getByText("−40 pts")).toBeInTheDocument();
    expect(screen.getByText("−20 pts used")).toBeInTheDocument();
    expect(screen.queryByText("−10 pts")).not.toBeInTheDocument();
  });

  it("shows a success message after a correct submission", async () => {
    mockDetailThenSubmit(true);
    renderRoute(<ChallengeDetailPage />, ROUTE);
    fireEvent.change(await screen.findByLabelText("Submit flag"), { target: { value: "FLAG{x}" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Correct!")).toBeInTheDocument();
  });

  it("shows an incorrect message after a wrong submission", async () => {
    mockDetailThenSubmit(false);
    renderRoute(<ChallengeDetailPage />, ROUTE);
    fireEvent.change(await screen.findByLabelText("Submit flag"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Incorrect flag")).toBeInTheDocument();
  });

  it("reports a submission that fails without an API error, using authored copy", async () => {
    mockApiRoutes(async (path, options) => {
      if (options?.method === "POST" && path.includes("/submit/")) {
        throw new TypeError("Failed to fetch");
      }
      return detail();
    });
    renderRoute(<ChallengeDetailPage />, ROUTE);
    fireEvent.change(await screen.findByLabelText("Submit flag"), { target: { value: "FLAG{x}" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Could not submit")).toBeInTheDocument();
    expect(screen.getByText("The flag could not be submitted. Please try again.")).toBeInTheDocument();
    expect(screen.queryByText("Failed to fetch")).not.toBeInTheDocument();
  });

  it("reports a failed attachment download", async () => {
    mockApiRoutes(async (path) => {
      if (path.endsWith("/files/f1/download/")) throw new TypeError("Failed to fetch");
      return detail({ files: [{ id: "f1", filename: "notes.txt", display_name: "Notes" }] });
    });
    renderRoute(<ChallengeDetailPage />, ROUTE);
    fireEvent.click(await screen.findByRole("button", { name: "Download" }));
    expect(await screen.findByText("Could not download the file. Try again.")).toBeInTheDocument();
    expect(screen.queryByText("Failed to fetch")).not.toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApiRoutes(() =>detail());
    const { container } = renderRoute(<ChallengeDetailPage />, ROUTE);
    await screen.findByRole("heading", { name: "SQL Injection" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("shows a locked notice instead of the submit form for a locked challenge", async () => {
    mockApiRoutes(() =>detail({ locked: true }));
    renderRoute(<ChallengeDetailPage />, ROUTE);
    expect(await screen.findByText("Locked")).toBeInTheDocument();
    expect(screen.queryByLabelText("Submit flag")).not.toBeInTheDocument();
  });

  it("shows the rating control after a solve and records a rating", async () => {
    let rated = false;
    mockApiRoutes((path, options) => {
      if (options?.method === "POST" && path.includes("/rate/")) {
        rated = true;
        return { value: 5, challenge_id: "c1" };
      }
      return rated
        ? detail({ solved: true, rating: { average: 4.7, count: 3, own_rating: 5, public: true } })
        : detail({ solved: true, rating: { average: 4.5, count: 2, own_rating: null, public: true } });
    });
    renderRoute(<ChallengeDetailPage />, ROUTE);
    expect(await screen.findByRole("group", { name: /Rate this challenge/ })).toBeInTheDocument();
    expect(screen.getByText(/Average 4.5 from 2 ratings/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "5" }));
    expect(await screen.findByText(/Average 4.7 from 3 ratings/)).toBeInTheDocument();
  });

  it("hides the rating control when ratings are disabled or unsolved", async () => {
    mockApiRoutes(() =>detail({ solved: false, rating: { average: null, count: 0, own_rating: null, public: true } }));
    renderRoute(<ChallengeDetailPage />, ROUTE);
    await screen.findByRole("heading", { name: "SQL Injection" });
    expect(screen.queryByRole("group", { name: /Rate this challenge/ })).not.toBeInTheDocument();
  });
});
