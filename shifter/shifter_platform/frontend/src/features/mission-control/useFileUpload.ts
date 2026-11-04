import { useCancelFileUpload, useCompleteFileUpload, useInitiateFileUpload, type FileScope } from "@/api/files";

import { useAssetUpload, type AssetUploadArgs } from "./useAssetUpload";

interface FileUploadArgs extends AssetUploadArgs { replaces?: number }

export function useFileUpload(scope: FileScope, maxSizeBytes: number | undefined) {
  const initiate = useInitiateFileUpload();
  const complete = useCompleteFileUpload();
  const cancel = useCancelFileUpload();
  return useAssetUpload<FileUploadArgs>({ maxSizeBytes, label: "File", services: {
    initiate: ({ name, file, replaces }) => initiate.mutateAsync({
      ...scope, name, filename: file.name, file_size: file.size, ...(replaces ? { replaces } : {}),
    }),
    complete: complete.mutateAsync,
    cancel: token => cancel.mutate(token),
  } });
}
