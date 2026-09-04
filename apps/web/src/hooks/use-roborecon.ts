import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchApi } from "@/lib/api";
import type {
  AIInvestigation,
  AuditEvent,
  BatchCloseBrief,
  Batch,
  CopilotAnswer,
  ExceptionDetail,
  ExceptionSummary,
  OverviewData,
  ReviewAction,
  ReviewDecision,
  RunDetail,
  RunSummary,
  TransactionRecord,
  PaginatedResponse,
} from "@/types/api";

export const queryKeys = {
  overview: ["overview"] as const,
  batches: ["batches"] as const,
  runs: ["runs"] as const,
  transactions: ["transactions"] as const,
  exceptions: ["exceptions"] as const,
  audit: ["audit"] as const,
};

const invalidateAfterMutation = [
  queryKeys.overview,
  queryKeys.batches,
  queryKeys.runs,
  queryKeys.transactions,
  queryKeys.exceptions,
  queryKeys.audit,
] as const;

async function invalidateOperationalQueries(
  queryClient: ReturnType<typeof useQueryClient>,
) {
  await Promise.all(
    invalidateAfterMutation.map((queryKey) =>
      queryClient.invalidateQueries({ queryKey }),
    ),
  );
}

async function fetchOverview(): Promise<OverviewData> {
  const [batches, runs] = await Promise.all([
    fetchApi<PaginatedResponse<Batch>>("/batches?page=1&page_size=1"),
    fetchApi<PaginatedResponse<RunSummary>>("/reconciliation-runs?page=1&page_size=1"),
  ]);
  const latestBatch = batches.items[0] ?? null;
  const latestRun = latestBatch
    ? runs.items.find((run) => run.batchId === latestBatch.batchId && run.metrics)
    : undefined;

  return {
    metrics: latestRun?.metrics
      ? { ...latestRun.metrics, runId: latestRun.runId }
      : null,
    latestBatch,
  };
}

export function useOverview() {
  return useQuery({
    queryKey: queryKeys.overview,
    queryFn: fetchOverview,
  });
}

export function useResetDemo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => fetchApi<Batch>("/demo/reset", { method: "POST" }),
    onSuccess: async (batch) => {
      queryClient.setQueryData<OverviewData>(queryKeys.overview, {
        metrics: null,
        latestBatch: batch,
      });
      await invalidateOperationalQueries(queryClient);
    },
  });
}

export function useRunReconciliation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (batchId: string) =>
      fetchApi<RunDetail>("/reconciliation-runs", {
        method: "POST",
        body: JSON.stringify({ batchId }),
      }),
    onSuccess: () => invalidateOperationalQueries(queryClient),
  });
}

export function useRuns(page = 1, pageSize = 50) {
  return useQuery({
    queryKey: [...queryKeys.runs, page, pageSize],
    queryFn: () =>
      fetchApi<PaginatedResponse<RunSummary>>(
        `/reconciliation-runs?page=${page}&page_size=${pageSize}`,
      ),
    placeholderData: (previousData) => previousData,
  });
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: [...queryKeys.runs, runId],
    queryFn: () => fetchApi<RunDetail>(`/reconciliation-runs/${runId}`),
    enabled: Boolean(runId),
  });
}

export interface AssessBatchCloseInput {
  runId: string;
  actor?: string;
}

export function useAssessBatchClose() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, actor = "human" }: AssessBatchCloseInput) =>
      fetchApi<BatchCloseBrief>(`/reconciliation-runs/${runId}/close-brief`, {
        method: "POST",
        body: JSON.stringify({ actor }),
      }),
    onSuccess: (brief) => {
      queryClient.setQueryData<RunDetail>([...queryKeys.runs, brief.runId], (current) =>
        current ? { ...current, closeBrief: brief } : current,
      );
    },
  });
}

export function useException(exceptionId: string | undefined) {
  return useQuery({
    queryKey: [...queryKeys.exceptions, exceptionId],
    queryFn: () => fetchApi<ExceptionDetail>(`/exceptions/${exceptionId}`),
    enabled: Boolean(exceptionId),
  });
}

export interface ExceptionFilters {
  page?: number;
  pageSize?: number;
  batchId?: string;
  runId?: string;
  exceptionType?: string;
  status?: string;
}

function exceptionPath(filters: ExceptionFilters): string {
  const params = new URLSearchParams();
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 50));
  if (filters.batchId) params.set("batch_id", filters.batchId);
  if (filters.runId) params.set("run_id", filters.runId);
  if (filters.exceptionType) params.set("type", filters.exceptionType);
  if (filters.status) params.set("status", filters.status);
  return `/exceptions?${params.toString()}`;
}

export function useExceptions(filters: ExceptionFilters = {}) {
  return useQuery({
    queryKey: [...queryKeys.exceptions, filters],
    queryFn: () => fetchApi<PaginatedResponse<ExceptionSummary>>(exceptionPath(filters)),
    placeholderData: (previousData) => previousData,
  });
}

export function useBatches(page = 1, pageSize = 50) {
  return useQuery({
    queryKey: [...queryKeys.batches, page, pageSize],
    queryFn: () =>
      fetchApi<PaginatedResponse<Batch>>(`/batches?page=${page}&page_size=${pageSize}`),
    placeholderData: (previousData) => previousData,
  });
}

export interface ReviewExceptionInput {
  exceptionId: string;
  action: ReviewAction;
  candidateId?: string;
  note?: string;
  actor?: string;
}

export function useReviewException() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ exceptionId, action, candidateId, note, actor = "human" }: ReviewExceptionInput) => {
      const body: Record<string, string> = { action, actor };
      if (candidateId) body.candidateId = candidateId;
      if (note?.trim()) body.note = note.trim();
      return fetchApi<ReviewDecision>(`/exceptions/${exceptionId}/review`, {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => invalidateOperationalQueries(queryClient),
  });
}

export interface InvestigateInput {
  exceptionId: string;
  actor?: string;
}

export function useInvestigate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ exceptionId, actor = "human" }: InvestigateInput) =>
      fetchApi<AIInvestigation>(`/exceptions/${exceptionId}/investigate`, {
        method: "POST",
        body: JSON.stringify({ actor }),
      }),
    onSuccess: () => invalidateOperationalQueries(queryClient),
  });
}

export interface AuditFilters {
  page?: number;
  pageSize?: number;
  batchId?: string;
  runId?: string;
  exceptionId?: string;
  eventType?: string;
}

function auditPath(filters: AuditFilters): string {
  const params = new URLSearchParams();
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 50));
  if (filters.batchId) params.set("batch_id", filters.batchId);
  if (filters.runId) {
    params.set("entity_type", "reconciliation_run");
    params.set("entity_id", filters.runId);
  } else if (filters.exceptionId) {
    params.set("entity_type", "reconciliation_exception");
    params.set("entity_id", filters.exceptionId);
  }
  if (filters.eventType) params.set("event_type", filters.eventType);
  return `/audit-events?${params.toString()}`;
}

export function useAuditEvents(filters: AuditFilters = {}) {
  return useQuery({
    queryKey: [...queryKeys.audit, filters],
    queryFn: () => fetchApi<PaginatedResponse<AuditEvent>>(auditPath(filters)),
    placeholderData: (previousData) => previousData,
  });
}

export interface CopilotInput {
  question: string;
  runId?: string;
  settlementId?: string;
}

export function useCopilot() {
  return useMutation({
    mutationFn: ({ question, runId, settlementId }: CopilotInput) => {
      const body: Record<string, string> = { question };
      if (runId) body.runId = runId;
      if (settlementId) body.settlementId = settlementId;
      return fetchApi<CopilotAnswer>("/copilot/ask", {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
  });
}

export interface TransactionFilters {
  page?: number;
  pageSize?: number;
  batchId?: string;
  sourceType?: string;
  sourceId?: string;
  status?: string;
  reconciliationState?: string;
  enabled?: boolean;
}

function transactionPath(filters: TransactionFilters): string {
  const params = new URLSearchParams();
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 50));
  if (filters.batchId) params.set("batch_id", filters.batchId);
  if (filters.sourceType) params.set("source_type", filters.sourceType);
  if (filters.sourceId) params.set("source_id", filters.sourceId);
  if (filters.status) params.set("status", filters.status);
  if (filters.reconciliationState) {
    params.set("reconciliation_state", filters.reconciliationState);
  }
  return `/transactions?${params.toString()}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function normalizeTransaction(value: unknown): TransactionRecord {
  const row = isRecord(value) ? value : {};
  return {
    sourceType: nullableString(row.sourceType) ?? "unknown",
    sourceId: nullableString(row.sourceId),
    reference: nullableString(row.reference),
    amount: nullableNumber(row.amount),
    currency: nullableString(row.currency),
    status: nullableString(row.status) ?? "unknown",
    businessAt: nullableString(row.businessAt),
    batchId: nullableString(row.batchId) ?? "unknown",
    reconciliationState:
      nullableString(row.reconciliationState) ?? "unreconciled",
    parseError: nullableString(row.parseError),
    runId: nullableString(row.runId),
    resultId: nullableString(row.resultId),
    exceptionId: nullableString(row.exceptionId),
  };
}

function normalizeTransactionPage(value: unknown): PaginatedResponse<TransactionRecord> {
  const payload = isRecord(value) ? value : {};
  const rawItems = Array.isArray(payload.items) ? payload.items : [];
  return {
    items: rawItems.map(normalizeTransaction),
    total: typeof payload.total === "number" ? payload.total : rawItems.length,
    page: typeof payload.page === "number" ? payload.page : 1,
    pageSize: typeof payload.pageSize === "number" ? payload.pageSize : 50,
  };
}

export function useTransactions(filters: TransactionFilters = {}) {
  return useQuery({
    queryKey: [...queryKeys.transactions, filters],
    queryFn: async () =>
      normalizeTransactionPage(await fetchApi<unknown>(transactionPath(filters))),
    placeholderData: (previousData) => previousData,
    enabled: filters.enabled ?? true,
  });
}
