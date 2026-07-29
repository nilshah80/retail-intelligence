import { z } from "zod";

const capabilitySchema = z.object({
  available: z.boolean(),
  reasonCode: z.string().nullish(),
  limitation: z.string().nullish(),
  evidence: z.string().nullish()
}).passthrough();

export const summarySchema = z.object({
  schemaVersion: z.literal("retail-data-management/v1"),
  dataMode: z.literal("live"),
  sourceSnapshotId: z.string().min(1),
  nativeSnapshotId: z.string().nullable().optional(),
  gateAStatus: z.string(),
  gateBStatus: z.string(),
  sourceDatasetCount: z.number().int().nonnegative(),
  canonicalEntityCount: z.number().int().nonnegative(),
  curatedObjectCount: z.number().int().nonnegative(),
  publicationFingerprint: z.string().min(1),
  capabilityMask: z.record(z.string(), capabilitySchema)
});

export const ruleSchema = z.object({
  ruleId: z.string(),
  outcome: z.string(),
  summary: z.string(),
  reasonCode: z.string().optional(),
  affectedCapability: z.string().optional()
}).passthrough();

export const gatesSchema = z.object({
  schemaVersion: z.literal("retail-quality-gates/v1"),
  gateA: z.object({
    status: z.string(),
    rules: z.array(ruleSchema)
  }).passthrough(),
  gateB: z.object({
    status: z.string(),
    rules: z.array(ruleSchema)
  }).passthrough()
});

export const reconciliationSchema = z.array(z.object({
  currencyCode: z.string(),
  difference: z.array(z.number()),
  canonical: z.object({
    grossMinor: z.number(),
    netMinor: z.number(),
    taxMinor: z.number(),
    units: z.number()
  })
}));

export type DataSummary = z.infer<typeof summarySchema>;
export type Gates = z.infer<typeof gatesSchema>;
export type Reconciliation = z.infer<typeof reconciliationSchema>;

async function get<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(path, {headers: {Accept: "application/json"}});
  if (!response.ok) {
    throw new Error(`${path} returned HTTP ${response.status}`);
  }
  return schema.parse(await response.json());
}

export const loadSummary = () =>
  get("/api/v1/data-management/summary", summarySchema);
export const loadGates = () =>
  get("/api/v1/data-management/gates", gatesSchema);
export const loadReconciliation = () =>
  get("/api/v1/data-management/reconciliation", reconciliationSchema);
