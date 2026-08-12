// @vitest-environment jsdom

import {afterEach, describe, expect, it, vi} from "vitest";
import {downloadDirectExport} from "./directExport";

afterEach(() => {
  vi.restoreAllMocks();
});

function headers(values: Record<string, string>) {
  return new Headers(values);
}

describe("direct export client", () => {
  it("downloads only the server-authored bytes after matching metadata", async () => {
    const csv = new TextEncoder().encode('"sku_id"\n"sku-1"');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        schemaVersion: "retail-direct-export-metadata/v1",
        exportId: "exportForecastBtn",
        limit: 1000,
        scopeRevision: "scope_0123456789abcdef0123",
        registered: ["exportForecastBtn"]
      }), {status: 200, headers: {"Content-Type": "application/json"}}))
      .mockResolvedValueOnce(new Response(csv, {status: 200, headers: headers({
        "Content-Disposition": 'attachment; filename="demand-forecast-0123456789ab-20260811T120000Z.csv"',
        "X-Export-Count": "1",
        "X-Export-ID": "dx_0123456789abcdef0123",
        "X-Scope-Revision": "scope_0123456789abcdef0123"
      })}));
    vi.stubGlobal("fetch", fetchMock);
    const objectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:export");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    const result = await downloadDirectExport({
      exportId: "exportForecastBtn",
      scope: "selected_visible",
      expectedCount: 1,
      ids: ["forecast_1"],
      currency: "INR",
      filters: {marketId: "india-west", horizonWeeks: 4}
    });

    expect(result).toEqual({
      filename: "demand-forecast-0123456789ab-20260811T120000Z.csv",
      count: 1
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[0][0])).toContain("metadata=true");
    expect(String(fetchMock.mock.calls[1][0])).toContain(
      "scopeRevision=scope_0123456789abcdef0123"
    );
    expect(objectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revoke).toHaveBeenCalledWith("blob:export");
  });

  it("refuses empty and over-limit requests before network access", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(downloadDirectExport({
      exportId: "inventoryExportBtn",
      scope: "current_filtered",
      expectedCount: 0,
      currency: "INR"
    })).rejects.toThrow("No rows are available to export.");
    await expect(downloadDirectExport({
      exportId: "inventoryExportBtn",
      scope: "current_filtered",
      expectedCount: 1001,
      currency: "INR"
    })).rejects.toThrow("Export limit is 1000 rows");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a mismatched attachment lineage", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        schemaVersion: "retail-direct-export-metadata/v1",
        exportId: "inventoryExportBtn",
        limit: 1000,
        scopeRevision: "scope_0123456789abcdef0123",
        registered: ["inventoryExportBtn"]
      }), {status: 200}))
      .mockResolvedValueOnce(new Response("csv", {status: 200, headers: {
        "Content-Disposition": 'attachment; filename="inventory-overview-0123456789ab-20260811T120000Z.csv"',
        "X-Export-Count": "2",
        "X-Export-ID": "dx_0123456789abcdef0123",
        "X-Scope-Revision": "scope_0123456789abcdef0123"
      }})));
    await expect(downloadDirectExport({
      exportId: "inventoryExportBtn",
      scope: "current_filtered",
      expectedCount: 1,
      currency: "INR"
    })).rejects.toThrow("exported row count differs");
  });
});
