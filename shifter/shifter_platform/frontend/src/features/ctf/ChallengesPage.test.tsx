import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/errors";

import { ChallengesPage } from "./ChallengesPage";

const mockApi = vi.mocked(apiFetch);

function challenge(overrides: Record<string, unknown> = {}) {
  return {
    id: "c1",
    name: "SQL Injection",
    category: "web",
    points: 100,
    difficulty: "easy",
    order: 0,
    solved: false,
    team_solved: false,
    ...overrides,
  };
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("ChallengesPage", () => {
  it("renders challenges grouped by category with solved status", async () => {
    mockApi.mockResolvedValue([
      challenge(),
      challenge({ id: "c2", name: "Buffer Overflow", category: "pwn", solved: true }),
    ]);
    renderRoute(<ChallengesPage />);
    expect(await screen.findByRole("link", { name: /SQL Injection/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Web" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pwn" })).toBeInTheDocument();
    expect(screen.getByText("Solved")).toBeInTheDocument();
  });

  it("shows a teammate's solve as solved by your team", async () => {
    mockApi.mockResolvedValue([challenge({ team_solved: true })]);
    renderRoute(<ChallengesPage />);
    expect(await screen.findByText("Solved by your team")).toBeInTheDocument();
    expect(screen.getByText("1 of 1 solved")).toBeInTheDocument();
  });

  it("renders authored mission categories in numeric mission order", async () => {
    mockApi.mockResolvedValue([
      challenge({ id: "c10", name: "Tenth", category: "Mission 10 — Finale" }),
      challenge({ id: "c2", name: "Second", category: "Mission 2 — Inside Example" }),
      challenge({ id: "c1", name: "First", category: "Mission 1 — Example" }),
    ]);
    renderRoute(<ChallengesPage />);

    const headings = await screen.findAllByRole("heading", { level: 2 });
    expect(headings.map((heading) => heading.textContent)).toEqual([
      "Mission 1 — Example",
      "Mission 2 — Inside Example",
      "Mission 10 — Finale",
    ]);
  });

  it("pins the participant warm-up ahead of the mission groups", async () => {
    mockApi.mockResolvedValue([
      challenge({ id: "c2", name: "Employee Directory", category: "Mission 1 — Example" }),
      challenge({ id: "warmup", name: "Start Here — Kali Warm-Up", category: "Start Here" }),
    ]);
    renderRoute(<ChallengesPage />);

    const headings = await screen.findAllByRole("heading", { level: 2 });
    expect(headings.map((heading) => heading.textContent)).toEqual(["Start Here", "Mission 1 — Example"]);
  });

  it("summarizes solved-of-total in the header", async () => {
    mockApi.mockResolvedValue([challenge(), challenge({ id: "c2", name: "B", solved: true })]);
    renderRoute(<ChallengesPage />);
    expect(await screen.findByText("1 of 2 solved")).toBeInTheDocument();
  });

  it("shows the empty state when there are no challenges", async () => {
    mockApi.mockResolvedValue([]);
    renderRoute(<ChallengesPage />);
    expect(await screen.findByText("No challenges available yet")).toBeInTheDocument();
  });

  it("reports a rejected query", async () => {
    mockApi.mockRejectedValue(new ApiError(503, { code: "unavailable", message: "Service unavailable" }));
    renderRoute(<ChallengesPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load challenges");
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue([challenge()]);
    const { container } = renderRoute(<ChallengesPage />);
    await screen.findByRole("link", { name: /SQL Injection/ });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("filters challenges by tag and clears on second click", async () => {
    mockApi.mockResolvedValue([
      challenge({ tags: ["xdr"], topics: ["sql-injection"] }),
      challenge({ id: "c2", name: "Buffer Overflow", category: "pwn", tags: ["linux"] }),
    ]);
    renderRoute(<ChallengesPage />);
    await screen.findByRole("link", { name: /SQL Injection/ });

    fireEvent.click(screen.getByRole("button", { name: "xdr" }));
    expect(screen.getByRole("link", { name: /SQL Injection/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Buffer Overflow/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "xdr" }));
    expect(screen.getByRole("link", { name: /Buffer Overflow/ })).toBeInTheDocument();
  });

  it("groups challenges by solved and not solved in the status view", async () => {
    mockApi.mockResolvedValue([
      challenge({ id: "c1", name: "Open One" }),
      challenge({ id: "c2", name: "Mine", category: "pwn", solved: true }),
      challenge({ id: "c3", name: "Teammate", category: "crypto", team_solved: true }),
    ]);
    renderRoute(<ChallengesPage />);
    await screen.findByRole("link", { name: /Open One/ });

    const viewGroup = screen.getByRole("group", { name: "View" });
    expect(viewGroup.tagName).toBe("FIELDSET");
    fireEvent.click(within(viewGroup).getByRole("button", { name: "By status" }));

    expect(screen.getByRole("button", { name: "By status" })).toHaveAttribute("aria-pressed", "true");
    const headings = screen.getAllByRole("heading", { level: 2 });
    expect(headings.map((heading) => heading.textContent)).toEqual(["Not solved", "Solved"]);
    const solved = screen.getByRole("region", { name: "Solved" });
    expect(within(solved).getAllByRole("link").map((link) => link.textContent)).toEqual([
      expect.stringContaining("Mine"),
      expect.stringContaining("Teammate"),
    ]);
    expect(within(screen.getByRole("region", { name: "Not solved" })).getAllByRole("link")).toHaveLength(1);
  });

  it("sorts the list by the selected key", async () => {
    mockApi.mockResolvedValue([
      challenge({ id: "c1", name: "Low", points: 50, order: 0 }),
      challenge({ id: "c2", name: "High", points: 500, order: 1 }),
      challenge({ id: "c3", name: "Mid", points: 200, order: 2 }),
    ]);
    renderRoute(<ChallengesPage />);
    await screen.findByRole("link", { name: /Low/ });
    const names = () => screen.getAllByRole("link").map((link) => link.querySelector("span")?.textContent);
    expect(names()).toEqual(["Low", "High", "Mid"]);

    fireEvent.change(screen.getByLabelText("Sort within groups"), { target: { value: "points-desc" } });
    expect(names()).toEqual(["High", "Mid", "Low"]);

    fireEvent.change(screen.getByLabelText("Sort within groups"), { target: { value: "name" } });
    expect(names()).toEqual(["High", "Low", "Mid"]);
  });

  it("restores the view and sort from the URL", async () => {
    mockApi.mockResolvedValue([
      challenge({ id: "c1", name: "Low", category: "web", points: 50 }),
      challenge({ id: "c2", name: "High", category: "pwn", points: 500 }),
    ]);
    renderRoute(<ChallengesPage />, { initialEntries: ["/?view=all&sort=points-desc"] });
    await screen.findByRole("link", { name: /Low/ });

    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Sort within groups")).toHaveValue("points-desc");
    expect(screen.queryByRole("heading", { level: 2 })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link").map((link) => link.querySelector("span")?.textContent)).toEqual(["High", "Low"]);
  });

  it("ignores unknown view, sort, and label values in the URL", async () => {
    mockApi.mockResolvedValue([challenge(), challenge({ id: "c2", name: "Buffer Overflow", category: "pwn" })]);
    renderRoute(<ChallengesPage />, { initialEntries: ["/?view=bogus&sort=bogus&tag=missing&topic=missing"] });
    await screen.findByRole("link", { name: /SQL Injection/ });

    expect(screen.getByRole("link", { name: /Buffer Overflow/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "By category" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Sort within groups")).toHaveValue("order");
  });

  it("filters by a markup-like tag without rendering it as markup", async () => {
    const tag = '<img src=x onerror="alert(1)">';
    mockApi.mockResolvedValue([
      challenge({ tags: [tag] }),
      challenge({ id: "c2", name: "Buffer Overflow", category: "pwn" }),
    ]);
    const { container } = renderRoute(<ChallengesPage />, {
      initialEntries: [`/?tag=${encodeURIComponent(tag)}`],
    });
    await screen.findByRole("link", { name: /SQL Injection/ });

    expect(screen.queryByRole("link", { name: /Buffer Overflow/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: tag })).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector("img")).toBeNull();
  });

  it("keeps the controls when no challenge matches the filters", async () => {
    mockApi.mockResolvedValue([
      challenge({ tags: ["xdr"] }),
      challenge({ id: "c2", name: "Buffer Overflow", category: "pwn", topics: ["linux"] }),
    ]);
    renderRoute(<ChallengesPage />, { initialEntries: ["/?tag=xdr&topic=linux"] });

    expect(await screen.findByText("No challenges match this filter")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "xdr" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "By status" })).toBeInTheDocument();
    expect(screen.getByLabelText("Sort within groups")).toBeInTheDocument();
  });

  it("keeps the list state after opening a challenge and going back", async () => {
    mockApi.mockResolvedValue([challenge(), challenge({ id: "c2", name: "Solved One", solved: true })]);
    const router = createMemoryRouter(
      [
        { path: "/ctf/challenges/", element: <ChallengesPage /> },
        { path: "/ctf/challenges/:challengeId/", element: <p>Challenge detail</p> },
      ],
      { initialEntries: ["/ctf/challenges/"] },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    await screen.findByRole("link", { name: /SQL Injection/ });

    fireEvent.click(screen.getByRole("button", { name: "By status" }));
    fireEvent.change(screen.getByLabelText("Sort within groups"), { target: { value: "name" } });
    fireEvent.click(screen.getByRole("link", { name: /SQL Injection/ }));
    expect(await screen.findByText("Challenge detail")).toBeInTheDocument();

    await act(async () => {
      await router.navigate(-1);
    });

    expect(await screen.findByRole("button", { name: "By status" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Sort within groups")).toHaveValue("name");
  });

  it("keeps the list query parameters on each challenge link", async () => {
    mockApi.mockResolvedValue([challenge()]);
    renderRoute(<ChallengesPage />, { initialEntries: ["/?view=all&sort=name"] });
    expect(await screen.findByRole("link", { name: /SQL Injection/ })).toHaveAttribute(
      "href",
      "/ctf/challenges/c1/?view=all&sort=name",
    );
  });

  it("has no axe violations in the status view", async () => {
    mockApi.mockResolvedValue([challenge({ tags: ["xdr"] }), challenge({ id: "c2", name: "B", solved: true })]);
    const { container } = renderRoute(<ChallengesPage />, { initialEntries: ["/?view=status"] });
    await screen.findByRole("link", { name: /SQL Injection/ });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
