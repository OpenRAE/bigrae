import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/errors";
import { renderRoute, STAFF_BOOTSTRAP } from "@/test/utils";

import { ParticipantControlCard } from "./ParticipantControlCard";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
const mockApi = vi.mocked(apiFetch);
const root = "/participant-control/ctf";
const statePath = `${root}/bindings/binding-1/`;
const state = {
  binding_id: "binding-1", configuration_id: "configuration-1", range_uuid: "range-1",
  episode_id: "episode:run-1", state_revision: 1, history_head: 2,
  control_cut_digest: `sha256:${"a".repeat(64)}`, range_status: "ready", next_before: null,
  commands: [{ id: "approval-1", kind: "approval", verb: "pause", proposal_id: "proposal-1",
    action_id: "action-1", operation_id: "operation-1", operation_state: "succeeded" }],
};

beforeEach(() => { mockApi.mockReset(); });

function route(binding = true) {
  mockApi.mockImplementation(async (url) => {
    if (url === "/bootstrap/") return { ...STAFF_BOOTSTRAP, participant_control_available: true };
    if (url === `${root}/participants/participant-1/binding/`) return {
      configuration_id: "configuration-1", binding_id: binding ? "binding-1" : null, requires_refresh: false,
    };
    if (url === statePath) return state;
    throw new Error(`Unexpected request ${url}`);
  });
}

describe("supervised participant range power", () => {
  it("separates native status from recorded admission and confirms before requesting an effect", async () => {
    route();
    const { container } = renderRoute(<ParticipantControlCard participantId="participant-1" />);
    await screen.findByRole("button", { name: "Request reviewed pause" });
    expect(screen.getByText("Native range status:")).toHaveTextContent("Ready");
    expect(screen.getByText(/Review admission does not confirm/)).toBeInTheDocument();
    expect((await axe(container, { rules: { "color-contrast": { enabled: false } } })).violations).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Request reviewed pause" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("every member of the assigned range");
    expect(mockApi.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
  });

  it("retains an ambiguous original request and its old cut when retrying after a refreshed history", async () => {
    let current = state;
    let posts = 0;
    mockApi.mockImplementation(async (url) => {
      if (url === "/bootstrap/") return { ...STAFF_BOOTSTRAP, participant_control_available: true };
      if (url === `${root}/participants/participant-1/binding/`) return { configuration_id: "configuration-1", binding_id: "binding-1", requires_refresh: false };
      if (url === statePath) return current;
      if (url === `${statePath}commands/`) {
        posts++;
        current = { ...state, control_cut_digest: `sha256:${"b".repeat(64)}` };
        if (posts === 1) throw new ApiError(503, { code: "dependency_unavailable", message: "Service unavailable" });
        return { command_id: "action-1", operation_id: "operation-2", state: "succeeded" };
      }
      throw new Error(`Unexpected request ${url}`);
    });
    renderRoute(<ParticipantControlCard participantId="participant-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Request reviewed pause" }));
    fireEvent.click(screen.getByRole("button", { name: "Submit original request" }));
    await within(screen.getByRole("alertdialog")).findByText("Service unavailable");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Submit original request" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    const requests = mockApi.mock.calls.filter(([url]) => url === `${statePath}commands/`);
    expect(requests).toHaveLength(2);
    expect(requests[0][1]?.body).toEqual(requests[1][1]?.body);
    expect(requests[1][1]?.body).toMatchObject({ request_id: "action-1", expected_cut_digest: state.control_cut_digest });
  });

  it("recovers a retained request by ID without submitting replacement bytes", async () => {
    route();
    const original = mockApi.getMockImplementation()!;
    mockApi.mockImplementation(async (url, options) => url.endsWith("/retry/") ?
      { command_id: "approval-1", operation_id: "operation-1", state: "succeeded" } : original(url, options));
    renderRoute(<ParticipantControlCard participantId="participant-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry original request" }));
    await waitFor(() => expect(mockApi).toHaveBeenCalledWith(`${statePath}commands/approval-1/retry/`, {
      method: "POST", body: {},
    }));
    expect(await screen.findByText("Original request admission: succeeded.")).toBeInTheDocument();
  });

  it("requires confirmation for activation without issuing a power command", async () => {
    route(false);
    renderRoute(<ParticipantControlCard participantId="participant-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Activate supervised power" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("does not pause or resume");
    expect(mockApi.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
  });

  it("does not query an uninstalled controller", async () => {
    mockApi.mockResolvedValue({ ...STAFF_BOOTSTRAP, participant_control_available: false });
    const { container } = renderRoute(<ParticipantControlCard participantId="participant-1" />);
    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1));
    expect(container).toBeEmptyDOMElement();
  });
});
