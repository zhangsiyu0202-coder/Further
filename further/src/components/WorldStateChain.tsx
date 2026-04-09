import { useMemo, useState } from 'react';
import { Clock3, Filter, Link2, Radar, Sparkles } from 'lucide-react';
import type { WorldSnapshot, WorldTimelineEvent } from '../lib/api';

function formatClock(iso?: string) {
  if (!iso) return '未记录';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatVirtualOffset(tick: number, tickSeconds?: number) {
  const seconds = tick * (tickSeconds || 300);
  if (seconds < 3600) return `T+${Math.max(1, Math.round(seconds / 60))}m`;
  if (seconds < 86400) return `T+${Math.round(seconds / 3600)}h`;
  return `T+${Math.round(seconds / 86400)}d`;
}

function eventTone(eventType: string) {
  if (eventType === 'simulation_context' || eventType === 'narrative_setup') {
    return 'bg-amber-50 border-amber-200 text-amber-800';
  }
  if (eventType === 'system_topic') {
    return 'bg-sky-50 border-sky-200 text-sky-800';
  }
  if (eventType === 'agent_action') {
    return 'bg-emerald-50 border-emerald-200 text-emerald-800';
  }
  if (eventType === 'intervention') {
    return 'bg-rose-50 border-rose-200 text-rose-800';
  }
  return 'bg-neutral-50 border-neutral-200 text-neutral-700';
}

function groupEvents(events: WorldTimelineEvent[]) {
  const grouped = new Map<number, WorldTimelineEvent[]>();
  [...events]
    .sort((a, b) => {
      if (a.tick !== b.tick) return a.tick - b.tick;
      return new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime();
    })
    .forEach((event) => {
      if (!grouped.has(event.tick)) grouped.set(event.tick, []);
      grouped.get(event.tick)?.push(event);
    });
  return Array.from(grouped.entries()).map(([tick, tickEvents]) => ({ tick, events: tickEvents }));
}

export default function WorldStateChain({
  projectId,
  snapshot,
  timeline,
  tickSeconds,
  continuationSteps,
  busy,
  onBranchTimeline,
}: {
  projectId?: string | null;
  snapshot: WorldSnapshot | null;
  timeline: WorldTimelineEvent[];
  tickSeconds?: number;
  continuationSteps?: number;
  busy?: boolean;
  onBranchTimeline?: (anchorTick: number, command: string) => Promise<void> | void;
}) {
  if (!snapshot) {
    return (
      <div className="bg-white rounded-2xl p-6 shadow-sm border border-neutral-200">
        <div className="text-sm text-neutral-500">世界状态链</div>
        <div className="text-sm text-neutral-400 mt-3">创建世界后，这里会显示初始化链和演化过程。</div>
      </div>
    );
  }

  const globals = snapshot.global_variables || [];
  const timelineSource = timeline.length > 0 ? timeline : snapshot.timeline || [];
  const [eventFilter, setEventFilter] = useState<string>('all');
  const [selectedEventId, setSelectedEventId] = useState<string>('');
  const [branchCommand, setBranchCommand] = useState('');
  const [branchError, setBranchError] = useState('');
  const eventMap = useMemo(
    () => new Map(timelineSource.map((event) => [event.id, event])),
    [timelineSource],
  );
  const availableTypes = Array.from(new Set(timelineSource.map((event) => event.event_type))).sort();
  const filteredTimeline = useMemo(
    () =>
      eventFilter === 'all'
        ? timelineSource
        : timelineSource.filter((event) => event.event_type === eventFilter),
    [eventFilter, timelineSource],
  );
  const timelineGroups = groupEvents(filteredTimeline);
  const initEvents = timelineGroups.find((group) => group.tick === 0)?.events || [];
  const runtimeGroups = timelineGroups.filter((group) => group.tick > 0);
  const selectedEvent = eventMap.get(selectedEventId) || null;
  const parentEvent = selectedEvent?.parent_event_id
    ? eventMap.get(selectedEvent.parent_event_id) || null
    : null;
  const simulationGoal = globals.find((item) => item.name === 'simulation_goal')?.value;
  const narrativeDirection = globals.find((item) => item.name === 'narrative_direction')?.value;
  const timeConfig = globals.find((item) => item.name === 'time_config')?.value as
    | { horizon_days?: number; recommended_steps?: number; tick_seconds?: number }
    | undefined;
  const eventConfig = globals.find((item) => item.name === 'event_config')?.value as
    | { hot_topics?: string[] }
    | undefined;

  const handleBranch = async () => {
    if (!selectedEvent || !onBranchTimeline || !branchCommand.trim()) {
      return;
    }
    setBranchError('');
    try {
      await onBranchTimeline(selectedEvent.tick, branchCommand.trim());
      setBranchCommand('');
    } catch (error) {
      setBranchError(error instanceof Error ? error.message : '插入干预失败');
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-2xl p-6 shadow-sm border border-neutral-200">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-2xl bg-neutral-900 text-white flex items-center justify-center">
            <Link2 className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-neutral-900">WorldState 演化链</h3>
            <p className="text-sm text-neutral-500">从初始化到当前状态，按时间链查看虚拟世界如何演化。</p>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-2xl p-6 shadow-sm border border-neutral-200">
        <div className="flex items-center gap-2 text-neutral-900 font-semibold mb-4">
          <Sparkles className="w-4 h-4" />
          链头：World Init
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-5">
          <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4">
            <div className="text-xs uppercase tracking-[0.18em] text-neutral-400">Simulation Goal</div>
            <div className="text-sm text-neutral-800 mt-2 whitespace-pre-wrap">{String(simulationGoal || '未设置')}</div>
          </div>
          <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4">
            <div className="text-xs uppercase tracking-[0.18em] text-neutral-400">Narrative Direction</div>
            <div className="text-sm text-neutral-800 mt-2 whitespace-pre-wrap">{String(narrativeDirection || '未设置')}</div>
          </div>
          <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4">
            <div className="text-xs uppercase tracking-[0.18em] text-neutral-400">Time Config</div>
            <div className="text-sm text-neutral-800 mt-2 space-y-1">
              <div>范围: {timeConfig?.horizon_days ? `${timeConfig.horizon_days} 天` : '未设置'}</div>
              <div>建议步数: {timeConfig?.recommended_steps || '未设置'}</div>
              <div>步长: {timeConfig?.tick_seconds || tickSeconds || 300} 秒</div>
            </div>
          </div>
        </div>
        <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4">
          <div className="text-xs uppercase tracking-[0.18em] text-neutral-400">Build Summary</div>
          <div className="text-sm text-neutral-700 mt-2 whitespace-pre-wrap">{snapshot.build_summary || '暂无摘要'}</div>
        </div>
        {initEvents.length > 0 ? (
          <div className="mt-5 space-y-3">
            {initEvents.map((event) => (
              <div key={event.id} className="relative pl-8">
                <div className="absolute left-2 top-2.5 h-full w-px bg-neutral-200" />
                <div className="absolute left-0 top-1.5 w-4 h-4 rounded-full bg-black" />
                <div className="rounded-2xl border border-neutral-200 bg-white p-4">
                  <div className="flex flex-wrap items-center gap-2 mb-2">
                    <span className={`px-2.5 py-1 rounded-full text-xs font-medium border ${eventTone(event.event_type)}`}>
                      {event.event_type}
                    </span>
                    <span className="text-xs text-neutral-400">{formatClock(event.created_at)}</span>
                  </div>
                  <div className="font-medium text-neutral-900">{event.title}</div>
                  <div className="text-sm text-neutral-600 mt-1 whitespace-pre-wrap">{event.description}</div>
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <div className="bg-white rounded-2xl p-6 shadow-sm border border-neutral-200">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div className="flex items-center gap-2 text-neutral-900 font-semibold">
            <Clock3 className="w-4 h-4" />
            演化链
          </div>
          <div className="flex items-start gap-2 flex-wrap justify-end">
            <div className="flex items-center gap-2 text-xs text-neutral-400 uppercase tracking-[0.18em]">
              <Filter className="w-3.5 h-3.5" />
              事件筛选
            </div>
            <button
              onClick={() => setEventFilter('all')}
              className={`px-2.5 py-1 rounded-full border text-xs ${
                eventFilter === 'all'
                  ? 'bg-black text-white border-black'
                  : 'bg-white text-neutral-600 border-neutral-200'
              }`}
            >
              全部
            </button>
            {availableTypes.map((type) => (
              <button
                key={type}
                onClick={() => setEventFilter(type)}
                className={`px-2.5 py-1 rounded-full border text-xs ${
                  eventFilter === type
                    ? 'bg-black text-white border-black'
                    : 'bg-white text-neutral-600 border-neutral-200'
                }`}
              >
                {type}
              </button>
            ))}
          </div>
        </div>
        {runtimeGroups.length > 0 ? (
          <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px] gap-6">
            <div className="space-y-6">
            {runtimeGroups.map((group) => (
              <div key={group.tick} className="rounded-2xl border border-neutral-200 overflow-hidden">
                <div className="bg-neutral-50 border-b border-neutral-200 px-4 py-3 flex flex-wrap items-center gap-3">
                  <div className="font-semibold text-neutral-900">Tick {group.tick}</div>
                  <div className="text-sm text-neutral-500">{formatVirtualOffset(group.tick, tickSeconds || timeConfig?.tick_seconds)}</div>
                  <div className="text-xs text-neutral-400">
                    {group.events.length} 条事件
                  </div>
                </div>
                <div className="p-4 space-y-4">
                  {group.events.map((event, index) => (
                    <div key={event.id} className="relative pl-8">
                      {index < group.events.length - 1 ? (
                        <div className="absolute left-2 top-3 h-[calc(100%+12px)] w-px bg-neutral-200" />
                      ) : null}
                      <div className="absolute left-0 top-1.5 w-4 h-4 rounded-full bg-neutral-900" />
                      <button
                        type="button"
                        onClick={() => setSelectedEventId(event.id)}
                        className={`w-full text-left rounded-2xl border p-4 transition-colors ${
                          selectedEventId === event.id
                            ? 'border-black bg-neutral-50'
                            : 'border-neutral-200 bg-white hover:bg-neutral-50'
                        }`}
                      >
                        <div className="flex flex-wrap items-center gap-2 mb-2">
                          <span className={`px-2.5 py-1 rounded-full text-xs font-medium border ${eventTone(event.event_type)}`}>
                            {event.event_type}
                          </span>
                          <span className="text-xs text-neutral-400">{formatVirtualOffset(event.tick, tickSeconds || timeConfig?.tick_seconds)}</span>
                          <span className="text-xs text-neutral-400">{formatClock(event.created_at)}</span>
                          {event.created_by ? (
                            <span className="text-xs text-neutral-400">来源: {event.created_by}</span>
                          ) : null}
                        </div>
                        <div className="font-medium text-neutral-900">{event.title}</div>
                        <div className="text-sm text-neutral-600 mt-1 whitespace-pre-wrap">{event.description}</div>
                        {event.parent_event_id ? (
                          <div className="mt-3 text-xs text-neutral-500">
                            上游事件: {eventMap.get(event.parent_event_id)?.title || event.parent_event_id}
                          </div>
                        ) : null}
                        {event.participants && event.participants.length > 0 ? (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {event.participants.map((participant) => (
                              <span
                                key={`${event.id}-${participant}`}
                                className="px-2.5 py-1 rounded-full bg-neutral-100 text-neutral-600 text-xs"
                              >
                                {participant}
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ))}
            </div>
            <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4 h-fit sticky top-4">
              <div className="text-xs uppercase tracking-[0.18em] text-neutral-400 mb-3">事件详情</div>
              {selectedEvent ? (
                <div className="space-y-4">
                  <div>
                    <div className="text-lg font-semibold text-neutral-900">{selectedEvent.title}</div>
                    <div className="text-sm text-neutral-500 mt-1">{selectedEvent.event_type}</div>
                  </div>
                  <div className="text-sm text-neutral-700 whitespace-pre-wrap">{selectedEvent.description}</div>
                  <div className="space-y-2 text-sm text-neutral-600">
                    <div>Tick: {selectedEvent.tick}</div>
                    <div>虚拟时间: {formatVirtualOffset(selectedEvent.tick, tickSeconds || timeConfig?.tick_seconds)}</div>
                    <div>真实时间: {formatClock(selectedEvent.created_at)}</div>
                    <div>来源模块: {selectedEvent.source_module || '未标注'}</div>
                    <div>来源实体: {selectedEvent.source_entity_id || '未标注'}</div>
                    <div>创建方式: {selectedEvent.created_by || '未标注'}</div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-[0.18em] text-neutral-400 mb-2">触发原因</div>
                    <div className="text-sm text-neutral-700 whitespace-pre-wrap">
                      {selectedEvent.trigger_reason || '当前事件还没有显式触发原因。'}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-[0.18em] text-neutral-400 mb-2">上游事件</div>
                    {parentEvent ? (
                      <div className="rounded-xl border border-neutral-200 bg-white p-3">
                        <div className="font-medium text-neutral-900">{parentEvent.title}</div>
                        <div className="text-xs text-neutral-500 mt-1">{parentEvent.event_type}</div>
                        <div className="text-sm text-neutral-600 mt-2 whitespace-pre-wrap">{parentEvent.description}</div>
                      </div>
                    ) : (
                      <div className="text-sm text-neutral-500">当前事件没有显式上游事件。</div>
                    )}
                  </div>
                  <div className="rounded-2xl border border-neutral-200 bg-white p-4 space-y-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.18em] text-neutral-400 mb-2">Timeline Intervention</div>
                      <div className="text-sm text-neutral-700">
                        从当前节点 `Tick {selectedEvent.tick}` 派生一条新的推演分支，并继续运行 {continuationSteps || 5} 步。
                      </div>
                    </div>
                    <textarea
                      value={branchCommand}
                      onChange={(e) => setBranchCommand(e.target.value)}
                      placeholder="输入自然语言干预指令，例如：要求主流媒体在该节点后对住房议题转为负面报道"
                      className="w-full min-h-[104px] resize-y rounded-2xl border border-neutral-200 px-3 py-3 text-sm text-neutral-800 focus:outline-none focus:ring-2 focus:ring-black/10"
                    />
                    {branchError ? (
                      <div className="text-sm text-rose-700">{branchError}</div>
                    ) : null}
                    <button
                      type="button"
                      onClick={handleBranch}
                      disabled={!projectId || !branchCommand.trim() || !!busy}
                      className="w-full rounded-2xl bg-black px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-neutral-800 disabled:opacity-50"
                    >
                      {busy ? '正在派生新推演...' : '从该节点插入干预并继续推演'}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-neutral-500">点击左侧链节点后，这里会显示事件详情与上游关联。</div>
              )}
            </div>
          </div>
        ) : (
          <div className="text-sm text-neutral-500">尚未开始仿真，链条还没有进入运行阶段。</div>
        )}
      </div>

      <div className="bg-white rounded-2xl p-6 shadow-sm border border-neutral-200">
        <div className="flex items-center gap-2 text-neutral-900 font-semibold mb-4">
          <Radar className="w-4 h-4" />
          链尾：Current World State
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-5">
          <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4">
            <div className="text-xs uppercase tracking-[0.18em] text-neutral-400">Current Tick</div>
            <div className="text-2xl font-semibold text-neutral-900 mt-2">{snapshot.current_tick}</div>
          </div>
          <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4">
            <div className="text-xs uppercase tracking-[0.18em] text-neutral-400">Hot Topics</div>
            <div className="text-sm text-neutral-800 mt-2">
              {eventConfig?.hot_topics?.length ? eventConfig.hot_topics.join(' / ') : '暂无'}
            </div>
          </div>
          <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4">
            <div className="text-xs uppercase tracking-[0.18em] text-neutral-400">World Size</div>
            <div className="text-sm text-neutral-800 mt-2 space-y-1">
              <div>实体: {snapshot.entities.length}</div>
              <div>关系: {snapshot.relations.length}</div>
              <div>人格: {snapshot.personas.length}</div>
            </div>
          </div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4">
            <div className="text-xs uppercase tracking-[0.18em] text-neutral-400 mb-3">Global Variables</div>
            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {globals.length > 0 ? (
                globals.map((item) => (
                  <div key={item.name} className="rounded-xl bg-white border border-neutral-200 p-3">
                    <div className="font-medium text-neutral-900 text-sm">{item.name}</div>
                    <div className="text-xs text-neutral-500 mt-1 whitespace-pre-wrap break-words">
                      {typeof item.value === 'object'
                        ? JSON.stringify(item.value, null, 2)
                        : String(item.value)}
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-sm text-neutral-500">暂无全局变量。</div>
              )}
            </div>
          </div>
          <div className="rounded-2xl border border-neutral-200 bg-neutral-50 p-4">
            <div className="text-xs uppercase tracking-[0.18em] text-neutral-400 mb-3">Entities</div>
            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {snapshot.entities.slice(0, 20).map((entity) => (
                <div key={entity.id} className="rounded-xl bg-white border border-neutral-200 p-3">
                  <div className="font-medium text-neutral-900 text-sm">{entity.name}</div>
                  <div className="text-xs text-neutral-500 mt-1">{entity.entity_type || 'other'}</div>
                  {entity.description ? (
                    <div className="text-xs text-neutral-600 mt-2 whitespace-pre-wrap">{entity.description}</div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
