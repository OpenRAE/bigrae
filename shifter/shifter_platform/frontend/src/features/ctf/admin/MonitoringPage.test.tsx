import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { MonitoringPage } from "./MonitoringPage";

const mockApi = vi.mocked(apiFetch);

function render() {
  return renderRoute(<MonitoringPage defaultTab="scoreboard" />, {
    path: "/ctf/admin/events/:eventId/monitoring",
    initialEntries: ["/ctf/admin/events/e1/monitoring"],
  });
}

beforeEach(() => {
  mockApi.mockReset();
});

// Radix Select drives pointer capture and scrolling, which jsdom does not implement.
beforeAll(() => {
  window.HTMLElement.prototype.hasPointerCapture = vi.fn();
  window.HTMLElement.prototype.releasePointerCapture = vi.fn();
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

describe("MonitoringPage", () => {
  it("renders the tabs and the default scoreboard content", async () => {
    mockApi.mockResolvedValue({
      team_mode: false,
      frozen: false,
      rankings: [{ participant_id: "p1", name: "Ada Lovelace", score: 300, solve_count: 3, rank: 1 }],
    });
    render();
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Scoreboard" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Ranges" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Alerts" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Analytics" })).toBeInTheDocument();
  });

  it("shows the scoreboard empty state", async () => {
    mockApi.mockResolvedValue({ team_mode: false, frozen: false, rankings: [] });
    render();
    expect(await screen.findByText("No scores yet")).toBeInTheDocument();
  });

  it("loads the scoreboard from the organizer-scoreboard endpoint", async () => {
    mockApi.mockImplementation((path: string) =>
      path === "/ctf/events/e1/organizer-scoreboard/"
        ? Promise.resolve({
            team_mode: false,
            frozen: false,
            rankings: [{ participant_id: "p1", name: "Ada Lovelace", score: 300, solve_count: 3, rank: 1 }],
          })
        : Promise.resolve({}),
    );
    render();
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    // The organizer monitoring board must use the full-visibility organizer read,
    // not the public `/ctf/events/<id>/scoreboard/` hook (which honors freeze/hide).
    expect(mockApi).toHaveBeenCalledWith("/ctf/events/e1/organizer-scoreboard/", expect.anything());
  });

  it("reports a results export that fails", async () => {
    mockApi.mockImplementation((path: string) => {
      if (path.endsWith("/results/export/")) return Promise.reject(new TypeError("Failed to fetch"));
      // No analytics yet: the analytics card renders nothing for a null body.
      if (path.endsWith("/analytics/")) return Promise.resolve(null);
      return Promise.resolve({});
    });
    renderRoute(<MonitoringPage defaultTab="analytics" />, {
      path: "/ctf/admin/events/:eventId/monitoring",
      initialEntries: ["/ctf/admin/events/e1/monitoring"],
    });
    fireEvent.click(await screen.findByRole("button", { name: "Export results" }));
    expect(await screen.findByText("Could not export the results.")).toBeInTheDocument();
    expect(screen.queryByText("Failed to fetch")).not.toBeInTheDocument();
  });

  it("graphs the live score progression on the organizer scoreboard", async () => {
    mockApi.mockResolvedValue({
      team_mode: true,
      frozen: true,
      rankings: [{ team_id: "t1", name: "Red Team", score: 300, solve_count: 3, rank: 1 }],
      progression: {
        starts_at: "2026-11-21T10:00:00Z",
        ends_at: "2026-11-21T12:00:00Z",
        series: [
          {
            id: "t1",
            name: "Red Team",
            rank: 1,
            points: [
              { at: "2026-11-21T10:00:00Z", score: 0 },
              { at: "2026-11-21T11:00:00Z", score: 300 },
            ],
          },
        ],
      },
    });
    render();
    const graph = await screen.findByRole("img", { name: "Score over time" });
    // The organizer board is live, so the description names no freeze cutoff.
    expect(graph).toHaveAccessibleDescription("Cumulative score of the top 1 teams. Open Score history below the graph for each value.");
  });

  it("graphs and lists a participant's score timeline with the service fields", async () => {
    const user = userEvent.setup({ delay: null });
    mockApi.mockImplementation((path: string) => {
      if (path.endsWith("/participants/")) return Promise.resolve({ participants: [{ id: "p1", name: "Ada" }] });
      if (path.endsWith("/score-timeline/")) {
        return Promise.resolve({
          participant_id: "p1",
          participant_name: "Ada",
          timeline: [
            { timestamp: "2026-11-21T10:00:00Z", points: 0, cumulative: 0, label: "Event start", type: "start" },
            { timestamp: "2026-11-21T11:00:00Z", points: 150, cumulative: 150, label: "Web 1", type: "solve" },
            { timestamp: "2026-11-21T11:30:00Z", points: -20, cumulative: 130, label: "Penalty", type: "award" },
          ],
        });
      }
      if (path.endsWith("/analytics/")) return Promise.resolve(null);
      return Promise.resolve({});
    });
    renderRoute(<MonitoringPage defaultTab="analytics" />, {
      path: "/ctf/admin/events/:eventId/monitoring",
      initialEntries: ["/ctf/admin/events/e1/monitoring"],
    });

    await user.click(await screen.findByRole("combobox", { name: "Participant" }));
    await user.click(await screen.findByRole("option", { name: "Ada" }));

    expect(await screen.findByRole("img", { name: "Score over time" })).toBeInTheDocument();
    const penalty = screen.getByRole("row", { name: /Penalty/ });
    expect(penalty).toHaveTextContent("-20");
    expect(penalty).toHaveTextContent("130");
    expect(screen.getByRole("row", { name: /Web 1/ })).toHaveTextContent("150");
  });
});
