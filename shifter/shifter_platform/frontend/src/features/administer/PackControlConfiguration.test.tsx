import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/errors";
import { renderRoute, STAFF_BOOTSTRAP } from "@/test/utils";

import { PackControlConfiguration } from "./PackControlConfiguration";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
const mockApi = vi.mocked(apiFetch);
const digest = `sha256:${"a".repeat(64)}`;
const path = "/participant-control/organizations/org-1/sources/example/";
const values = {
  participant_address: "participant.behavior.analyst", controller_address: "participant.behavior.controller",
  pause_action_contract_address: "participant.action-contract.pause",
  resume_action_contract_address: "participant.action-contract.resume",
  observation_boundary_address: "participant.observation-boundary.references",
};

beforeEach(() => { mockApi.mockReset(); });

function fields() {
  const labels = ["Participant address", "Controller address", "Pause action address", "Resume action address", "Observation boundary address"];
  labels.forEach((label, index) => fireEvent.change(screen.getByLabelText(label), { target: { value: Object.values(values)[index] } }));
}

describe("pack control configuration", () => {
  it("checks logical references for the displayed version without installing code or activating a range", async () => {
    let configuration = null as Record<string, unknown> | null;
    mockApi.mockImplementation(async (url, options) => {
      if (url === "/bootstrap/") return { ...STAFF_BOOTSTRAP, participant_control_available: true };
      if (url !== path) throw new Error(`Unexpected request ${url}`);
      if (options?.method === "POST") {
        configuration = { id: "configuration-1", selection: values };
        return configuration;
      }
      return { configuration, requires_refresh: false };
    });
    const { container } = renderRoute(<PackControlConfiguration organization="org-1" source="example" digest={digest} />);
    await screen.findByLabelText("Participant address");
    expect(screen.getByRole("button", { name: "Review control configuration" })).toBeDisabled();
    fields();
    expect((await axe(container, { rules: { "color-contrast": { enabled: false } } })).violations).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Review control configuration" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Range activation and every power operation");
    expect(mockApi.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Save mapping" }));
    await waitFor(() => expect(mockApi).toHaveBeenCalledWith(path, {
      method: "POST", body: { expected_package_digest: digest, selection: values },
    }));
    expect(await screen.findByText(/Control mapping saved/)).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("retains a rejected mapping and its displayed digest without rebasing or claiming success", async () => {
    mockApi.mockImplementation(async (url, options) => {
      if (url === "/bootstrap/") return { ...STAFF_BOOTSTRAP, participant_control_available: true };
      if (options?.method === "POST") throw new ApiError(409, { code: "conflict", message: "The source changed. Reload its current revision." });
      return { configuration: null, requires_refresh: true };
    });
    renderRoute(<PackControlConfiguration organization="org-1" source="example" digest={digest} />);
    await screen.findByLabelText("Participant address");
    fields();
    fireEvent.click(screen.getByRole("button", { name: "Review control configuration" }));
    fireEvent.click(screen.getByRole("button", { name: "Save mapping" }));
    expect(await screen.findByText("The source changed. Reload its current revision.")).toBeInTheDocument();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Participant address")).toHaveValue(values.participant_address);
    expect(screen.queryByText(/Control mapping saved/)).not.toBeInTheDocument();
    expect(mockApi.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
  });

  it("does not query an uninstalled service", async () => {
    mockApi.mockResolvedValue({ ...STAFF_BOOTSTRAP, participant_control_available: false });
    const { container } = renderRoute(<PackControlConfiguration organization="org-1" source="example" digest={digest} />);
    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1));
    expect(mockApi.mock.calls[0][0]).toBe("/bootstrap/");
    expect(container).toBeEmptyDOMElement();
  });
});
