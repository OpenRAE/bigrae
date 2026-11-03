import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { uploadFileToPresignedUrl } from "./upload";
import { useAssetUpload } from "./useAssetUpload";

vi.mock("./upload", () => ({ uploadFileToPresignedUrl: vi.fn() }));

it("cancels a late admission without affecting a newer upload", async () => {
  let finishOld!: (value: { upload_token: string; presigned_url: string }) => void;
  let finishNew!: () => void;
  const services = {
    initiate: vi.fn().mockReturnValueOnce(new Promise(resolve => { finishOld = resolve; }))
      .mockResolvedValueOnce({ upload_token: "new-token", presigned_url: "new-url" }),
    complete: vi.fn().mockResolvedValue(undefined), cancel: vi.fn(),
  };
  vi.mocked(uploadFileToPresignedUrl).mockReturnValue({
    promise: new Promise<void>(resolve => { finishNew = resolve; }), abort: vi.fn(),
  });
  const { result } = renderHook(() => useAssetUpload({ maxSizeBytes: 1024, label: "File", services }));
  const file = new File(["bytes"], "input.bin");
  act(() => result.current.start({ name: "first", file }));
  act(() => result.current.cancel());
  act(() => result.current.start({ name: "second", file }));
  await waitFor(() => expect(uploadFileToPresignedUrl).toHaveBeenCalledTimes(1));
  await act(async () => finishOld({ upload_token: "old-token", presigned_url: "old-url" }));
  expect(services.cancel).toHaveBeenCalledWith("old-token");
  expect(result.current.phase).toBe("uploading");
  expect(uploadFileToPresignedUrl).toHaveBeenCalledTimes(1);
  await act(async () => finishNew());
  expect(services.complete).toHaveBeenCalledExactlyOnceWith("new-token");
  expect(result.current.phase).toBe("idle");
});
