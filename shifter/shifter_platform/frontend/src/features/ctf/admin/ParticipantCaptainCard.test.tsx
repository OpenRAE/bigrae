import { beforeEach, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderRoute } from "@/test/utils";
import type { CtfOrganizerParticipantDetail } from "@/api/types";
import { apiFetch } from "@/api/client";
import { ParticipantCaptainCard } from "./ParticipantCaptainCard";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
const mockApi = vi.mocked(apiFetch);
const participant = { id: "p1", event_id: "e1", team_id: "t1", team_captain_id: "p2" } as CtfOrganizerParticipantDetail;
beforeEach(() => { mockApi.mockReset(); });
it("assigns a teammate and displays a safe failure", async () => {
  mockApi.mockImplementation((path) => path.includes("/events/")
    ? Promise.resolve({ access_source: "owner", access_capabilities: ["teams"] })
    : Promise.reject(new Error("unavailable")));
  renderRoute(<ParticipantCaptainCard participant={participant} />);
  await userEvent.click(await screen.findByRole("button", { name: "Make team captain" }));
  expect(mockApi).toHaveBeenCalledWith("/api/v1/ctf/teams/t1/captain/", { method: "POST", body: { participant_id: "p1" } });
  expect(await screen.findByRole("alert")).toBeVisible();
});
it("does not offer team administration to a participant moderator", async () => {
  mockApi.mockResolvedValue({ access_source: "event_staff", access_capabilities: ["participants"] });
  renderRoute(<ParticipantCaptainCard participant={participant} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
