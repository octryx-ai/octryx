// Thread usage, cost, workflow ROI and code intelligence statistics.

export type ThreadUsageStats = {
  contextTokens: number;
  inputTokens: number;
  outputTokens: number;
  cacheReadInputTokens?: number;
  cacheWriteInputTokens?: number;
  nonCachedInputTokens?: number;
  totalCost?: number;
  costByModel?: Array<{
    provider: string;
    model: string;
    requestCount: number;
    inputTokens: number;
    outputTokens: number;
    cost: number;
  }>;
  requestCount: number;
  llmRequestCount?: number;
  toolCallCount?: number;
  turnTraceCount?: number;
  deterministicStepCount?: number;
  zeroCostReason?: string;
  workflowRoi?: {
    status: string;
    workflowId: string;
    workflowClass: string;
    baselineSampleCount: number;
    current: WorkflowRoiMetrics;
    baseline: WorkflowRoiMetrics;
    savings: {
      tokenDelta: number;
      tokenReductionPercent: number;
      costDelta: number;
      costReductionPercent: number;
      llmRequestDelta: number;
      toolCallDelta: number;
    };
    quality: {
      status: string;
      current: WorkflowRoiQualityBucket;
      baseline: WorkflowRoiQualityBucket;
    };
  } | null;
  messageCount: number;
  userMessageCount: number;
  assistantMessageCount: number;
  lastModel: string;
  lastProvider: string;
};

export type WorkflowRoiMetrics = {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  totalCost: number;
  llmRequestCount: number;
  toolCallCount: number;
  deterministicStepCount: number;
};

export type WorkflowRoiQualityBucket = {
  runCount: number;
  passedCount: number;
  failedCount: number;
  passRate: number;
};

export type ThreadCodeIntelligenceStats = {
  rows: Array<{ label: string; value: string }>;
  repositoryBackends: Record<string, string> | null;
  totalToolCalls: number;
  codeToolCalls: number;
  fallbackToolCalls: number;
  fallbackRate: number;
  hasData: boolean;
};
