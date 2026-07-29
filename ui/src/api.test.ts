import { describe, expect, it } from "vitest";
import {dashboardSchema, fxSchema, summarySchema} from "./api";

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

  it("accepts only live original-screen data points", () => {
    const parsed = dashboardSchema.parse({
      schemaVersion: "retail-data-management-dashboard/v1",
      dataMode: "live",
      kpis: {
        dataFreshnessPct: 100,
        qualityScorePct: 100,
        connectedSources: 3,
        rejectedRecords: 0,
        lastRefreshAt: "2026-07-30T00:00:00Z"
      },
      sources: [{
        sourceSystem: "shopify",
        name: "Shopify Commerce",
        type: "Commerce / Parquet",
        lastRefreshAt: "2026-07-30T00:00:00Z",
        records: 173637309,
        qualityPct: 100,
        status: "Healthy",
        action: "View mapping",
        datasetCount: 22,
        objectCount: 2318
      }],
      footer: {
        totalSkus: 720,
        activeSkus: 348,
        stores: 4,
        channels: 2,
        forecastCoveragePct: null,
        modelAccuracyPct: null
      },
      filters: {
        dateRange: {start: "2016-07-28", end: "2026-07-28"},
        markets: [
          {marketId: "india-west", name: "India West"},
          {marketId: "us-new-york", name: "US New York"}
        ],
        stores: [],
        channelTypes: [
          {
            type: "online",
            name: "E-commerce",
            marketIds: ["india-west", "us-new-york"]
          },
          {
            type: "store",
            name: "Store",
            marketIds: ["india-west", "us-new-york"]
          }
        ],
        currencies: ["INR", "USD"]
      }
    });
    expect(parsed.footer.forecastCoveragePct).toBeNull();
    expect(parsed.kpis.qualityScorePct).toBe(100);
  });

  it("accepts exact live FX rates as decimal strings", () => {
    const parsed = fxSchema.parse({
      schemaVersion: "retail-fx-rates/v1",
      dataMode: "live",
      reportingCurrency: "INR",
      coverage: {
        start: "2016-07-28",
        end: "2026-07-28",
        observations: 7306
      },
      rates: [
        {
          baseCurrency: "INR",
          quoteCurrency: "INR",
          rate: "1.000000000000000000",
          rateDate: "2026-07-28"
        },
        {
          baseCurrency: "USD",
          quoteCurrency: "INR",
          rate: "83.000000000000000000",
          rateDate: "2026-07-28"
        }
      ]
    });
    expect(parsed.rates[1].rate).toBe("83.000000000000000000");
  });
});
