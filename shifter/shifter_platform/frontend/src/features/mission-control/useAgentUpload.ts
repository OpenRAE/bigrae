/** Installer uploads use the shared signed-upload state machine. */
import { useCancelUpload, useCompleteUpload, useInitiateUpload, type UploadInitiateRequest } from "@/api/mission-control";

import { useAssetUpload, type AssetUploadState } from "./useAssetUpload";

export type AgentType = NonNullable<UploadInitiateRequest["agent_type"]>;
export type AgentUploadPhase = AssetUploadState["phase"];
export type AgentUploadState = AssetUploadState;
export interface UseAgentUploadOptions { maxSizeBytes: number | undefined }
export interface StartUploadArgs { name: string; file: File; agentType: AgentType }
export interface UseAgentUploadResult extends AssetUploadState {
  start: (args: StartUploadArgs) => void;
  cancel: () => void;
}

export function useAgentUpload({ maxSizeBytes }: UseAgentUploadOptions): UseAgentUploadResult {
  const initiate = useInitiateUpload();
  const complete = useCompleteUpload();
  const cancel = useCancelUpload();
  return useAssetUpload<StartUploadArgs>({ maxSizeBytes, label: "Agent", services: {
    initiate: ({ name, file, agentType }) => initiate.mutateAsync({
      name, filename: file.name, file_size: file.size, agent_type: agentType,
    }),
    complete: upload_token => complete.mutateAsync({ upload_token }),
    cancel: upload_token => cancel.mutate({ upload_token }),
  } });
}
