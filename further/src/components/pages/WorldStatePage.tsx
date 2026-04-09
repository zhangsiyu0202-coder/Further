import { Link2 } from 'lucide-react';
import WorldStateChain from '../WorldStateChain';

export default function WorldStatePage({ backendState, actions }: any) {
  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight text-neutral-900">世界状态链</h2>
          <p className="text-neutral-500 mt-2 text-lg">
            单独查看世界从初始化到当前状态的完整演化过程，并从任意节点继续分支推演。
          </p>
        </div>
        <div className="w-12 h-12 rounded-2xl bg-black text-white flex items-center justify-center shrink-0">
          <Link2 className="w-5 h-5" />
        </div>
      </div>

      <WorldStateChain
        projectId={backendState.projectId}
        snapshot={backendState.worldSnapshot}
        timeline={backendState.worldTimeline}
        tickSeconds={backendState.simulationStatus.tick_seconds}
        continuationSteps={backendState.simSteps}
        busy={backendState.busyAction === 'branchTimelineIntervention'}
        onBranchTimeline={actions.branchFromTimeline}
      />

      {backendState.error ? (
        <div className="rounded-2xl bg-red-50 border border-red-100 text-red-700 px-4 py-3 text-sm">
          {backendState.error}
        </div>
      ) : null}
    </div>
  );
}
