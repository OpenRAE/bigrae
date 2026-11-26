import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { axe } from "vitest-axe";

import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/errors";

import { TeamPage } from "./TeamPage";

const mockApi = vi.mocked(apiFetch);

beforeEach(() => {
  mockApi.mockReset();
});

describe("TeamPage", () => {
  it("renders the team and its members", async () => {
    mockApi.mockResolvedValue({
      id: "t1",
      name: "Blue Team",
      members: [
        { id: "m1", name: "Alice", is_captain: true },
        { id: "m2", name: "Bob", is_captain: false },
      ],
      is_captain: false,
      team_size_limit: 4,
      invite_code: null,
    });
    renderRoute(<TeamPage />);
    expect(await screen.findByRole("heading", { name: "Blue Team" })).toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
  });

  it("summarizes the member count", async () => {
    mockApi.mockResolvedValue({ id: "t1", name: "Blue Team", members: [{ id: "m1", name: "Alice" }] });
    renderRoute(<TeamPage />);
    expect(await screen.findByText("1 member")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue({ id: "t1", name: "Blue Team", members: [{ id: "m1", name: "Alice" }] });
    const { container } = renderRoute(<TeamPage />);
    await screen.findByRole("heading", { name: "Blue Team" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("offers create and join forms when not on a team", async () => {
    // The hook resolves the API's 404 to null (see useCtfTeam), so "no team"
    // is ordinary data, not an error state.
    mockApi.mockResolvedValue(null);
    renderRoute(<TeamPage />);
    expect(await screen.findByLabelText("Team name")).toBeInTheDocument();
    expect(screen.getByLabelText("Invite code")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create team" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Join team" })).toBeInTheDocument();
  });

  it("shows captain controls with the invite code to the captain", async () => {
    mockApi.mockResolvedValue({
      id: "t1",
      name: "Blue Team",
      members: [
        { id: "m1", name: "Alice", is_captain: true },
        { id: "m2", name: "Bob", is_captain: false },
      ],
      is_captain: true,
      team_size_limit: 4,
      invite_code: "join-us-123",
    });
    renderRoute(<TeamPage />);
    expect(await screen.findByText("join-us-123")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regenerate" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make captain" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disband team" })).toBeInTheDocument();
  });

  it("hides captain controls and shows leave for members", async () => {
    mockApi.mockResolvedValue({
      id: "t1",
      name: "Blue Team",
      members: [
        { id: "m1", name: "Alice", is_captain: true },
        { id: "m2", name: "Bob", is_captain: false },
      ],
      is_captain: false,
      team_size_limit: null,
      invite_code: null,
    });
    renderRoute(<TeamPage />);
    expect(await screen.findByRole("button", { name: "Leave team" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Regenerate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Make captain" })).not.toBeInTheDocument();
  });

  it("shows invite-code settings and recovery to the captain", async () => {
    mockApi.mockResolvedValue({
      id: "t1",
      name: "Blue Team",
      members: [{ id: "m1", name: "Alice", is_captain: true }],
      is_captain: true,
      team_size_limit: 4,
      invite_code: null,
      invite_code_single_use: false,
      invite_code_expires_at: null,
    });
    renderRoute(<TeamPage />);
    expect(await screen.findByText("No active code. Regenerate to create one.")).toBeInTheDocument();
    expect(screen.getByLabelText("Use mode")).toBeInTheDocument();
    expect(screen.getByLabelText("Expiry")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regenerate" })).toBeInTheDocument();
  });

  it("sends only the edited invite-code settings on regenerate", async () => {
    mockApi.mockResolvedValue({
      id: "t1",
      name: "Blue Team",
      members: [{ id: "m1", name: "Alice", is_captain: true }],
      is_captain: true,
      team_size_limit: 4,
      invite_code: "join-us-123",
      invite_code_single_use: false,
      invite_code_expires_at: null,
    });
    renderRoute(<TeamPage />);
    fireEvent.change(await screen.findByLabelText("Use mode"), { target: { value: "single" } });
    fireEvent.change(screen.getByLabelText("Expiry"), { target: { value: "3600" } });
    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));
    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/ctf/me/team/regenerate-code/",
        expect.objectContaining({ method: "POST", body: { single_use: true, expires_in_seconds: 3600 } }),
      );
    });
  });

  it("omits unedited settings so a routine regenerate keeps restrictions", async () => {
    mockApi.mockResolvedValue({
      id: "t1",
      name: "Blue Team",
      members: [{ id: "m1", name: "Alice", is_captain: true }],
      is_captain: true,
      team_size_limit: 4,
      invite_code: "join-us-123",
      invite_code_single_use: true,
      invite_code_expires_at: "2030-01-01T00:00:00Z",
    });
    renderRoute(<TeamPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Regenerate" }));
    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/ctf/me/team/regenerate-code/",
        expect.objectContaining({ method: "POST", body: {} }),
      );
    });
  });

  it("reports a failed member removal to the captain", async () => {
    const team = {
      id: "t1",
      name: "Blue Team",
      members: [
        { id: "m1", name: "Alice", is_captain: true },
        { id: "m2", name: "Bob", is_captain: false },
      ],
      is_captain: true,
      team_size_limit: 4,
      invite_code: null,
    };
    mockApi.mockImplementation(async (path: string, options?: { method?: string }) => {
      if (options?.method === "POST" && path.endsWith("/remove-member/")) {
        throw new ApiError(409, { code: "conflict", message: "Bob cannot be removed now." });
      }
      return team;
    });
    renderRoute(<TeamPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    expect(await screen.findByText("Bob cannot be removed now.")).toBeInTheDocument();
  });

});
