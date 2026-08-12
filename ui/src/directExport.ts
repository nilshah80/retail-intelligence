import {z} from "zod";

export const DIRECT_EXPORT_LIMIT = 1_000;

const directExportMetadataSchema = z.object({
  schemaVersion: z.literal("retail-direct-export-metadata/v1"),
  exportId: z.string(),
  limit: z.number().int().positive(),
  scopeRevision: z.string().min(1),
  registered: z.array(z.string())
}).strict();

const directExportErrorSchema = z.object({
  message: z.string().optional(),
  reasonCode: z.string().optional()
}).passthrough();

export type DirectExportScope = "selected_visible" | "current_filtered";

export interface DirectExportRequest {
  exportId: string;
  scope: DirectExportScope;
  expectedCount: number;
  ids?: readonly string[];
  currency: string;
  storeId?: string;
  channelType?: string;
  filters?: Readonly<Record<string, string | number | undefined>>;
}

function requestParams(request: DirectExportRequest) {
  const params = new URLSearchParams({
    scope: request.scope,
    expectedCount: String(request.expectedCount),
    currency: request.currency
  });
  if (request.storeId) params.set("storeId", request.storeId);
  if (request.channelType) params.set("channelType", request.channelType);
  if (request.ids?.length) params.set("ids", request.ids.join(","));
  for (const [key, value] of Object.entries(request.filters ?? {})) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return params;
}

async function responseMessage(response: Response) {
  const payload = await response.json().catch(() => null);
  const parsed = directExportErrorSchema.safeParse(payload);
  return parsed.success && parsed.data.message
    ? parsed.data.message
    : `Export request returned HTTP ${response.status}.`;
}

function attachmentFilename(response: Response) {
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/^attachment; filename="([A-Za-z0-9_.-]+\.csv)"$/);
  if (!match) throw new Error("The export response did not provide a safe CSV filename.");
  return match[1];
}

/**
 * Downloads the bytes authored by the server without parsing or regenerating the
 * CSV in the browser. Metadata and download use the same normalized scope so a
 * changed authority or filter population is refused rather than silently exported.
 */
export async function downloadDirectExport(request: DirectExportRequest) {
  if (!Number.isInteger(request.expectedCount) || request.expectedCount < 1) {
    throw new Error("No rows are available to export.");
  }
  if (request.expectedCount > DIRECT_EXPORT_LIMIT) {
    throw new Error(
      `Export limit is ${DIRECT_EXPORT_LIMIT} rows; narrow filters or selection.`
    );
  }

  const base = `/api/v1/direct-exports/${encodeURIComponent(request.exportId)}`;
  const metadataParams = requestParams(request);
  metadataParams.set("metadata", "true");
  const metadataResponse = await fetch(`${base}?${metadataParams}`, {
    headers: {Accept: "application/json"},
    cache: "no-store"
  });
  if (!metadataResponse.ok) throw new Error(await responseMessage(metadataResponse));
  const metadata = directExportMetadataSchema.parse(await metadataResponse.json());
  if (metadata.exportId !== request.exportId ||
      !metadata.registered.includes(request.exportId)) {
    throw new Error("The server did not confirm this direct-export trigger.");
  }
  if (request.expectedCount > metadata.limit) {
    throw new Error(
      `Export limit is ${metadata.limit} rows; narrow filters or selection.`
    );
  }

  const downloadParams = requestParams(request);
  downloadParams.set("scopeRevision", metadata.scopeRevision);
  const response = await fetch(`${base}?${downloadParams}`, {
    headers: {Accept: "text/csv"},
    cache: "no-store"
  });
  if (!response.ok) throw new Error(await responseMessage(response));
  if (response.headers.get("X-Export-Count") !== String(request.expectedCount)) {
    throw new Error("The exported row count differs from the reviewed count.");
  }
  if (!response.headers.get("X-Export-ID") ||
      response.headers.get("X-Scope-Revision") !== metadata.scopeRevision) {
    throw new Error("The export response lineage is incomplete or stale.");
  }
  const filename = attachmentFilename(response);
  const bytes = await response.arrayBuffer();
  const url = URL.createObjectURL(new Blob([bytes], {type: "text/csv;charset=utf-8"}));
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
  } finally {
    URL.revokeObjectURL(url);
  }
  return {filename, count: request.expectedCount};
}
