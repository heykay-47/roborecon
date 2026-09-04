export type BatchKind = "demo" | "test_mode_sync";
export type BatchStatus = "pending" | "running" | "completed" | "failed";
export type RunStatus = "running" | "completed" | "failed";
export type ReconciliationStage =
  | "ledger_to_razorpay"
  | "razorpay_to_settlement";
export type ResultStatus =
  | "matched"
  | "ambiguous"
  | "duplicate"
  | "missing_razorpay"
  | "missing_ledger"
  | "missing_settlement"
  | "missing_bank_credit"
  | "amount_mismatch"
  | "malformed"
  | "confirmed_no_match";
export type ExceptionStatus = "open" | "approved" | "rejected";
export type ReviewAction = "approve" | "reject";
export type ClosePosture = "ready" | "review required";
export type CloseBriefMode = "provider" | "deterministicFallback" | "not required";

export interface Batch {
  batchId: string;
  kind: BatchKind;
  status: BatchStatus;
  seed: string | null;
  groundTruthAvailable: boolean;
  sourceRowCount: number;
  startedAt: string | null;
  completedAt: string | null;
  sourceCounts: Record<string, number> | null;
}

export interface CriterionEvidence {
  ruleCode: string;
  observedValues: Record<string, unknown>;
  points: number;
  result: string;
  explanation: string;
}

export interface ScoredCandidate {
  candidateId: string;
  score: number;
  evidence: CriterionEvidence[];
  contradictions: string[];
  duplicate: boolean;
  exactIdentifierChain: boolean;
  verifiedSettlementMath: boolean;
}

export interface ReconciliationResult {
  resultId: string;
  stage: ReconciliationStage;
  status: ResultStatus;
  primarySourceType: string;
  primarySourceId: string | null;
  amount: number | null;
  currency: string | null;
  score: number;
  runnerUpScore: number;
  margin: number;
  autonomous: boolean;
  selectedIds: string[];
  evidence: CriterionEvidence[];
  candidates: ScoredCandidate[];
}

export interface MatchLink {
  linkId: string;
  resultId: string;
  sourceType: string;
  sourceId: string;
  role: string;
  autonomous: boolean;
  actor: string;
}

export interface ExceptionSummary {
  exceptionId: string;
  runId: string | null;
  batchId: string | null;
  resultId: string | null;
  status: ExceptionStatus;
  exceptionType: string;
  sourceType: string | null;
  sourceId: string | null;
  amount: number | null;
  message: string;
  reviewNote?: string | null;
  reviewedBy?: string | null;
  reviewedAt?: string | null;
  createdAt: string;
  aiReady: boolean;
}

export interface ReviewDecision {
  exceptionId: string;
  resultId: string | null;
  action: ReviewAction;
  status: ExceptionStatus;
  candidateId: string | null;
  note: string | null;
  actor: string;
  reviewedAt: string;
  linkId: string | null;
}

export interface AIInvestigation {
  investigationId: string;
  exceptionId: string;
  runId: string;
  batchId: string;
  mode: string;
  provider: string | null;
  model: string | null;
  recommendation: string;
  confidence: number;
  citations: Record<string, unknown>[];
  toolTrace: Record<string, unknown>[];
  errorCode: string | null;
  errorMessage: string | null;
}

export interface ExceptionDetail extends ExceptionSummary {
  result: ReconciliationResult | null;
  sourceSummaries: Record<string, unknown>[];
  criterionEvidence: CriterionEvidence[];
  arithmetic: Record<string, unknown>;
  aiInvestigations: AIInvestigation[];
  auditEvents: AuditEvent[];
}

export interface ScenarioMetric {
  scenarioClass: string;
  cases: number;
  matchableCases: number;
  correctlyResolved: number;
  matchRate: number;
  autonomousCases: number;
  falsePositives: number;
  precision: number;
  openExceptions: number;
  financiallyUnresolvedCases: number;
  moneyReconciled: number;
  moneyUnresolved: number;
}

export interface StageMetric {
  eligibleCases: number;
  correctlyResolved: number;
  correctnessRate: number;
  autonomousCases: number;
  autonomyRate: number;
  autonomousLinks: number;
  falsePositives: number;
  precision: number;
  unresolvedCases: number;
  openExceptions: number;
  recordsProcessed: number;
}

export interface RunMetrics {
  runId?: string;
  reportVersion: number;
  benchmarkAvailable: boolean;
  precision: number | null;
  falsePositives: number | null;
  falsePositiveRate: number | null;
  matchRate: number | null;
  endToEndAutonomyRate: number | null;
  exceptionRecall: number | null;
  correctlyResolved: number | null;
  matchableCases: number | null;
  autonomousCases: number | null;
  openExceptions: number;
  financiallyUnresolvedCases: number | null;
  moneyReconciled: number | null;
  moneyUnresolved: number | null;
  settlementNet: number;
  recordsProcessed: number;
  durationMs: number;
  throughput: number;
  perClass: Record<string, ScenarioMetric> | null;
  stageMetrics: Record<string, StageMetric> | null;
  reviewAdjusted: Record<string, unknown>;
  acceptanceChecks: Record<string, boolean>;
  acceptancePassed: boolean;
  benchmarkUnavailable?: boolean | null;
  sourceThroughput?: number | null;
}

export interface RunSummary {
  runId: string;
  batchId: string;
  batchKind: BatchKind;
  status: RunStatus;
  sourceRowCount: number;
  sourceCounts: Record<string, number>;
  startedAt: string;
  completedAt: string | null;
  durationMs: number | null;
  throughput: number | null;
  metrics: RunMetrics | null;
  errorMessage: string | null;
}

export interface BatchCloseCitation {
  exceptionId: string;
  sourceType?: string | null;
  sourceId?: string | null;
}

export interface BatchCloseTheme {
  themeId: string;
  title: string;
  summary: string;
  exceptionIds: string[];
  exceptionCount: number;
  moneyExposure: number;
  priority: number;
  reviewAction: string;
  citations: BatchCloseCitation[];
}

export interface BatchCloseReviewAction {
  priority: number;
  action: string;
  exceptionIds: string[];
  citations: BatchCloseCitation[];
}

export interface BatchCloseBrief {
  briefId: string;
  runId: string;
  batchId: string;
  posture: ClosePosture;
  deterministicCoverage: {
    sourceRows: number;
    results: number;
    openExceptions: number;
  };
  aiCoverage: {
    openExceptions: number;
    coveredExceptions: number;
  };
  moneyReconciled: number;
  moneyUnresolved: number;
  openExceptions: number;
  financialRecordsChanged: number;
  mode: CloseBriefMode;
  provider: string | null;
  model: string | null;
  themes: BatchCloseTheme[];
  reviewPlan: BatchCloseReviewAction[];
  citations: BatchCloseCitation[];
  generatedAt: string;
  stale: boolean;
  staleAt: string | null;
  durationMs: number;
  errorCode: string | null;
  errorMessage: string | null;
  actor: string;
}

export interface RunDetail extends RunSummary {
  results: ReconciliationResult[];
  links: MatchLink[];
  exceptions: ExceptionSummary[];
  closeBrief: BatchCloseBrief | null;
}

export interface TransactionRecord {
  sourceType: string;
  sourceId: string | null;
  reference: string | null;
  amount: number | null;
  currency: string | null;
  status: string;
  businessAt: string | null;
  batchId: string;
  reconciliationState: string;
  parseError: string | null;
  runId: string | null;
  resultId: string | null;
  exceptionId: string | null;
}

export interface AuditEvent {
  eventId: string;
  batchId: string | null;
  eventType: string;
  sequence: number;
  actor: string;
  entityType: string;
  entityId: string | null;
  sourceType: string | null;
  sourceId: string | null;
  occurredAt: string;
  summary: string;
  toolTrace: Record<string, unknown> | null;
}

export interface CopilotCitation {
  sourceType: string;
  sourceId: string;
}

export interface CopilotAnswer {
  answer: string;
  mode: string;
  citations: CopilotCitation[];
  calculation: Record<string, unknown> | null;
  toolTrace: Record<string, unknown>[];
  errorCode: string | null;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface OverviewData {
  metrics: RunMetrics | null;
  latestBatch: Batch | null;
}
