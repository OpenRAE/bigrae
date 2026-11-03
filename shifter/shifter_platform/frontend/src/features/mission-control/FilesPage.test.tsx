import { beforeEach, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";

import { renderRoute, setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("./upload", () => ({ uploadFileToPresignedUrl: vi.fn() }));

import { apiFetch } from "@/api/client";
import { uploadFileToPresignedUrl } from "./upload";
import { FilesPage } from "./FilesPage";

const api = vi.mocked(apiFetch);
const put = vi.mocked(uploadFileToPresignedUrl);
const location = { kind: "account", name: "Personal", scope_kind: "account", account: "account-one", organization: null, workspace: null };
const file = { id: 1, uuid: "file-one", name: "Parameters", original_filename: "input.json", file_size_bytes: 4, created_at: "2026-11-02T10:00:00Z" };

beforeEach(() => { api.mockReset(); put.mockReset(); });

function files() {
  api.mockImplementation(path => {
    if (path === "/cms/content-scopes/") return Promise.resolve({ count: 1, results: [location] });
    if (path === "/mission-control/files/") return Promise.resolve({ files: [file], max_file_size_bytes: 512 * 1024 });
    if (path === "/mission-control/files/upload/initiate/") return Promise.resolve({
      presigned_url: "https://storage.example.test/put", upload_token: "file-token", s3_key: "private/object", expected_os: "",
    });
    if (path === "/mission-control/files/upload/complete/") return Promise.resolve({ success: true, file_id: 2, message: "File uploaded" });
    if (path === "/mission-control/files/1/") return Promise.resolve({ success: true });
    return Promise.reject(new Error("Unexpected API path"));
  });
}

it("lists file metadata in an authorized location without rendering storage or content", async () => {
  files();
  renderRoute(<FilesPage />);
  expect(await screen.findByText("input.json")).toBeInTheDocument();
  expect(screen.getByText(/512 KB/)).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/mission-control/files/", expect.objectContaining({ query: { account_uuid: "account-one" } }));
  expect(screen.queryByText("private/object")).not.toBeInTheDocument();
});

it("uploads opaque files through the existing signed PUT flow", async () => {
  files();
  put.mockReturnValue({ promise: Promise.resolve(), abort: vi.fn() });
  const user = setupUser();
  renderRoute(<FilesPage />);
  await screen.findByText("input.json");
  await user.type(screen.getByLabelText("File name"), "New parameters");
  const chosen = new File(["opaque data"], "parameters.bin");
  await user.upload(screen.getByLabelText("File"), chosen);
  await user.click(screen.getByRole("button", { name: "Upload file" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/mission-control/files/upload/complete/", expect.objectContaining({ body: { upload_token: "file-token" } })));
  expect(api).toHaveBeenCalledWith("/mission-control/files/upload/initiate/", { method: "POST", body: {
    name: "New parameters", filename: "parameters.bin", file_size: chosen.size, account_uuid: "account-one",
  } });
  expect(put).toHaveBeenCalledWith("https://storage.example.test/put", chosen, expect.any(Function));
});

it("replaces the selected exact version while retaining its name", async () => {
  files();
  put.mockReturnValue({ promise: Promise.resolve(), abort: vi.fn() });
  const user = setupUser();
  renderRoute(<FilesPage />);
  await user.click(await screen.findByRole("button", { name: "Replace Parameters" }));
  expect(screen.getByLabelText("File name")).toHaveValue("Parameters");
  await user.upload(screen.getByLabelText("File"), new File(["new"], "new.json"));
  await user.click(screen.getByRole("button", { name: "Replace file" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/mission-control/files/upload/initiate/", expect.objectContaining({ body: {
    name: "Parameters", filename: "new.json", file_size: 3, replaces: 1, account_uuid: "account-one",
  } })));
});

it("confirms retirement and explains the effect on existing ranges", async () => {
  files();
  const user = setupUser();
  renderRoute(<FilesPage />);
  await user.click(await screen.findByRole("button", { name: "Delete Parameters" }));
  const dialog = screen.getByRole("alertdialog");
  expect(within(dialog).getByText(/Existing ranges keep/)).toBeInTheDocument();
  await user.click(within(dialog).getByRole("button", { name: "Delete file" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/mission-control/files/1/", { method: "DELETE" }));
});

it("never falls back to a file scope when discovery is unavailable", async () => {
  api.mockRejectedValue(new Error("Unavailable"));
  renderRoute(<FilesPage />);
  expect(await screen.findByText("Could not load file locations")).toBeInTheDocument();
  expect(api.mock.calls.every(([path]) => path === "/cms/content-scopes/")).toBe(true);
});

it("does not offer installation catalog publication as a file location", async () => {
  api.mockResolvedValue({ count: 1, results: [{ ...location, kind: "installation", scope_kind: "installation" }] });
  renderRoute(<FilesPage />);
  expect(await screen.findByText("No file locations are available.")).toBeInTheDocument();
  expect(api.mock.calls.every(([path]) => path === "/cms/content-scopes/")).toBe(true);
});
