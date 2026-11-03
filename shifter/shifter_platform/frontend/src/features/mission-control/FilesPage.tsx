import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";

import { describeMutationError } from "@/api/errors";
import { useDeleteFileAsset, useFileAssets, type FileAsset, type FileScope } from "@/api/files";
import { contentScopeKey, useContentScopes } from "@/api/scenarios";
import type { ContentScopeOption } from "@/api/types";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { titleCase } from "@/lib/format";

import { formatTimestamp } from "./format";
import { formatUploadLimit } from "./useAssetUpload";
import { useFileUpload } from "./useFileUpload";

function placement(scope: ContentScopeOption | null): FileScope | null {
  if (!scope?.account || scope.scope_kind !== "account") return null;
  return {
    account_uuid: scope.account,
    ...(scope.organization ? { organization_uuid: scope.organization } : {}),
    ...(scope.workspace ? { workspace_uuid: scope.workspace } : {}),
  };
}

export function FilesPage() {
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<ContentScopeOption | null>(null);
  const [params] = useSearchParams();
  const preferredOrganization = params.get("organization");
  const locations = useContentScopes(offset);
  const available = (locations.data?.results ?? []).filter(row => row.kind !== "installation");
  const initial = preferredOrganization
    ? available.find(row => row.kind === "organization" && row.organization === preferredOrganization) : available[0];
  const scope = locations.isError ? null : selected ?? initial ?? null;
  const choices = scope && !available.some(row => contentScopeKey(row) === contentScopeKey(scope))
    ? [scope, ...available] : available;
  const target = placement(scope);
  function browse(next: number) { setSelected(scope); setOffset(next); }

  return <div className="space-y-6">
    <PageHeader title="Files" description="Upload named files for scenario adapters." />
    <div className="space-y-2">
      <Label htmlFor="file-location">Location</Label>
      <select id="file-location" className="block rounded border bg-background p-2" value={scope ? contentScopeKey(scope) : ""}
        disabled={!choices.length} onChange={event => setSelected(choices.find(row => contentScopeKey(row) === event.target.value) ?? null)}>
        {scope ? null : <option value="">Choose a file location</option>}
        {choices.map(row => <option key={contentScopeKey(row)} value={contentScopeKey(row)}>{titleCase(row.kind)}: {row.name}</option>)}
      </select>
      {offset > 0 || (locations.data?.count ?? 0) > 50 ? <nav aria-label="File location pages" className="flex gap-2">
        <Button variant="outline" disabled={!offset || locations.isFetching} onClick={() => browse(Math.max(0, offset - 50))}>Previous locations</Button>
        <Button variant="outline" disabled={locations.isFetching || offset + 50 >= (locations.data?.count ?? 0)} onClick={() => browse(offset + 50)}>Next locations</Button>
      </nav> : null}
    </div>
    {locations.isError ? <Alert variant="destructive"><AlertTitle>Could not load file locations</AlertTitle>
      <AlertDescription>Please retry.</AlertDescription></Alert> : null}
    {locations.isPending ? <output className="block">Loading file locations…</output> : null}
    {locations.isSuccess && !choices.length ? <p>No file locations are available.</p> : null}
    {target && scope ? <FileAssetsPanel key={contentScopeKey(scope)} scope={target} /> : null}
  </div>;
}

function FileAssetsPanel({ scope }: Readonly<{ scope: FileScope }>) {
  const files = useFileAssets(scope);
  const [replacement, setReplacement] = useState<FileAsset | null>(null);
  const [deleting, setDeleting] = useState<FileAsset | null>(null);
  const remove = useDeleteFileAsset();
  const error = describeMutationError(files.error, "Files could not be loaded.");
  return <div className="space-y-6">
    {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
    <FileUploadForm key={replacement?.id ?? "new"} scope={scope} replacement={replacement}
      maxSize={files.data?.max_file_size_bytes} onFinished={() => setReplacement(null)} />
    <section aria-label="Uploaded files" className="space-y-3">
      <h2 className="text-lg font-semibold">Uploaded files</h2>
      {files.isPending ? <output className="block">Loading files…</output> : null}
      {files.data?.files.length === 0 ? <p>No files uploaded yet.</p> : null}
      {files.data?.files.length ? <Table><TableHeader><TableRow>
        <TableHead>Name</TableHead><TableHead>Filename</TableHead><TableHead>Size</TableHead>
        <TableHead>Uploaded</TableHead><TableHead>Actions</TableHead>
      </TableRow></TableHeader><TableBody>{files.data.files.map(file => <TableRow key={file.id}>
        <TableCell>{file.name}</TableCell><TableCell>{file.original_filename}</TableCell>
        <TableCell>{formatUploadLimit(file.file_size_bytes)}</TableCell><TableCell>{formatTimestamp(file.created_at)}</TableCell>
        <TableCell className="space-x-2">
          <Button variant="outline" onClick={() => setReplacement(file)}>Replace {file.name}</Button>
          <Button variant="outline" onClick={() => { remove.reset(); setDeleting(file); }}>Delete {file.name}</Button>
        </TableCell>
      </TableRow>)}</TableBody></Table> : null}
    </section>
    <ConfirmDialog open={deleting !== null} onOpenChange={open => { if (!open && !remove.isPending) setDeleting(null); }}
      title="Delete this file?" confirmLabel="Delete file" destructive pending={remove.isPending} error={remove.error}
      onConfirm={() => { if (deleting) remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) }); }}>
      New launches will no longer have access to this file. Existing ranges keep their original version until they are destroyed.
    </ConfirmDialog>
  </div>;
}

function FileUploadForm({ scope, replacement, maxSize, onFinished }: Readonly<{
  scope: FileScope; replacement: FileAsset | null; maxSize: number | undefined; onFinished: () => void;
}>) {
  const upload = useFileUpload(scope, maxSize);
  const [name, setName] = useState(replacement?.name ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const previous = useRef(upload.phase);
  const pending = upload.phase === "uploading";
  useEffect(() => {
    if (previous.current === "uploading" && upload.phase === "idle") {
      setName(""); setFile(null); setInputKey(value => value + 1); onFinished();
    }
    previous.current = upload.phase;
  }, [upload.phase, onFinished]);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (file) upload.start({ name, file, ...(replacement ? { replaces: replacement.id } : {}) });
  }
  return <section className="space-y-3 rounded border p-4" aria-label="File upload">
    <h2 className="text-lg font-semibold">{replacement ? `Replace ${replacement.name}` : "Upload file"}</h2>
    <p>New launches use replacements. Existing ranges keep their original file version.</p>
    <form onSubmit={submit} className="space-y-3">
      <Label htmlFor="file-asset-name">File name</Label>
      <Input id="file-asset-name" value={name} maxLength={100} disabled={pending || replacement !== null}
        onChange={event => setName(event.target.value)} />
      <Label htmlFor="file-asset-content">File</Label>
      <Input key={inputKey} id="file-asset-content" type="file" disabled={pending}
        onChange={event => setFile(event.target.files?.[0] ?? null)} />
      <p className="text-sm text-muted-foreground">{maxSize === undefined ? "Loading upload limit…" : `Max ${formatUploadLimit(maxSize)} per file.`}</p>
      {pending ? <div aria-live="polite" className="space-y-2"><Progress value={upload.progress} />
        <span>{upload.statusText}</span><Button type="button" variant="outline" onClick={upload.cancel}>Cancel upload</Button></div> : null}
      {upload.error ? <Alert variant="destructive"><AlertDescription>{upload.error}</AlertDescription></Alert> : null}
      <Button disabled={pending || !file || !name.trim() || maxSize === undefined} type="submit">
        {replacement ? "Replace file" : "Upload file"}
      </Button>
    </form>
  </section>;
}
