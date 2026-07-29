import { describe, expect, it } from "vitest";
import { summarySchema } from "./api";

describe("data-management contract", () => {
  it("accepts a live governed summary", () => {
    const parsed = summarySchema.parse({
      schemaVersion: "retail-data-management/v1",
      dataMode: "live",
      sourceSnapshotId: "snapshot-a",
      nativeSnapshotId: "run-a",
      gateAStatus: "pass",
      gateBStatus: "pass",
      sourceDatasetCount: 132,
      canonicalEntityCount: 40,
      curatedObjectCount: 1330,
      publicationFingerprint: "fingerprint",
      capabilityMask: {
        data_management: {available: true}
      }
    });
    expect(parsed.dataMode).toBe("live");
  });

  it("rejects an unlabelled stub response", () => {
    expect(() => summarySchema.parse({
      schemaVersion: "retail-data-management/v1",
      dataMode: "stub"
    })).toThrow();
  });
});
