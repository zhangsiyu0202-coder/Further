import { useMemo, useState } from 'react';
import { FileText, Link2, Network, Play, RefreshCcw } from 'lucide-react';
import KnowledgeGraph from '../KnowledgeGraph';

function getHotTopics(snapshot: any) {
  const globals = snapshot?.global_variables || [];
  const eventConfig = globals.find((item: any) => item.name === 'event_config')?.value as
    | { hot_topics?: string[] }
    | undefined;
  return eventConfig?.hot_topics || [];
}

function getRecentEvents(snapshot: any, timeline: any[]) {
  const source = timeline.length > 0 ? timeline : snapshot?.timeline || [];
  return [...source]
    .sort((a, b) => {
      if (a.tick !== b.tick) return b.tick - a.tick;
      return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
    })
    .slice(0, 8);
}

export default function WorldOverviewPage({
  data,
  backendState,
  actions,
}: any) {
  const snapshot = backendState.worldSnapshot;
  const recentEvents = useMemo(
    () => getRecentEvents(snapshot, backendState.worldTimeline),
    [snapshot, backendState.worldTimeline],
  );
  const hotTopics = getHotTopics(snapshot);
  const [selectedEventId, setSelectedEventId] = useState<string>('');
  const isRunningStep = backendState.busyAction === 'runSingleStep';
  const isRunningMultiple = backendState.busyAction === 'runMultipleSteps';
  const isLoadingReport = backendState.busyAction === 'loadReport';
  const isRefreshingOverview = backendState.busyAction === 'refreshOverview';
  const selectedEvent =
    recentEvents.find((event) => event.id === selectedEventId) || recentEvents[0] || null;

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight text-neutral-900">世界总览</h2>
          <p className="text-neutral-500 mt-2 text-lg">
            把图谱、状态摘要、热点、关键指标和运行操作集中到一个主页面里。
          </p>
        </div>
        <div className="flex flex-wrap gap-3 justify-end">
          <button
            onClick={actions.refreshWorldOverview}
            disabled={isRefreshingOverview || !backendState.projectId}
            className="px-4 py-2.5 bg-white text-neutral-900 rounded-xl font-medium hover:bg-neutral-100 border border-neutral-200 disabled:opacity-50 flex items-center gap-2"
          >
            <RefreshCcw className="w-4 h-4" />
            {isRefreshingOverview ? '刷新中...' : '刷新总览'}
          </button>
          <button
            onClick={actions.runSingleStep}
            disabled={isRunningStep || isRunningMultiple || !backendState.projectId}
            className="px-4 py-2.5 bg-black text-white rounded-xl font-medium hover:bg-neutral-800 disabled:opacity-50 flex items-center gap-2"
          >
            <Play className="w-4 h-4" />
            {isRunningStep ? '执行中...' : '执行一步'}
          </button>
          <button
            onClick={actions.runMultipleSteps}
            disabled={isRunningStep || isRunningMultiple || !backendState.projectId}
            className="px-4 py-2.5 bg-neutral-800 text-white rounded-xl font-medium hover:bg-neutral-700 disabled:opacity-50 flex items-center gap-2"
          >
            <Play className="w-4 h-4" />
            {isRunningMultiple ? `运行 ${backendState.simSteps} 步中...` : `运行 ${backendState.simSteps} 步`}
          </button>
          <button
            onClick={actions.loadReport}
            disabled={isLoadingReport || !backendState.projectId}
            className="px-4 py-2.5 bg-white text-neutral-900 rounded-xl font-medium hover:bg-neutral-100 border border-neutral-200 disabled:opacity-50 flex items-center gap-2"
          >
            <FileText className="w-4 h-4" />
            {isLoadingReport ? '生成中...' : '生成报告'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-6 gap-4">
        <div className="bg-white rounded-2xl p-5 border border-neutral-200 shadow-sm">
          <div className="text-sm text-neutral-500">当前世界</div>
          <div className="text-sm font-medium text-neutral-900 mt-2 break-all">
            {backendState.projectId || '尚未创建'}
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 border border-neutral-200 shadow-sm">
          <div className="text-sm text-neutral-500">Current Tick</div>
          <div className="text-2xl font-semibold text-neutral-900 mt-2">
            {snapshot?.current_tick ?? 0}
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 border border-neutral-200 shadow-sm">
          <div className="text-sm text-neutral-500">实体数</div>
          <div className="text-2xl font-semibold text-neutral-900 mt-2">
            {snapshot?.entities?.length ?? 0}
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 border border-neutral-200 shadow-sm">
          <div className="text-sm text-neutral-500">关系数</div>
          <div className="text-2xl font-semibold text-neutral-900 mt-2">
            {snapshot?.relations?.length ?? 0}
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 border border-neutral-200 shadow-sm">
          <div className="text-sm text-neutral-500">智能体数</div>
          <div className="text-2xl font-semibold text-neutral-900 mt-2">
            {backendState.simulationStatus.agent_count || backendState.agents.length || 0}
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 border border-neutral-200 shadow-sm">
          <div className="text-sm text-neutral-500">图谱规模</div>
          <div className="text-sm text-neutral-900 mt-2 space-y-1">
            <div>节点 {backendState.graphStatus?.node_count || backendState.graphData.nodes.length || 0}</div>
            <div>边 {backendState.graphStatus?.edge_count || backendState.graphData.edges.length || 0}</div>
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 border border-neutral-200 shadow-sm xl:col-span-2">
          <div className="text-sm text-neutral-500">批量步数控制</div>
          <div className="flex items-center gap-3 mt-2">
            <input
              type="number"
              min={1}
              max={100}
              value={backendState.simSteps}
              onChange={(e) => actions.setSimSteps(Number(e.target.value))}
              className="w-20 px-3 py-2.5 border border-neutral-200 rounded-xl text-center text-sm bg-white"
            />
            <div className="text-sm text-neutral-600">
              推荐 {backendState.simulationStatus.recommended_steps || backendState.simSteps} 步 / 步长{' '}
              {backendState.simulationStatus.tick_seconds || 300} 秒
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.3fr)_420px] gap-6">
        <div className="bg-white rounded-2xl p-6 border border-neutral-200 shadow-sm min-h-[640px]">
          <div className="flex items-center justify-between mb-5">
            <div>
              <div className="text-lg font-semibold text-neutral-900">世界图谱</div>
              <div className="text-sm text-neutral-500 mt-1">
                当前使用后端图谱；如果图谱尚未返回，则回退到前端场景结构。
              </div>
            </div>
            <button
              onClick={actions.refreshGraphPanel}
              disabled={!backendState.projectId || backendState.busyAction === 'refreshGraph'}
              className="px-3 py-2 bg-white text-neutral-900 rounded-xl border border-neutral-200 hover:bg-neutral-100 disabled:opacity-50 flex items-center gap-2"
            >
              <RefreshCcw className="w-4 h-4" />
              刷新图谱
            </button>
          </div>
          <div className="h-[540px]">
            <KnowledgeGraph
              data={data}
              graphData={backendState.graphData}
              graphStatus={backendState.graphStatus}
              onRefresh={actions.refreshGraphPanel}
              refreshDisabled={!backendState.projectId || backendState.busyAction === 'refreshGraph'}
            />
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-white rounded-2xl p-6 border border-neutral-200 shadow-sm">
            <div className="text-sm uppercase tracking-[0.18em] text-neutral-400 mb-4">世界摘要</div>
            <div className="text-sm text-neutral-700 whitespace-pre-wrap">
              {snapshot?.build_summary || '尚未生成世界摘要。'}
            </div>
          </div>

          <div className="bg-white rounded-2xl p-6 border border-neutral-200 shadow-sm">
            <div className="text-sm uppercase tracking-[0.18em] text-neutral-400 mb-4">热点话题</div>
            {hotTopics.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {hotTopics.map((topic) => (
                  <span
                    key={topic}
                    className="px-3 py-1.5 rounded-full bg-neutral-100 text-sm text-neutral-700"
                  >
                    {topic}
                  </span>
                ))}
              </div>
            ) : (
              <div className="text-sm text-neutral-500">暂无热点配置。</div>
            )}
          </div>

          <div className="bg-white rounded-2xl p-6 border border-neutral-200 shadow-sm">
            <div className="text-sm uppercase tracking-[0.18em] text-neutral-400 mb-4">最新事件</div>
            {recentEvents.length > 0 ? (
              <div className="space-y-3">
                {recentEvents.map((event) => (
                  <button
                    type="button"
                    key={event.id}
                    onClick={() => setSelectedEventId(event.id)}
                    className={`w-full text-left rounded-xl border p-4 transition-colors ${
                      selectedEvent?.id === event.id
                        ? 'border-black bg-neutral-50'
                        : 'border-neutral-200 hover:bg-neutral-50'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-neutral-900">{event.title}</div>
                      <div className="text-xs text-neutral-400">Tick {event.tick}</div>
                    </div>
                    <div className="text-xs text-neutral-500 mt-1">{event.event_type}</div>
                    <div className="text-sm text-neutral-600 mt-2 line-clamp-3">{event.description}</div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="text-sm text-neutral-500">尚未开始仿真，暂时没有运行事件。</div>
            )}
          </div>

          <div className="bg-white rounded-2xl p-6 border border-neutral-200 shadow-sm">
            <div className="text-sm uppercase tracking-[0.18em] text-neutral-400 mb-4">事件详情</div>
            {selectedEvent ? (
              <div className="space-y-3">
                <div>
                  <div className="font-semibold text-neutral-900">{selectedEvent.title}</div>
                  <div className="text-xs text-neutral-500 mt-1">
                    {selectedEvent.event_type} · Tick {selectedEvent.tick}
                  </div>
                </div>
                <div className="text-sm text-neutral-700 whitespace-pre-wrap">
                  {selectedEvent.description}
                </div>
                {selectedEvent.participants?.length ? (
                  <div className="flex flex-wrap gap-2">
                    {selectedEvent.participants.map((participant: string) => (
                      <span
                        key={`${selectedEvent.id}-${participant}`}
                        className="px-2.5 py-1 rounded-full bg-neutral-100 text-xs text-neutral-700"
                      >
                        {participant}
                      </span>
                    ))}
                  </div>
                ) : null}
                <button
                  type="button"
                  onClick={() => actions.goToPage('world-state')}
                  className="w-full px-4 py-3 rounded-xl bg-white border border-neutral-200 text-left hover:bg-neutral-50"
                >
                  在世界状态链中查看完整上下文
                </button>
              </div>
            ) : (
              <div className="text-sm text-neutral-500">点击左侧事件后，这里会显示详情。</div>
            )}
          </div>

          <div className="bg-white rounded-2xl p-6 border border-neutral-200 shadow-sm">
            <div className="text-sm uppercase tracking-[0.18em] text-neutral-400 mb-4">快捷跳转</div>
            <div className="grid gap-3">
              <button
                onClick={() => actions.goToPage('world-state')}
                className="w-full px-4 py-3 rounded-xl bg-white border border-neutral-200 text-left hover:bg-neutral-50"
              >
                <div className="flex items-center gap-3">
                  <Link2 className="w-4 h-4 text-neutral-500" />
                  <div>
                    <div className="font-medium text-neutral-900">打开世界状态链</div>
                    <div className="text-sm text-neutral-500 mt-1">查看完整时间链与分支推演。</div>
                  </div>
                </div>
              </button>
              <button
                onClick={() => actions.goToPage('agent-interaction')}
                className="w-full px-4 py-3 rounded-xl bg-white border border-neutral-200 text-left hover:bg-neutral-50"
              >
                <div className="flex items-center gap-3">
                  <Network className="w-4 h-4 text-neutral-500" />
                  <div>
                    <div className="font-medium text-neutral-900">打开 Agent 交互</div>
                    <div className="text-sm text-neutral-500 mt-1">采访、问卷和世界观察都在这里。</div>
                  </div>
                </div>
              </button>
              <button
                onClick={() => actions.goToPage('report')}
                className="w-full px-4 py-3 rounded-xl bg-white border border-neutral-200 text-left hover:bg-neutral-50"
              >
                <div className="flex items-center gap-3">
                  <FileText className="w-4 h-4 text-neutral-500" />
                  <div>
                    <div className="font-medium text-neutral-900">打开报告页</div>
                    <div className="text-sm text-neutral-500 mt-1">查看结构化报告与导出入口。</div>
                  </div>
                </div>
              </button>
            </div>
          </div>

          {backendState.error ? (
            <div className="rounded-2xl bg-red-50 border border-red-100 text-red-700 px-4 py-3 text-sm">
              {backendState.error}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
