import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { axe } from "vitest-axe";

import type { Bootstrap } from "@/api/types";
import { STAFF_BOOTSTRAP } from "@/test/utils";

let currentBootstrap: Bootstrap = STAFF_BOOTSTRAP;

vi.mock("@/app/bootstrap-context", () => ({
  useBootstrapContext: () => currentBootstrap,
}));
vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { ModeProvider } from "@/app/mode";

import { AppShell } from "./app-shell";

function renderShell(bootstrap: Bootstrap = STAFF_BOOTSTRAP) {
  currentBootstrap = bootstrap;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ModeProvider bootstrap={bootstrap}>
          <AppShell>
            <h1>Page content</h1>
          </AppShell>
        </ModeProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const PARTICIPANT_BOOTSTRAP: Bootstrap = {
  ...STAFF_BOOTSTRAP,
  permissions: { ...STAFF_BOOTSTRAP.permissions, is_ctf_participant: true },
  modes: { participant: true, operator: false, default: "participant" },
};

function mockCurrentEvent(teamMode: boolean) {
  vi.mocked(apiFetch).mockResolvedValue({ event: { id: "e1", team_mode: teamMode }, participant: { id: "p1" } });
}

beforeEach(() => {
  currentBootstrap = STAFF_BOOTSTRAP;
  vi.mocked(apiFetch).mockReset();
});

describe("AppShell", () => {
  it("renders the skip link and core landmarks", () => {
    renderShell();
    expect(screen.getByRole("link", { name: /skip to content/i })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
  });

  it("renders operator nav groups from the shared contract", () => {
    renderShell();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(nav).toHaveTextContent("Operate");
    expect(nav).toHaveTextContent("Overview");
  });

  it("links not-yet-migrated surfaces to their legacy Django route (full-page nav)", () => {
    renderShell();
    expect(screen.getByRole("link", { name: /Ranges/ })).toHaveAttribute("href", "/mission-control/");
  });

  it("offers a POST logout form", () => {
    renderShell();
    const button = screen.getByRole("button", { name: /log out/i });
    const form = button.closest("form");
    expect(form).toHaveAttribute("action", "/logout/");
    expect(form).toHaveAttribute("method", "post");
  });

  it("hides the mode switch when only one mode is eligible", () => {
    renderShell();
    expect(screen.queryByRole("group", { name: "Mode" })).not.toBeInTheDocument();
  });

  it("shows the mode switch when both modes are eligible", () => {
    renderShell({
      ...STAFF_BOOTSTRAP,
      modes: { participant: true, operator: true, default: "operator" },
    });
    expect(screen.getByRole("group", { name: "Mode" })).toBeInTheDocument();
  });

  it("shows the individual and team scoreboard entries in a team-mode event (#2968)", async () => {
    mockCurrentEvent(true);
    renderShell(PARTICIPANT_BOOTSTRAP);
    expect(await screen.findByRole("link", { name: "Individual scoreboard" })).toHaveAttribute(
      "href",
      "/ctf/individual-scoreboard/",
    );
    expect(screen.getByRole("link", { name: "Team scoreboard" })).toHaveAttribute("href", "/ctf/team-scoreboard/");
    expect(screen.queryByRole("link", { name: "Scoreboard" })).not.toBeInTheDocument();
  });

  it("shows the single scoreboard entry in a solo event", async () => {
    mockCurrentEvent(false);
    renderShell(PARTICIPANT_BOOTSTRAP);
    await waitFor(() => expect(vi.mocked(apiFetch)).toHaveBeenCalledWith("/ctf/me/event/", expect.anything()));
    expect(await screen.findByRole("link", { name: "Scoreboard" })).toHaveAttribute("href", "/ctf/scoreboard/");
    expect(screen.queryByRole("link", { name: "Team scoreboard" })).not.toBeInTheDocument();
  });

  it("reads no CTF event in operator mode", () => {
    renderShell();
    expect(vi.mocked(apiFetch)).not.toHaveBeenCalled();
  });

  it("has no axe violations", async () => {
    const { container } = renderShell();
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
