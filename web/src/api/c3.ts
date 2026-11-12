/** C3 System Database & AI Inference API client (docs/components/C3_DATABASE_AND_AI.md §3). */

import { http, type Page } from "./http";

// --- models (C3-07/08) -----------------------------------------------------------------------

export type ModelStatus = "registered" | "evaluated" | "active" | "retired";
export type FrameRule = "max" | "mean" | "consec2";

export interface ModelSummary {
  model_id: string;
  name: string;
  version: string;
  status: ModelStatus;
  source: string;
  metrics: Record<string, unknown> | null;
  created_at: string;
  activated_at: string | null;
}

export interface LabelMapEntry {
  home_label: string;
  category?: string | null;
  source_classes: string[];
  min_confidence: number;
  rule: FrameRule;
}

export interface LabelMap {
  version?: string | null;
  entries: LabelMapEntry[];
}

export interface PerLabelMetrics {
  precision: number;
  recall: number;
  f1: number;
  support: number;
}

export interface EvaluationMetrics {
  dataset: string;
  accuracy: number;
  macro_f1: number;
  per_label?: Record<string, PerLabelMetrics>;
  labels?: string[];
  confusion?: number[][];
  avg_latency_ms?: number;
  p95_latency_ms?: number;
  n_clips?: number;
  evaluated_at: string;
}

export interface ModelEvaluation {
  evaluation_id: string;
  dataset: string;
  metrics: EvaluationMetrics;
  started_at: string;
  finished_at: string | null;
}

export interface ModelDetail extends ModelSummary {
  label_map: LabelMap;
  notes: string | null;
  evaluations: ModelEvaluation[];
}

export interface CreateModelRequest {
  name?: string;
  version: string;
  base_model_id?: string;
  label_map?: LabelMap;
  notes?: string;
}

export function listModels(): Promise<ModelSummary[]> {
  return http.get<ModelSummary[]>("/api/v1/models");
}

export function getModel(modelId: string): Promise<ModelDetail> {
  return http.get<ModelDetail>(`/api/v1/models/${encodeURIComponent(modelId)}`);
}

export function createModel(body: CreateModelRequest): Promise<ModelDetail> {
  return http.post<ModelDetail>("/api/v1/models", body);
}

export function updateLabelMap(
  modelId: string,
  labelMap: LabelMap,
): Promise<ModelDetail> {
  return http.put<ModelDetail>(
    `/api/v1/models/${encodeURIComponent(modelId)}/label-map`,
    labelMap,
  );
}

export function evaluateModel(modelId: string, dataset = "eval-v1"): Promise<EvaluationMetrics> {
  return http.post<EvaluationMetrics>(`/api/v1/models/${encodeURIComponent(modelId)}/evaluate`, {
    dataset,
  });
}

export function activateModel(modelId: string): Promise<ModelDetail> {
  return http.post<ModelDetail>(`/api/v1/models/${encodeURIComponent(modelId)}/activate`, {
    confirm: true,
  });
}

export function listClasses(): Promise<string[]> {
  return http.get<{ classes: string[] }>("/api/v1/models/classes").then((r) => r.classes);
}

// --- deployment status (C3-08) ---------------------------------------------------------------

export interface WorkerStatus {
  worker_id: string | null;
  hostname: string | null;
  model_id: string | null;
  model_version: string | null;
  last_heartbeat: string | null;
  processed: number;
  failed: number;
  avg_latency_ms: number;
}

export interface DeploymentStatus {
  active_model: Record<string, unknown> | null;
  workers: WorkerStatus[];
  queue: { queued: number; processing: number; failed: number; analyzed_last_hour: number };
  throughput_per_min: number;
  p95_latency_ms: number;
}

export function getDeployment(): Promise<DeploymentStatus> {
  return http.get<DeploymentStatus>("/api/v1/models/deployment");
}

// --- test classify (C3-05) -------------------------------------------------------------------

export interface LabelOut {
  label: string;
  confidence: number;
  source_class: string;
  start_s: number;
  end_s: number;
}

export interface RawScore {
  class_name: string;
  score: number;
}

export interface TestClassifyResult {
  model: { model_id: string; name: string; version: string };
  top_label: string;
  top_confidence: number;
  labels: LabelOut[];
  raw_top10: RawScore[];
  frames: number;
  duration_s: number;
  latency_ms: number;
}

/** Multipart upload of a clip; ``modelId`` picks a version (default: the active model). */
export async function testClassify(file: File, modelId?: string): Promise<TestClassifyResult> {
  const form = new FormData();
  form.append("file", file);
  if (modelId) form.append("model_id", modelId);
  const { getToken } = await import("./http");
  const token = getToken();
  const resp = await fetch("/api/v1/inference/test", {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  const parsed = await resp.json().catch(() => undefined);
  if (!resp.ok || !parsed?.data) {
    const { ApiError } = await import("./http");
    throw new ApiError(
      resp.status,
      parsed?.error?.code ?? "unknown",
      parsed?.error?.message ?? resp.statusText,
      parsed?.error?.details,
    );
  }
  return parsed.data as TestClassifyResult;
}

// --- records + stats (C3-10) -----------------------------------------------------------------

export const RECORD_ENTITIES = [
  "houses",
  "rooms",
  "feeds",
  "clips",
  "detections",
  "alerts",
  "activity_patterns",
] as const;
export type RecordEntity = (typeof RECORD_ENTITIES)[number];

export type Record_ = Record<string, unknown>;

export interface RecordFilters {
  tenantId?: string;
  houseId?: string;
  from?: string;
  to?: string;
  filter?: string; // field:value
  page?: number;
  pageSize?: number;
}

export function recordsQuery(f: RecordFilters): string {
  const q = new URLSearchParams();
  if (f.tenantId) q.set("tenant_id", f.tenantId);
  if (f.houseId) q.set("house_id", f.houseId);
  if (f.from) q.set("from", f.from);
  if (f.to) q.set("to", f.to);
  if (f.filter) q.set("filter", f.filter);
  q.set("page", String(f.page ?? 1));
  q.set("page_size", String(f.pageSize ?? 25));
  return q.toString();
}

export function listRecords(entity: RecordEntity, f: RecordFilters): Promise<Page<Record_>> {
  return http.getPage<Record_>(
    `/api/v1/records/${encodeURIComponent(entity)}?${recordsQuery(f)}`,
  );
}

export interface StatBucket {
  key: string;
  count: number;
}

export function detectionsStats(params: {
  groupBy?: string;
  houseId?: string;
  tenantId?: string;
}): Promise<StatBucket[]> {
  const q = new URLSearchParams();
  if (params.groupBy) q.set("group_by", params.groupBy);
  if (params.houseId) q.set("house_id", params.houseId);
  if (params.tenantId) q.set("tenant_id", params.tenantId);
  return http.get<StatBucket[]>(`/api/v1/detections/stats?${q.toString()}`);
}

// --- data dictionary (C3-13) -----------------------------------------------------------------

export interface DictField {
  name: string;
  type: string;
  nullable: boolean | null;
  internal: boolean;
  description: string | null;
}

export interface DictEntity {
  name: string;
  store: string;
  schema_name: string | null;
  owner_component: string;
  fields: DictField[];
}

export interface DictionaryGrouped {
  version: string;
  generated_at: string;
  components: { component: string; entities: DictEntity[] }[];
}

export interface DictVersion {
  version: string;
  published_by: string;
  published_at: string;
}

export function getDictionary(version?: string): Promise<DictionaryGrouped> {
  const q = version ? `?version=${encodeURIComponent(version)}` : "";
  return http.get<DictionaryGrouped>(`/api/v1/data-dictionary${q}`);
}

export function dictionaryCsvUrl(version?: string): string {
  const q = new URLSearchParams({ format: "csv" });
  if (version) q.set("version", version);
  return `/api/v1/data-dictionary?${q.toString()}`;
}

export function listDictionaryVersions(): Promise<DictVersion[]> {
  return http.get<DictVersion[]>("/api/v1/data-dictionary/versions");
}

export function generateDictionary(version: string): Promise<{ version: string; entities: number }> {
  return http.post<{ version: string; entities: number }>("/api/v1/data-dictionary", {
    version,
    generate: true,
  });
}

// --- integrity (C3-12) -----------------------------------------------------------------------

export type IntegritySeverity = "high" | "medium" | "low";
export type IntegrityStatus = "running" | "done" | "failed";

export interface IntegrityFinding {
  kind: string;
  severity: IntegritySeverity;
  entity_id: string;
  detail: Record<string, unknown>;
}

export interface IntegrityReport {
  report_id: string;
  scope: Record<string, unknown>;
  status: IntegrityStatus;
  findings: IntegrityFinding[];
  started_at: string;
  finished_at: string | null;
}

export function runIntegrityCheck(tenantId?: string): Promise<{ report_id: string; status: string }> {
  const q = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : "";
  return http.post<{ report_id: string; status: string }>(`/api/v1/integrity-checks${q}`);
}

export function getIntegrityReport(reportId: string): Promise<IntegrityReport> {
  return http.get<IntegrityReport>(`/api/v1/integrity-reports/${encodeURIComponent(reportId)}`);
}

export function listIntegrityReports(tenantId?: string): Promise<IntegrityReport[]> {
  const q = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : "";
  return http.get<IntegrityReport[]>(`/api/v1/integrity-reports${q}`);
}

/** Requeue a failed clip (C3-12). */
export function requeueClip(mediaId: string): Promise<{ media_id: string; status: string }> {
  return http.post<{ media_id: string; status: string }>(
    `/api/v1/media-events/${encodeURIComponent(mediaId)}/requeue`,
  );
}

// --- activity patterns (C3-11) ---------------------------------------------------------------

export type ActivityBand = "normal" | "unusual" | "anomalous" | "insufficient_data";

export interface ActivityPattern {
  house_id: string;
  room_id: string | null;
  date: string; // yyyy-mm-dd (UTC)
  hours: number[]; // 24, indexed by UTC hour
  baseline_mean: number[] | null;
  baseline_std: number[] | null;
  anomaly_score: number | null;
  band: ActivityBand;
  last_activity_at: string | null;
}

export function listActivity(params: {
  houseId: string;
  roomId?: string;
  date?: string;
  days?: number;
}): Promise<ActivityPattern[]> {
  const q = new URLSearchParams({ house_id: params.houseId });
  if (params.roomId) q.set("room_id", params.roomId);
  if (params.date) q.set("date", params.date);
  if (params.days) q.set("days", String(params.days));
  return http.get<ActivityPattern[]>(`/api/v1/activity-patterns?${q.toString()}`);
}

// --- query keys ------------------------------------------------------------------------------

export const c3Keys = {
  models: () => ["c3", "models"] as const,
  model: (id: string) => ["c3", "model", id] as const,
  classes: () => ["c3", "classes"] as const,
  deployment: () => ["c3", "deployment"] as const,
  records: (entity: RecordEntity, f: RecordFilters) => ["c3", "records", entity, f] as const,
  stats: (p: Record<string, unknown>) => ["c3", "stats", p] as const,
  dictionary: (version?: string) => ["c3", "dictionary", version ?? "latest"] as const,
  dictionaryVersions: () => ["c3", "dictionary-versions"] as const,
  integrityReports: (tenantId?: string) => ["c3", "integrity-reports", tenantId ?? "all"] as const,
  integrityReport: (id: string) => ["c3", "integrity-report", id] as const,
  activity: (p: Record<string, unknown>) => ["c3", "activity", p] as const,
};
