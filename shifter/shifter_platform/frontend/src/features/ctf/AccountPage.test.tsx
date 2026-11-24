import { beforeEach, describe, expect, it, vi } from "vitest";
import { focusManager, onlineManager } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { axe } from "vitest-axe";

import { createQueryClient } from "@/api/queryClient";
import { renderRoute, testQueryClient } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { AccountPage } from "./AccountPage";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => {
  mockApi.mockReset();
  // Focus and network state are module singletons; a failed test must not leak them.
  onlineManager.setOnline(true);
  focusManager.setFocused(undefined);
});

const PROFILE = {
  id: "p1",
  name: "Self Player",
  affiliation: "EMEA",
  time_zone: "",
  email: "self@test.com",
  username: null,
  role: "player",
  status: "active",
  event: { id: "e1", name: "Spring CTF" },
  score: 250,
  solve_count: 3,
};

const NO_SUBMISSIONS = { submissions: [], total: 0 };

function submission(overrides: Record<string, unknown>) {
  return {
    id: "s1",
    challenge_id: "c1",
    challenge_name: "Web 101",
    is_correct: true,
    points_awarded: 100,
    attempt_number: 1,
    submitted_at: "2026-11-01T10:00:00Z",
    submitted_flag: "FLAG{web}",
    ...overrides,
  };
}

/** Route the mocked reads by path: the profile endpoint and the submission history. */
function mockReads(profile: object, history: object = NO_SUBMISSIONS) {
  mockApi.mockImplementation((path: string) =>
    Promise.resolve(path.includes("/submissions/") ? history : profile),
  );
}

describe("AccountPage", () => {
  it("renders profile form with current values", async () => {
    mockReads(PROFILE);
    renderRoute(<AccountPage />);
    expect(await screen.findByLabelText("Display name")).toHaveValue(
      "Self Player",
    );
    expect(screen.getByLabelText("Affiliation")).toHaveValue("EMEA");
    expect(screen.getByText(/Spring CTF/)).toBeInTheDocument();
    // Linked platform account: no self-service username section.
    expect(screen.queryByLabelText("Username")).not.toBeInTheDocument();
  });

  it("shows the time zone and saves the browser time zone (#582)", async () => {
    vi.spyOn(Intl, "DateTimeFormat").mockImplementation(
      () =>
        ({
          resolvedOptions: () => ({ timeZone: "Europe/Paris" }),
        }) as Intl.DateTimeFormat,
    );
    mockReads(PROFILE);
    renderRoute(<AccountPage />);
    const zone = await screen.findByLabelText("Time zone");
    expect(zone).toHaveValue("");
    expect(
      screen.getByText(/blank uses the event time zone/i),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Use Europe/Paris" }));
    expect(zone).toHaveValue("Europe/Paris");
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        expect.stringContaining("/me/profile/"),
        expect.objectContaining({
          method: "PATCH",
          body: {
            name: "Self Player",
            affiliation: "EMEA",
            time_zone: "Europe/Paris",
          },
        }),
      ),
    );
    vi.restoreAllMocks();
  });

  it("shows the username form for isolated accounts", async () => {
    mockReads({ ...PROFILE, username: "range-abc123" });
    renderRoute(<AccountPage />);
    expect(await screen.findByLabelText("Username")).toHaveValue(
      "range-abc123",
    );
    expect(
      screen.getByRole("button", { name: "Change username" }),
    ).toBeInTheDocument();
  });

  it("labels observers", async () => {
    mockReads({ ...PROFILE, role: "observer" });
    renderRoute(<AccountPage />);
    expect(
      await screen.findByText(/Observer — you can watch/),
    ).toBeInTheDocument();
  });

  it("lists each correct flag with its challenge and hides incorrect attempts (#3002)", async () => {
    mockReads(PROFILE, {
      submissions: [
        submission({
          id: "s3",
          challenge_id: "c2",
          challenge_name: "Crypto 1",
          submitted_flag: "<b>x</b>",
        }),
        submission({
          id: "s2",
          is_correct: false,
          points_awarded: 0,
          submitted_flag: null,
        }),
        submission({ id: "s1" }),
      ],
      total: 3,
    });
    renderRoute(<AccountPage />);

    await screen.findByRole("link", { name: "Crypto 1" });
    const section = screen.getByRole("region", { name: "Correct flags" });
    const rows = within(section).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(
      within(rows[0]).getByRole("link", { name: "Crypto 1" }),
    ).toHaveAttribute("href", "/ctf/challenges/c2/");
    // A markup-like value renders as literal text, never as HTML.
    expect(within(rows[0]).getByText("<b>x</b>")).toBeInTheDocument();
    expect(
      within(rows[1]).getByRole("link", { name: "Web 101" }),
    ).toHaveAttribute("href", "/ctf/challenges/c1/");
    expect(within(rows[1]).getByText("FLAG{web}")).toBeInTheDocument();
    expect(mockApi).toHaveBeenCalledWith(
      expect.stringContaining("/submissions/"),
      expect.anything(),
    );
  });

  it("never renders a retained flag from an earlier visit (#3002)", async () => {
    const queryClient = testQueryClient();
    mockReads(PROFILE, {
      submissions: [submission({ submitted_flag: "FLAG{first-account}" })],
      total: 1,
    });
    const first = renderRoute(<AccountPage />, { queryClient });
    await screen.findByText("FLAG{first-account}");
    first.unmount();
    // Leaving the page lets the zero garbage-collection timer drop the cached history.
    await new Promise((resolve) => setTimeout(resolve, 0));

    // Another account's session answers the next read; hold it to observe the pending render.
    let answer: (value: unknown) => void = () => undefined;
    mockApi.mockImplementation((path: string) =>
      path.includes("/submissions/")
        ? new Promise((resolve) => (answer = resolve))
        : Promise.resolve(PROFILE),
    );
    renderRoute(<AccountPage />, { queryClient });
    await screen.findByLabelText("Display name");
    expect(screen.queryByText("FLAG{first-account}")).not.toBeInTheDocument();

    answer({
      submissions: [submission({ submitted_flag: "FLAG{second-account}" })],
      total: 1,
    });
    expect(await screen.findByText("FLAG{second-account}")).toBeInTheDocument();
    expect(screen.queryByText("FLAG{first-account}")).not.toBeInTheDocument();
  });

  it("withholds earlier flags when the tab returns after a session change (#3002)", async () => {
    mockReads(PROFILE, {
      submissions: [submission({ submitted_flag: "FLAG{first-session}" })],
      total: 1,
    });
    // The app query client disables focus refetch by default.
    renderRoute(<AccountPage />, { queryClient: createQueryClient() });
    await screen.findByText("FLAG{first-session}");

    // Another tab changed the session; the next read answers for the new session.
    let answer: (value: unknown) => void = () => undefined;
    mockApi.mockImplementation((path: string) =>
      path.includes("/submissions/")
        ? new Promise((resolve) => (answer = resolve))
        : Promise.resolve(PROFILE),
    );
    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    await waitFor(() =>
      expect(screen.queryByText("FLAG{first-session}")).not.toBeInTheDocument(),
    );

    answer({
      submissions: [submission({ submitted_flag: "FLAG{second-session}" })],
      total: 1,
    });
    expect(await screen.findByText("FLAG{second-session}")).toBeInTheDocument();
    focusManager.setFocused(undefined);
  });

  it("withholds earlier flags while an offline revalidation is paused (#3002)", async () => {
    mockReads(PROFILE, {
      submissions: [submission({ submitted_flag: "FLAG{first-session}" })],
      total: 1,
    });
    renderRoute(<AccountPage />, { queryClient: createQueryClient() });
    await screen.findByText("FLAG{first-session}");

    mockReads(PROFILE, {
      submissions: [submission({ submitted_flag: "FLAG{second-session}" })],
      total: 1,
    });
    act(() => {
      onlineManager.setOnline(false);
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    await waitFor(() =>
      expect(screen.queryByText("FLAG{first-session}")).not.toBeInTheDocument(),
    );

    act(() => onlineManager.setOnline(true));
    expect(await screen.findByText("FLAG{second-session}")).toBeInTheDocument();
    focusManager.setFocused(undefined);
  });

  it("shows an empty state before any correct flag", async () => {
    mockReads(PROFILE, {
      submissions: [
        submission({
          id: "s2",
          is_correct: false,
          points_awarded: 0,
          submitted_flag: null,
        }),
        // A correct row on a deleted challenge carries no value.
        submission({ id: "s1", submitted_flag: null }),
      ],
      total: 2,
    });
    renderRoute(<AccountPage />);
    expect(
      await screen.findByText("No correct flags yet."),
    ).toBeInTheDocument();
  });

  it("keeps the profile usable when the flag history fails", async () => {
    mockApi.mockImplementation((path: string) =>
      path.includes("/submissions/")
        ? Promise.reject(new Error("boom"))
        : Promise.resolve(PROFILE),
    );
    renderRoute(<AccountPage />);
    expect(
      await screen.findByText("Could not load your correct flags"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Display name")).toHaveValue("Self Player");
  });

  it("has no axe violations", async () => {
    mockReads(
      { ...PROFILE, username: "range-abc123" },
      { submissions: [submission({})], total: 1 },
    );
    const { container } = renderRoute(<AccountPage />);
    await screen.findByLabelText("Username");
    await screen.findByText("FLAG{web}");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
