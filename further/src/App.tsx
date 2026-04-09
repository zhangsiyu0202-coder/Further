import { useEffect, useRef, useState } from 'react';
import {
  Target,
  PieChart,
  BarChart3,
  Link2,
  MessageCircle,
} from 'lucide-react';
import WorldStatePage from './components/pages/WorldStatePage';
import AgentInteractionPage from './components/pages/AgentInteractionPage';
import SeedMaterialsPage from './components/pages/SeedMaterialsPage';
import WorldOverviewPage from './components/pages/WorldOverviewPage';
import ReportPage from './components/pages/ReportPage';
import { cn } from './lib/utils';
import {
  branchTimelineIntervention,
  buildGraph,
  checkHealth,
  createProject,
  generateReport,
  getLatestReport,
  graphDataFromTaskResult,
  graphStatusFromTaskResult,
  getGraphData,
  getGraphStatus,
  getSimulationAgents,
  getSimulationStatus,
  getWorldStatus,
  getWorldSnapshot,
  getWorldTimeline,
  GraphData,
  GraphStatus,
  ReportData,
  SimulationAgent,
  SimulationStatus,
  stepSimulation,
  runSimulation,
  TaskRecord,
  worldRecordFromBuildTaskResult,
  WorldSnapshot,
  WorldTimelineEvent,
} from './lib/api';
import { AppContext } from './lib/AppContext';
import ErrorBoundary from './components/ErrorBoundary';
import { useTaskStream } from './lib/useTaskStream';

const PAGES = [
  { id: 'seed-materials', title: '种子材料', icon: Target },
  { id: 'world-overview', title: '世界总览', icon: BarChart3 },
  { id: 'world-state', title: '世界状态链', icon: Link2 },
  { id: 'agent-interaction', title: 'Agent 交互', icon: MessageCircle },
  { id: 'report', title: '报告', icon: PieChart },
] as const;

type PageId = (typeof PAGES)[number]['id'];

const EMPTY_GRAPH: GraphData = { nodes: [], edges: [] };
const PREDICTION_STORAGE_KEY = 'agentsociety.predictionData.v1';
const BACKEND_STORAGE_KEY = 'agentsociety.backendState.v1';

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function readStoredJson<T>(key: string): T | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function normalizePredictionData(
  stored: {
    objective?: string;
    background?: string;
    seedMaterials?: Array<{
      id?: string;
      title?: string;
      kind?: string;
      content?: string;
      source?: string;
      notes?: string;
    }>;
  } | null,
) {
  const seedMaterials = stored?.seedMaterials?.length
    ? stored.seedMaterials.map((material, index) => ({
        id: material.id || `seed-${index + 1}`,
        title: material.title || `材料 ${index + 1}`,
        kind: material.kind || 'text',
        content: material.content || '',
        source: material.source || '',
        notes: material.notes || '',
      }))
    : [
        {
          id: 'seed-1',
          title: '材料 1',
          kind: 'text',
          content: stored?.background || '',
          source: '',
          notes: '',
        },
      ];

  return {
    objective: stored?.objective || '',
    seedMaterials,
  };
}

export default function App() {
  const [currentPage, setCurrentPage] = useState<PageId>(() => {
    if (typeof window === 'undefined') return 'seed-materials';
    const hash = window.location.hash.replace('#', '');
    return (PAGES.find((page) => page.id === hash)?.id || 'seed-materials') as PageId;
  });
  const [predictionData, setPredictionData] = useState(() =>
    normalizePredictionData(
      readStoredJson<{
        objective?: string;
        background?: string;
        seedMaterials?: Array<{
          id?: string;
          title?: string;
          kind?: string;
          content?: string;
          source?: string;
          notes?: string;
        }>;
      }>(PREDICTION_STORAGE_KEY),
    ),
  );
  const [backendState, setBackendState] = useState(() => {
    const stored = readStoredJson<{
      projectId?: string;
      projectStatus?: string;
      graphStatus?: GraphStatus | null;
      graphData?: GraphData;
      currentTask?: TaskRecord | null;
      simSteps?: number;
      activity?: string[];
      report?: ReportData | null;
    }>(BACKEND_STORAGE_KEY);
    return {
    apiReady: false,
    projectId: stored?.projectId || '',
    projectStatus: stored?.projectStatus || 'idle',
    graphStatus: stored?.graphStatus || null as GraphStatus | null,
    graphData: stored?.graphData || EMPTY_GRAPH,
    simulationStatus: { initialized: false } as SimulationStatus,
    worldSnapshot: null as WorldSnapshot | null,
    worldTimeline: [] as WorldTimelineEvent[],
    agents: [] as SimulationAgent[],
    report: stored?.report || null as ReportData | null,
    currentTask: stored?.currentTask || null as TaskRecord | null,
    busyAction: '',
    simSteps: stored?.simSteps || 5,
    activity: stored?.activity || [] as string[],
    error: '',
  };
  });

  const setBusyAction = (busyAction: string) => {
    setBackendState((prev) => ({ ...prev, busyAction }));
  };

  const setSimSteps = (simSteps: number) => {
    setBackendState((prev) => ({ ...prev, simSteps: Math.max(1, Math.min(100, simSteps)) }));
  };

  const clearError = () => {
    setBackendState((prev) => ({ ...prev, error: '' }));
  };

  const setError = (error: unknown) => {
    const message = error instanceof Error ? error.message : '请求失败';
    setBackendState((prev) => ({ ...prev, error: message }));
  };

  const pushActivity = (message: string) => {
    setBackendState((prev) => ({
      ...prev,
      activity: [message, ...prev.activity].slice(0, 8),
    }));
  };

  const updateData = (data: Partial<typeof predictionData>) => {
    setPredictionData((prev) => ({ ...prev, ...data }));
  };

  const refreshGraph = async (projectId: string) => {
    const [worldStatus, graphData] = await Promise.all([
      getWorldStatus(projectId).catch(() => null),
      getGraphData(projectId).catch(() => EMPTY_GRAPH),
    ]);

    const graphStatus =
      worldStatus
        ? ({
            status:
              worldStatus.graph_status === 'completed'
                ? 'graph_ready'
                : worldStatus.graph_status || 'graph_pending',
            graph_id: projectId,
            node_count: worldStatus.graph_node_count || graphData.nodes.length,
            edge_count: worldStatus.graph_edge_count || graphData.edges.length,
            entity_types: [],
            error: worldStatus.graph_error || null,
          } satisfies GraphStatus)
        : await getGraphStatus(projectId);

    setBackendState((prev) => ({
      ...prev,
      projectStatus: worldStatus?.world_status || graphStatus.status,
      graphStatus,
      graphData,
      currentTask:
        worldStatus?.graph_task_id && worldStatus.graph_status !== 'completed'
          ? {
              id: worldStatus.graph_task_id,
              project_id: projectId,
              type: 'graph_build',
              status: worldStatus.graph_status || 'pending',
              progress: worldStatus.graph_progress || 0,
              message: worldStatus.graph_message || '图谱构建中',
              result: {},
            }
          : prev.currentTask,
    }));
  };

  const applyGraphTaskResult = (projectId: string, task: TaskRecord) => {
    const graphData = graphDataFromTaskResult(task.result);
    const graphStatus = graphStatusFromTaskResult(projectId, task.result);
    if (!graphData || !graphStatus) {
      return false;
    }
    setBackendState((prev) => ({
      ...prev,
      graphData,
      graphStatus,
      projectStatus: 'graph_ready',
      currentTask: task,
    }));
    return true;
  };

  const refreshSimulation = async (projectId: string) => {
    const [simulationStatus, agents, worldSnapshot, worldTimeline] = await Promise.all([
      getSimulationStatus(projectId),
      getSimulationAgents(projectId).catch(() => []),
      getWorldSnapshot(projectId).catch(() => null),
      getWorldTimeline(projectId, { limit: 200 }).catch(() => []),
    ]);

    setBackendState((prev) => ({
      ...prev,
      simulationStatus,
      simSteps:
        simulationStatus.recommended_steps && simulationStatus.recommended_steps > 0
          ? Math.max(1, Math.min(100, simulationStatus.recommended_steps))
          : prev.simSteps,
      worldSnapshot,
      worldTimeline,
      agents,
    }));
  };

  const syncProject = async () => {
    const hasSeedMaterials = predictionData.seedMaterials.some((material) => material.content.trim());
    if (!predictionData.objective.trim() && !hasSeedMaterials) {
      setBackendState((prev) => ({
        ...prev,
        error: '请先填写预测需求或信息材料，再同步到后端。',
      }));
      return;
    }

    setBusyAction('syncProject');
    clearError();

    try {
      const createProjectInput = {
        name: predictionData.objective.trim() || `预测项目 ${new Date().toLocaleString()}`,
        seed_materials: predictionData.seedMaterials
          .filter((material) => material.content.trim())
          .map((material) => ({
            id: material.id,
            kind: material.kind,
            title: material.title,
            content: material.content,
            source: material.source,
            metadata: material.notes ? { notes: material.notes } : {},
          })),
        simulation_goal: predictionData.objective.trim(),
      };

      const submitted = await createProject(createProjectInput);
      pushActivity(submitted.message || '世界构建任务已提交');
      setBackendState((prev) => ({
        ...prev,
        projectId: submitted.id,
        projectStatus: submitted.status,
        currentTask: {
          id: submitted.task_id,
          project_id: submitted.id,
          type: 'world_build',
          status: submitted.status,
          progress: 0,
          message: submitted.message || '世界构建任务已提交',
          result: {},
        },
        graphStatus: null,
        graphData: EMPTY_GRAPH,
        simulationStatus: { initialized: false },
        worldSnapshot: null,
        worldTimeline: [],
        agents: [],
        report: null,
      }));

      let project = null as ReturnType<typeof worldRecordFromBuildTaskResult> | null;
      await new Promise<void>((resolve, reject) => {
        worldBuildTaskIdRef.current = submitted.task_id;
        const cleanup = watchWorldBuildTask(submitted.task_id, createProjectInput, (p, err) => {
          cleanup();
          if (err) reject(err);
          else { project = p; resolve(); }
        });
      });

      if (!project) {
        throw new Error('世界构建超时，请稍后重试');
      }

      setBackendState((prev) => ({
        ...prev,
        projectId: project.id,
        projectStatus: project.status,
        graphStatus: null,
        graphData: EMPTY_GRAPH,
        simulationStatus: { initialized: false },
        worldSnapshot: null,
        worldTimeline: [],
        agents: [],
        report: null,
        currentTask: null,
      }));
      pushActivity(`已创建世界 ${project.name}`);
      await refreshSimulation(project.id);

      const taskStart = project.graph_id
        ? {
            project_id: project.id,
            task_id: project.graph_id,
            message: '知识图谱构建已在世界构建阶段自动提交',
          }
        : await buildGraph(project.id);
      pushActivity(taskStart.message || '知识图谱构建已提交到后端');
      graphBuildTaskIdRef.current = taskStart.task_id;
      setBackendState((prev) => ({
        ...prev,
        currentTask: {
          id: taskStart.task_id,
          project_id: project!.id,
          type: 'graph_build',
          status: 'pending',
          progress: 0,
          message: '图谱构建已提交',
          result: {},
        },
      }));
    } catch (error) {
      setError(error);
    } finally {
      setBusyAction('');
    }
  };

  const initializeSimulation = async () => {
    if (!backendState.projectId) {
      setBackendState((prev) => ({
        ...prev,
        error: '请先创建项目并完成图谱构建。',
      }));
      return;
    }

    setBusyAction('initializeSimulation');
    clearError();

    try {
      await refreshSimulation(backendState.projectId);
      pushActivity('已刷新世界智能体视图。');
    } catch (error) {
      setError(error);
    } finally {
      setBusyAction('');
    }
  };

  const runSingleStep = async () => {
    if (!backendState.projectId) {
      setBackendState((prev) => ({
        ...prev,
        error: '请先创建项目。',
      }));
      return;
    }

    if (!backendState.simulationStatus.initialized) {
      await initializeSimulation();
      if (!backendState.projectId) {
        return;
      }
    }

    setBusyAction('runSingleStep');
    clearError();

    try {
      const result = await stepSimulation(backendState.projectId);
      await Promise.all([
        refreshSimulation(backendState.projectId),
        refreshGraph(backendState.projectId),
      ]);
      pushActivity(`已执行到时间步 ${result.tick}，新增 ${result.new_events.length} 条事件`);
    } catch (error) {
      setError(error);
    } finally {
      setBusyAction('');
    }
  };

  const runMultipleSteps = async () => {
    if (!backendState.projectId) {
      setError('请先创建项目。');
      return;
    }

    if (!backendState.simulationStatus.initialized) {
      await initializeSimulation();
    }

    setBusyAction('runMultipleSteps');
    clearError();

    try {
      const result = await runSimulation(backendState.projectId, backendState.simSteps);
      await Promise.all([
        refreshSimulation(backendState.projectId),
        refreshGraph(backendState.projectId),
      ]);
      pushActivity(
        `批量仿真完成，执行 ${result.num_steps} 步，新增 ${result.new_event_count} 条事件`,
      );
    } catch (error) {
      setError(error);
    } finally {
      setBusyAction('');
    }
  };

  const loadReport = async () => {
    if (!backendState.projectId) {
      setBackendState((prev) => ({
        ...prev,
        error: '请先创建项目。',
      }));
      return;
    }

    setBusyAction('loadReport');
    clearError();

    try {
      const report = await generateReport(backendState.projectId);
      setBackendState((prev) => ({ ...prev, report }));
      pushActivity(`已生成报告《${report.title}》`);
    } catch (error) {
      setError(error);
    } finally {
      setBusyAction('');
    }
  };

  const loadLatestReport = async () => {
    if (!backendState.projectId) {
      setBackendState((prev) => ({
        ...prev,
        error: '请先创建项目。',
      }));
      return;
    }

    setBusyAction('loadLatestReport');
    clearError();

    try {
      const report = await getLatestReport(backendState.projectId);
      setBackendState((prev) => ({ ...prev, report }));
      pushActivity(`已读取最新报告《${report.title}》`);
    } catch (error) {
      setError(error);
    } finally {
      setBusyAction('');
    }
  };

  const branchFromTimeline = async (anchorTick: number, command: string) => {
    if (!backendState.projectId || !command.trim()) {
      return;
    }

    setBusyAction('branchTimelineIntervention');
    clearError();

    try {
      const result = await branchTimelineIntervention(backendState.projectId, {
        anchorTick,
        command,
        continuationSteps: backendState.simSteps,
        tickSeconds: backendState.simulationStatus.tick_seconds,
      });
      const nextProjectId = result.world_id || backendState.projectId;
      setBackendState((prev) => ({
        ...prev,
        projectId: nextProjectId,
        projectStatus: result.graph_status || 'world_ready',
        graphStatus: result.graph_task_id
          ? {
              status: result.graph_status || 'graph_pending',
              graph_id: nextProjectId,
              node_count: 0,
              edge_count: 0,
              entity_types: [],
              error: null,
            }
          : null,
        graphData: EMPTY_GRAPH,
        currentTask: result.graph_task_id
          ? {
              id: result.graph_task_id,
              project_id: nextProjectId,
              type: 'graph_build',
              status: result.graph_status || 'pending',
              progress: 0,
              message: '新分支图谱构建已提交',
              result: {},
            }
          : null,
        worldSnapshot: null,
        worldTimeline: [],
        agents: [],
        report: null,
      }));
      pushActivity(`已从 Tick ${anchorTick} 派生新分支 ${nextProjectId}`);
      await refreshSimulation(nextProjectId);
      setCurrentPage('world-state');
    } catch (error) {
      setError(error);
    } finally {
      setBusyAction('');
    }
  };

  const refreshGraphPanel = async () => {
    if (!backendState.projectId) {
      setError('请先创建项目。');
      return;
    }

    setBusyAction('refreshGraph');
    clearError();

    try {
      await refreshGraph(backendState.projectId);
      pushActivity('已手动刷新图谱。');
    } catch (error) {
      setError(error);
    } finally {
      setBusyAction('');
    }
  };

  const worldBuildTaskIdRef = useRef<string | null>(null);
  const graphBuildTaskIdRef = useRef<string | null>(null);

  const worldBuildStream = useTaskStream(
    backendState.busyAction === 'syncProject' ? worldBuildTaskIdRef.current : null,
    'world_build',
  );
  const graphBuildStream = useTaskStream(
    backendState.currentTask?.type === 'graph_build' &&
      backendState.currentTask.status !== 'completed' &&
      backendState.currentTask.status !== 'failed'
      ? backendState.currentTask.id
      : null,
    'graph_build',
  );

  useEffect(() => {
    if (!graphBuildStream.status || graphBuildStream.status === 'pending') return;
    const taskId = graphBuildTaskIdRef.current || backendState.currentTask?.id;
    if (!taskId || !backendState.projectId) return;
    setBackendState((prev) => ({
      ...prev,
      currentTask: prev.currentTask
        ? { ...prev.currentTask, status: graphBuildStream.status, progress: graphBuildStream.progress, message: graphBuildStream.message }
        : prev.currentTask,
      projectStatus: graphBuildStream.status,
    }));
    if (graphBuildStream.done && graphBuildStream.status === 'completed') {
      refreshGraph(backendState.projectId).then(() => {
        pushActivity(`图谱构建完成，节点数据已同步。`);
      });
    }
    if (graphBuildStream.done && graphBuildStream.status === 'failed') {
      setBackendState((prev) => ({ ...prev, error: graphBuildStream.error || '图谱构建失败' }));
    }
  }, [graphBuildStream.status, graphBuildStream.progress, graphBuildStream.done]);

  function watchWorldBuildTask(
    taskId: string,
    createProjectInput: Parameters<typeof worldRecordFromBuildTaskResult>[0],
    cb: (project: ReturnType<typeof worldRecordFromBuildTaskResult> | null, err?: Error) => void,
  ): () => void {
    let cancelled = false;
    const poll = async () => {
      for (let i = 0; i < 600 && !cancelled; i++) {
        try {
          const { getWorldBuildTask } = await import('./lib/api');
          const task = await getWorldBuildTask(taskId);
          if (cancelled) return;
          setBackendState((prev) => ({
            ...prev,
            projectId: task.project_id || prev.projectId,
            projectStatus: task.status,
            currentTask: task,
          }));
          if (task.status === 'completed') {
            cb(worldRecordFromBuildTaskResult(createProjectInput, task));
            return;
          }
          if (task.status === 'failed') {
            cb(null, new Error(task.message || '世界构建失败'));
            return;
          }
        } catch (e) {
          cb(null, e instanceof Error ? e : new Error('轮询失败'));
          return;
        }
        await sleep(1500);
      }
      cb(null, new Error('世界构建超时，请稍后重试'));
    };
    poll();
    return () => { cancelled = true; };
  }

  const refreshWorldOverview = async () => {
    if (!backendState.projectId) {
      setError('请先创建项目。');
      return;
    }

    setBusyAction('refreshOverview');
    clearError();

    try {
      await Promise.all([
        refreshSimulation(backendState.projectId),
        refreshGraph(backendState.projectId),
      ]);
      pushActivity('已刷新世界总览数据。');
    } catch (error) {
      setError(error);
    } finally {
      setBusyAction('');
    }
  };

  useEffect(() => {
    checkHealth()
      .then(() => {
        setBackendState((prev) => ({ ...prev, apiReady: true }));
      })
      .catch(() => {
        setBackendState((prev) => ({
          ...prev,
          apiReady: false,
          error: '后端 API 尚未启动，当前页面只会显示本地输入。',
        }));
      });
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(PREDICTION_STORAGE_KEY, JSON.stringify(predictionData));
  }, [predictionData]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.location.hash = currentPage;
  }, [currentPage]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(
      BACKEND_STORAGE_KEY,
      JSON.stringify({
        projectId: backendState.projectId,
        projectStatus: backendState.projectStatus,
        graphStatus: backendState.graphStatus,
        graphData: backendState.graphData,
        currentTask: backendState.currentTask,
        simSteps: backendState.simSteps,
        activity: backendState.activity,
        report: backendState.report,
      }),
    );
  }, [
    backendState.projectId,
    backendState.projectStatus,
    backendState.graphStatus,
    backendState.graphData,
    backendState.currentTask,
    backendState.simSteps,
    backendState.activity,
    backendState.report,
  ]);

  useEffect(() => {
    if (!backendState.apiReady || !backendState.projectId) {
      return;
    }
    refreshSimulation(backendState.projectId).catch(() => undefined);
    if (backendState.graphData.nodes.length === 0 && backendState.graphData.edges.length === 0) {
      refreshGraph(backendState.projectId).catch(() => undefined);
    }
  }, [backendState.apiReady, backendState.projectId]);

  const setReport = (report: ReportData) => {
    setBackendState((prev) => ({ ...prev, report }));
    pushActivity(`已生成报告《${report.title}》`);
  };

  const actions = {
    syncProject,
    initializeSimulation,
    runSingleStep,
    runMultipleSteps,
    setSimSteps,
    loadReport,
    loadLatestReport,
    branchFromTimeline,
    setReport,
    refreshGraphPanel,
    refreshWorldOverview,
    goToPage: (page: string) => setCurrentPage(page as PageId),
  };

  const contextValue = { backendState, predictionData, updateData, actions };

  const renderMainPanel = () => {
    if (currentPage === 'seed-materials') {
      return (
        <SeedMaterialsPage
          data={predictionData}
          updateData={updateData}
          backendState={backendState}
          actions={actions}
        />
      );
    }
    if (currentPage === 'world-overview') {
      return (
        <WorldOverviewPage
          data={predictionData}
          backendState={backendState}
          actions={actions}
        />
      );
    }
    if (currentPage === 'world-state') {
      return <WorldStatePage backendState={backendState} actions={actions} />;
    }
    if (currentPage === 'agent-interaction') {
      return (
        <AgentInteractionPage
          projectId={backendState.projectId}
          snapshot={backendState.worldSnapshot}
        />
      );
    }
    if (currentPage === 'report') {
      return <ReportPage backendState={backendState} actions={actions} />;
    }

    return null;
  };

  return (
    <AppContext.Provider value={contextValue}>
    <div className="flex h-screen bg-neutral-50 text-neutral-900 font-sans overflow-hidden">
      <aside className="w-20 bg-white border-r border-neutral-200 flex flex-col shadow-sm z-30">
        <div className="p-4 border-b border-neutral-100 flex items-center justify-center">
          <div className="w-10 h-10 rounded-lg bg-black flex items-center justify-center text-white font-bold shadow-md">
            F
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto p-3 space-y-3 pt-6">
          {PAGES.map((page) => {
            const Icon = page.icon;
            const isActive = page.id === currentPage;

            return (
              <button
                key={page.id}
                onClick={() => setCurrentPage(page.id)}
                className={cn(
                  'w-full flex flex-col items-center gap-1.5 p-2 rounded-xl transition-all duration-200 group relative',
                  isActive ? 'text-black' : 'text-neutral-400 hover:text-neutral-600',
                )}
                title={page.title}
              >
                <div
                  className={cn(
                    'w-10 h-10 rounded-full flex items-center justify-center border-2 transition-all duration-300 bg-white',
                    isActive
                      ? 'border-black text-black shadow-sm scale-110'
                      : 'border-neutral-200 text-neutral-300 group-hover:border-neutral-300',
                  )}
                >
                  <Icon className="w-5 h-5" />
                </div>
                <span className="text-[10px] font-medium truncate w-full text-center">
                  {page.title}
                </span>
              </button>
            );
          })}
        </nav>
      </aside>

      <div className="flex-1 flex overflow-hidden">
        <main
          className="flex flex-col h-full relative w-full bg-neutral-50/50"
        >
          <div className="flex-1 overflow-y-auto p-8 md:p-10">
            <div
              className={cn(
                'mx-auto h-full flex flex-col',
                currentPage === 'world-overview'
                  ? 'w-full max-w-[1680px]'
                  : currentPage === 'world-state' || currentPage === 'report'
                    ? 'w-full max-w-7xl'
                    : 'w-full max-w-4xl',
              )}
            >
              <ErrorBoundary>
                {renderMainPanel()}
              </ErrorBoundary>
            </div>
          </div>
        </main>
      </div>
    </div>
    </AppContext.Provider>
  );
}
