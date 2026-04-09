export interface WorldRecord {
  id: string;
  name: string;
  seed_text: string;
  status: string;
  graph_id?: string | null;
  graph_node_count?: number;
  graph_edge_count?: number;
  entity_types?: string[];
  error?: string | null;
  build_summary?: string;
  current_tick?: number;
}

export interface GraphNode {
  id: string;
  label?: string;
  name?: string;
  kind?: string;
  summary?: string;
  group?: number;
}

export interface GraphEdge {
  id?: string;
  source: string;
  target: string;
  relation?: string;
  relation_type?: string;
  label?: string;
  value?: number;
  timestamp?: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphStatus {
  status: string;
  graph_id?: string | null;
  node_count: number;
  edge_count: number;
  entity_types: string[];
  error?: string | null;
}

export interface TaskRecord {
  id: string;
  project_id: string;
  type: string;
  status: string;
  progress: number;
  message: string;
  result: Record<string, unknown>;
}

export interface WorldSnapshot {
  world_id: string;
  name: string;
  actor_entity_ids?: string[];
  global_variables?: Array<{
    name: string;
    value: unknown;
    description?: string;
  }>;
  entities: Array<{
    id: string;
    name: string;
    entity_type?: string;
    description?: string;
  }>;
  relations: Array<{
    id: string;
    source_entity_id: string;
    target_entity_id: string;
    relation_type: string;
    description?: string;
  }>;
  personas: Array<{
    entity_id: string;
    identity_summary?: string;
    goals?: string[];
    behavior_style?: string;
    speech_style?: string;
  }>;
  build_summary?: string;
  current_tick: number;
  timeline?: Array<{
    id: string;
    tick: number;
    event_type: string;
    title: string;
    description: string;
    participants?: string[];
    created_by?: string;
    created_at?: string;
    payload?: Record<string, unknown>;
    parent_event_id?: string;
    source_entity_id?: string;
    source_module?: string;
    trigger_reason?: string;
  }>;
}

export interface WorldTimelineEvent {
  id: string;
  tick: number;
  event_type: string;
  title: string;
  description: string;
  participants?: string[];
  created_by?: string;
  created_at?: string;
  payload?: Record<string, unknown>;
  parent_event_id?: string;
  source_entity_id?: string;
  source_module?: string;
  trigger_reason?: string;
}

export interface SimulationStatus {
  initialized: boolean;
  is_running?: boolean;
  step_count?: number;
  current_time?: string;
  agent_count?: number;
  time_horizon_days?: number;
  tick_seconds?: number;
  recommended_steps?: number;
  latest_run_id?: string;
  latest_run_status?: string;
  latest_run_steps?: number;
  latest_run_new_event_count?: number;
}

export interface WorldStatus {
  world_id: string;
  world_status: string;
  current_tick: number;
  entity_count: number;
  relation_count: number;
  actor_count?: number;
  agent_count: number;
  graph_status?: string;
  graph_task_id?: string;
  graph_progress?: number;
  graph_message?: string;
  graph_node_count?: number;
  graph_edge_count?: number;
  graph_error?: string | null;
}

export interface SimulationAgent {
  id: number;
  name: string;
  profile?: Record<string, unknown>;
  memory_count?: number;
  inbox_count?: number;
  last_step_result?: unknown;
}

export interface SimulationStepResult {
  type: string;
  step: number;
  time: string;
  tick: number;
  agent_results: unknown[];
  new_events: unknown[];
  graph_update?: {
    node_count: number;
    edge_count: number;
  };
}

export interface ReportSection {
  title: string;
  content: string;
}

export interface ReportData {
  markdown: string;
  title: string;
  sections: ReportSection[];
  report_id?: string;
  report_type?: string;
  created_at?: string;
  focus?: string;
}

export interface TimelineInterventionResult {
  world_id: string;
  source_world_id?: string;
  source_tick?: number;
  intervention_id?: string;
  graph_task_id?: string;
  graph_status?: string;
  updated_snapshot?: WorldSnapshot;
  timeline?: WorldTimelineEvent[];
}

type ApiEnvelope<T> = {
  success: boolean;
  data?: T;
  count?: number;
  message?: string;
  answer?: string;
  result?: unknown;
  stopped?: boolean;
  error?: string;
  detail?: string;
};

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `请求失败：${response.status}`);
  }

  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) {
    return undefined as T;
  }

  const payload = (await response.json()) as ApiEnvelope<T> | T;
  if (typeof payload === 'object' && payload !== null && 'success' in payload) {
    if (!payload.success) {
      throw new Error(payload.error || payload.detail || payload.message || '接口请求失败');
    }
    if ('data' in payload && payload.data !== undefined) {
      return payload.data;
    }
  }

  return payload as T;
}

function toCsv(values?: string[]) {
  return values && values.length ? values.join(',') : undefined;
}

function deriveEntityTypes(nodes: GraphNode[]) {
  return Array.from(new Set(nodes.map((node) => node.kind).filter(Boolean))) as string[];
}

function buildReportSections(content: string): ReportSection[] {
  const blocks = content
    .split(/\n\s*\n/g)
    .map((block) => block.trim())
    .filter(Boolean);

  return blocks.map((block, index) => {
    const lines = block.split('\n').map((line) => line.trim()).filter(Boolean);
    const firstLine = lines[0] || '';
    const title = firstLine.length <= 40 ? firstLine.replace(/^#+\s*/, '') : `段落 ${index + 1}`;
    return {
      title,
      content: lines.length > 1 && firstLine.length <= 40 ? lines.slice(1).join('\n') : block,
    };
  });
}

export function checkHealth() {
  return apiRequest<{ status: string }>('/api/v1/health');
}

export async function createProject(input: {
  name: string;
  seed_materials: Array<{
    id?: string;
    kind: string;
    title: string;
    content: string;
    source?: string;
    metadata?: Record<string, unknown>;
  }>;
  simulation_goal?: string;
}) {
  const response = await apiRequest<{
    task_id: string;
    world_id: string;
    status?: string;
    message?: string;
  }>('/api/v1/worlds/build', {
    method: 'POST',
    body: JSON.stringify({
      name: input.name,
      simulation_goal: input.simulation_goal || '',
      seed_materials: input.seed_materials,
    }),
  });

  return {
    id: response.world_id,
    task_id: response.task_id,
    status: response.status || 'pending',
    message: response.message || '世界构建任务已提交',
  };
}

export async function getWorldBuildTask(taskId: string): Promise<TaskRecord> {
  const task = await apiRequest<{
    task_id: string;
    world_id?: string;
    type?: string;
    status: string;
    progress: number;
    message: string;
    result?: Record<string, unknown> | null;
  }>(`/api/v1/worlds/tasks/${taskId}`);

  return {
    id: task.task_id,
    project_id: task.world_id || '',
    type: task.type || 'world_build',
    status: task.status,
    progress: task.progress,
    message: task.message,
    result: task.result || {},
  };
}

export function worldRecordFromBuildTaskResult(
  input: { name: string; seed_materials: Array<{ content: string }> },
  task: TaskRecord,
) {
  const result = task.result || {};
  const snapshot =
    result.snapshot && typeof result.snapshot === 'object'
      ? (result.snapshot as WorldSnapshot)
      : undefined;

  return {
    id: String(result.world_id || task.project_id || ''),
    name: input.name,
    seed_text: input.seed_materials.map((item) => item.content).join('\n\n'),
    status: 'world_ready',
    graph_id: typeof result.graph_task_id === 'string' ? result.graph_task_id : null,
    build_summary:
      typeof result.build_summary === 'string'
        ? result.build_summary
        : snapshot?.build_summary || '',
  } satisfies WorldRecord;
}

export async function buildGraph(projectId: string) {
  const response = await apiRequest<{ success: boolean; task_id?: string; error?: string }>(
    '/api/v1/graph/build',
    {
      method: 'POST',
      body: JSON.stringify({
        world_id: projectId,
      }),
    },
  );

  return {
    project_id: projectId,
    task_id: response.task_id || '',
    message: response.task_id ? '图谱构建已开始' : response.error || '图谱构建失败',
  };
}

export async function getGraphTask(_projectId: string, taskId: string): Promise<TaskRecord> {
  const task = await apiRequest<{
    task_id: string;
    world_id: string;
    status: string;
    progress: number;
    message: string;
    result?: Record<string, unknown> | null;
  }>(`/api/v1/graph/tasks/${taskId}`);

  return {
    id: task.task_id,
    project_id: task.world_id,
    type: 'graph_build',
    status: task.status,
    progress: task.progress,
    message: task.message,
    result: task.result || {},
  };
}

export function graphDataFromTaskResult(result?: Record<string, unknown> | null): GraphData | null {
  if (!result) return null;
  const nodes = Array.isArray(result.nodes) ? (result.nodes as GraphData['nodes']) : [];
  const edges = Array.isArray(result.edges) ? (result.edges as GraphData['edges']) : [];
  if (!nodes.length && !edges.length) return null;
  return { nodes, edges };
}

export function graphStatusFromTaskResult(
  projectId: string,
  result?: Record<string, unknown> | null,
): GraphStatus | null {
  const graphData = graphDataFromTaskResult(result);
  if (!graphData) return null;
  return {
    status: 'graph_ready',
    graph_id: projectId,
    node_count: graphData.nodes.length,
    edge_count: graphData.edges.length,
    entity_types: deriveEntityTypes(graphData.nodes),
    error: null,
  } satisfies GraphStatus;
}

export async function getGraphData(
  projectId: string,
  filters?: {
    entityTypes?: string[];
    relationTypes?: string[];
  },
) {
  const params = new URLSearchParams();
  const entityTypes = toCsv(filters?.entityTypes);
  const relationTypes = toCsv(filters?.relationTypes);
  if (entityTypes) params.set('entity_types', entityTypes);
  if (relationTypes) params.set('relation_types', relationTypes);
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return apiRequest<GraphData>(`/api/v1/graph/${projectId}/snapshot${suffix}`);
}

export async function getGraphStatus(projectId: string) {
  const graphData = await getGraphData(projectId).catch(() => ({ nodes: [], edges: [] }));
  return {
    status: graphData.nodes.length || graphData.edges.length ? 'graph_ready' : 'graph_pending',
    graph_id: projectId,
    node_count: graphData.nodes.length,
    edge_count: graphData.edges.length,
    entity_types: deriveEntityTypes(graphData.nodes),
    error: null,
  } satisfies GraphStatus;
}

export function getWorldStatus(projectId: string) {
  return apiRequest<WorldStatus>(`/api/v1/worlds/${projectId}/status`);
}

export function getWorldSnapshot(projectId: string) {
  return apiRequest<WorldSnapshot>(`/api/v1/worlds/${projectId}/snapshot`);
}

export async function getSimulationStatus(projectId: string) {
  const status = await apiRequest<{
    initialized: boolean;
    current_tick: number;
    agent_count: number;
    tick_seconds?: number;
    time_horizon_days?: number;
    recommended_steps?: number;
    latest_run_id?: string;
    latest_run_status?: string;
    latest_run_steps?: number;
    latest_run_new_event_count?: number;
  }>(`/api/v1/worlds/${projectId}/simulation/status`);

  return {
    initialized: status.initialized,
    is_running: status.latest_run_status === 'running',
    step_count: status.current_tick || 0,
    agent_count: status.agent_count,
    time_horizon_days: status.time_horizon_days,
    tick_seconds: status.tick_seconds,
    recommended_steps: status.recommended_steps,
    latest_run_id: status.latest_run_id,
    latest_run_status: status.latest_run_status,
    latest_run_steps: status.latest_run_steps,
    latest_run_new_event_count: status.latest_run_new_event_count,
  } satisfies SimulationStatus;
}

export function getWorldTimeline(
  projectId: string,
  options?: { limit?: number; afterTick?: number; eventType?: string },
) {
  const params = new URLSearchParams();
  if (options?.limit) params.set('limit', String(options.limit));
  if (typeof options?.afterTick === 'number') params.set('after_tick', String(options.afterTick));
  if (options?.eventType) params.set('event_type', options.eventType);
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return apiRequest<WorldTimelineEvent[]>(`/api/v1/worlds/${projectId}/timeline${suffix}`);
}

export function getSimulationAgents(projectId: string) {
  return apiRequest<SimulationAgent[]>(`/api/v1/worlds/${projectId}/agents`);
}

export async function stepSimulation(projectId: string, tick?: number) {
  const result = await apiRequest<{
    success: boolean;
    world_id?: string;
    tick?: number;
    new_events?: number;
    active_agents?: number;
  }>(`/api/v1/worlds/${projectId}/step${tick ? `?tick_seconds=${tick}` : ''}`);

  return {
    type: 'world_step',
    step: result.tick || 0,
    time: new Date().toISOString(),
    tick: result.tick || 0,
    agent_results: [],
    new_events: Array.from({ length: result.new_events || 0 }, (_, index) => ({ id: index })),
  } satisfies SimulationStepResult;
}

export async function runSimulation(projectId: string, numSteps: number, tick?: number) {
  const result = await apiRequest<{
    success: boolean;
    run_id?: string;
    world_id?: string;
    executed_steps?: number;
    new_event_count?: number;
    updated_snapshot?: WorldSnapshot;
  }>(`/api/v1/worlds/${projectId}/simulate`, {
    method: 'POST',
    body: JSON.stringify({
      steps: numSteps,
      ...(tick ? { tick_seconds: tick } : {}),
      stop_when_stable: false,
    }),
  });

  return {
    run_id: result.run_id || '',
    num_steps: result.executed_steps || numSteps,
    new_event_count: result.new_event_count || 0,
    updated_snapshot: result.updated_snapshot,
  };
}

export async function chatWithAgent(projectId: string, agentId: string, message: string) {
  return apiRequest<{ success: boolean; agent_id?: string; answer?: string; error?: string }>(
    `/api/v1/worlds/${projectId}/agents/${agentId}/chat`,
    { method: 'POST', body: JSON.stringify({ message }) },
  );
}

export async function chatWithWorld(projectId: string, message: string) {
  return apiRequest<{ success: boolean; answer?: string; context?: Record<string, unknown>; error?: string }>(
    `/api/v1/worlds/${projectId}/chat`,
    { method: 'POST', body: JSON.stringify({ message }) },
  );
}

export async function applyIntervention(
  projectId: string,
  interventionType: string,
  payload: Record<string, unknown>,
  reason: string = '',
) {
  return apiRequest<{ success: boolean; intervention_id?: string; tick?: number }>(
    `/api/v1/worlds/${projectId}/interventions`,
    {
      method: 'POST',
      body: JSON.stringify({ intervention_type: interventionType, payload, reason }),
    },
  );
}

export async function branchTimelineIntervention(
  projectId: string,
  input: {
    anchorTick: number;
    command: string;
    continuationSteps?: number;
    tickSeconds?: number;
    branchName?: string;
  },
) {
  return apiRequest<TimelineInterventionResult>(`/api/v1/worlds/${projectId}/timeline/interventions`, {
    method: 'POST',
    body: JSON.stringify({
      anchor_tick: input.anchorTick,
      command: input.command,
      continuation_steps: input.continuationSteps ?? 5,
      ...(input.tickSeconds ? { tick_seconds: input.tickSeconds } : {}),
      ...(input.branchName ? { branch_name: input.branchName } : {}),
    }),
  });
}

export async function generateReport(projectId: string) {
  const result = await apiRequest<{
    success: boolean;
    report_id?: string;
    world_id?: string;
    report_type?: string;
    content?: string;
    created_at?: string;
    focus?: string;
  }>(`/api/v1/worlds/${projectId}/report`, {
    method: 'POST',
    body: JSON.stringify({
      report_type: 'prediction',
    }),
  });

  const markdown = result.content || '';
  return {
    markdown,
    title: '世界预测报告',
    sections: buildReportSections(markdown),
    report_id: result.report_id,
    report_type: result.report_type || 'prediction',
    created_at: result.created_at,
    focus: result.focus,
  } satisfies ReportData;
}

export async function getLatestReport(projectId: string) {
  const result = await apiRequest<{
    report_id?: string;
    world_id?: string;
    report_type?: string;
    focus?: string;
    content?: string;
    created_at?: string;
  }>(`/api/v1/worlds/${projectId}/report/latest`);

  const markdown = result.content || '';
  return {
    markdown,
    title: '世界预测报告',
    sections: buildReportSections(markdown),
    report_id: result.report_id,
    report_type: result.report_type || 'prediction',
    created_at: result.created_at,
    focus: result.focus,
  } satisfies ReportData;
}
