import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { components } from "./schema";

export type FileAsset = components["schemas"]["FileAsset"];
export type FileAssetList = components["schemas"]["FileAssetList"];
export type FileUploadRequest = components["schemas"]["FileUploadInitiate"];
export type FileScope = Pick<FileUploadRequest, "account_uuid" | "organization_uuid" | "workspace_uuid">;

const FILES = "/mission-control/files/";
const key = ["file-assets"] as const;

export function useFileAssets(scope: FileScope | null) {
  return useQuery({
    queryKey: [...key, scope?.account_uuid ?? "", scope?.organization_uuid ?? "", scope?.workspace_uuid ?? ""],
    enabled: scope !== null,
    queryFn: ({ signal }) => apiFetch<FileAssetList>(FILES, { signal, query: scope ?? undefined }),
  });
}

export function useInitiateFileUpload() {
  return useMutation({
    mutationFn: (body: FileUploadRequest) => apiFetch<components["schemas"]["UploadInitiateResponse"]>(
      `${FILES}upload/initiate/`, { method: "POST", body },
    ),
  });
}

export function useCompleteFileUpload() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (upload_token: string) => apiFetch<components["schemas"]["FileUploadComplete"]>(
      `${FILES}upload/complete/`, { method: "POST", body: { upload_token } },
    ),
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  });
}

export function useCancelFileUpload() {
  return useMutation({
    mutationFn: (upload_token: string) => apiFetch<components["schemas"]["SuccessResponse"]>(
      `${FILES}upload/cancel/`, { method: "POST", body: { upload_token } },
    ),
  });
}

export function useDeleteFileAsset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (identifier: number) => apiFetch<components["schemas"]["SuccessResponse"]>(
      `${FILES}${identifier}/`, { method: "DELETE" },
    ),
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  });
}
