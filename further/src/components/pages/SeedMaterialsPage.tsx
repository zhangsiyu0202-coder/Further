import { Database, FileText, Plus, Server, Target, Trash2, Workflow } from 'lucide-react';

export default function SeedMaterialsPage({ data, updateData, backendState, actions }: any) {
  const isSyncing = backendState.busyAction === 'syncProject';
  const seedMaterials = data.seedMaterials || [];

  const updateMaterial = (id: string, patch: Record<string, string>) => {
    updateData({
      seedMaterials: seedMaterials.map((material: any) =>
        material.id === id ? { ...material, ...patch } : material,
      ),
    });
  };

  const addMaterial = () => {
    updateData({
      seedMaterials: [
        ...seedMaterials,
        {
          id: `seed-${Date.now()}`,
          title: `材料 ${seedMaterials.length + 1}`,
          kind: 'text',
          content: '',
          source: '',
          notes: '',
        },
      ],
    });
  };

  const removeMaterial = (id: string) => {
    if (seedMaterials.length === 1) {
      updateData({
        seedMaterials: [{ ...seedMaterials[0], content: '', source: '', notes: '' }],
      });
      return;
    }

    updateData({
      seedMaterials: seedMaterials.filter((material: any) => material.id !== id),
    });
  };

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-semibold tracking-tight text-neutral-900">种子材料</h2>
        <p className="text-neutral-500 mt-2 text-lg">
          第一阶段先保留文本录入方式，后续再把这里升级为真正的材料上传与管理页面。
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-neutral-200">
          <div className="flex items-center gap-3 text-sm text-neutral-500 mb-3">
            <Server className="w-4 h-4" />
            API 状态
          </div>
          <div className="text-lg font-semibold text-neutral-900">
            {backendState.apiReady ? '已连接' : '未连接'}
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-neutral-200">
          <div className="flex items-center gap-3 text-sm text-neutral-500 mb-3">
            <Database className="w-4 h-4" />
            当前世界
          </div>
          <div className="text-sm font-medium text-neutral-900 break-all">
            {backendState.projectId || '尚未创建'}
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 shadow-sm border border-neutral-200">
          <div className="flex items-center gap-3 text-sm text-neutral-500 mb-3">
            <Workflow className="w-4 h-4" />
            后端状态
          </div>
          <div className="text-lg font-semibold text-neutral-900">
            {backendState.graphStatus?.status || backendState.projectStatus}
          </div>
        </div>
      </div>

      <div className="bg-white rounded-2xl p-8 shadow-sm border border-neutral-200 space-y-6">
        <div className="space-y-3">
          <label className="block text-sm font-medium text-neutral-700">预测需求</label>
          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
              <Target className="h-5 w-5 text-neutral-400" />
            </div>
            <input
              type="text"
              value={data.objective || ''}
              onChange={(e) => updateData({ objective: e.target.value })}
              className="block w-full pl-11 pr-4 py-3 bg-neutral-50 border border-neutral-200 rounded-xl text-neutral-900 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-black/5 focus:border-black transition-all"
              placeholder="例如：未来 12 个月 AI 应用创业融资温度如何变化"
            />
          </div>
        </div>

        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <label className="block text-sm font-medium text-neutral-700">种子材料列表</label>
            <button
              type="button"
              onClick={addMaterial}
              className="px-4 py-2 bg-white text-neutral-900 rounded-xl border border-neutral-200 hover:bg-neutral-100 flex items-center gap-2"
            >
              <Plus className="w-4 h-4" />
              添加材料
            </button>
          </div>

          <div className="space-y-4">
            {seedMaterials.map((material: any, index: number) => (
              <div key={material.id} className="rounded-2xl border border-neutral-200 bg-neutral-50 p-5 space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-2xl bg-white border border-neutral-200 flex items-center justify-center text-neutral-700">
                      <FileText className="w-5 h-5" />
                    </div>
                    <div>
                      <div className="font-medium text-neutral-900">材料 {index + 1}</div>
                      <div className="text-sm text-neutral-500">第二阶段开始支持多条文本材料管理。</div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeMaterial(material.id)}
                    className="p-2 text-neutral-400 hover:text-red-600 hover:bg-white rounded-lg transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <input
                    type="text"
                    value={material.title || ''}
                    onChange={(e) => updateMaterial(material.id, { title: e.target.value })}
                    className="block w-full px-4 py-3 bg-white border border-neutral-200 rounded-xl text-neutral-900 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-black/5 focus:border-black transition-all"
                    placeholder="材料标题"
                  />
                  <input
                    type="text"
                    value={material.source || ''}
                    onChange={(e) => updateMaterial(material.id, { source: e.target.value })}
                    className="block w-full px-4 py-3 bg-white border border-neutral-200 rounded-xl text-neutral-900 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-black/5 focus:border-black transition-all"
                    placeholder="来源，可选"
                  />
                </div>

                <textarea
                  value={material.content || ''}
                  onChange={(e) => updateMaterial(material.id, { content: e.target.value })}
                  rows={8}
                  className="block w-full p-4 bg-white border border-neutral-200 rounded-xl text-neutral-900 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-black/5 focus:border-black transition-all resize-none"
                  placeholder="输入材料正文"
                />

                <textarea
                  value={material.notes || ''}
                  onChange={(e) => updateMaterial(material.id, { notes: e.target.value })}
                  rows={2}
                  className="block w-full p-4 bg-white border border-neutral-200 rounded-xl text-neutral-900 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-black/5 focus:border-black transition-all resize-none"
                  placeholder="备注，可选"
                />
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-neutral-200 bg-neutral-50 px-5 py-4 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div>
            <div className="text-sm font-medium text-neutral-900">创建后端世界并启动图谱构建</div>
            <div className="text-sm text-neutral-500 mt-1">
              当前输入会作为世界种子提交到后端，预测需求会单独作为 `simulation_goal` 参与 world init。
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              onClick={actions.syncProject}
              disabled={isSyncing}
              className="px-5 py-3 bg-black text-white rounded-xl font-medium hover:bg-neutral-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isSyncing ? '同步中...' : backendState.projectId ? '重新同步并重建图谱' : '创建世界并构图'}
            </button>
            <button
              onClick={() => actions.goToPage('world-overview')}
              disabled={!backendState.projectId}
              className="px-5 py-3 bg-white text-neutral-900 rounded-xl font-medium hover:bg-neutral-100 border border-neutral-200 disabled:opacity-50"
            >
              打开世界总览
            </button>
          </div>
        </div>

        {backendState.currentTask ? (
          <div className="rounded-2xl border border-neutral-200 p-5">
            <div className="flex items-center justify-between text-sm text-neutral-600 mb-3">
              <span>任务进度</span>
              <span>{backendState.currentTask.progress}%</span>
            </div>
            <div className="h-2 rounded-full bg-neutral-100 overflow-hidden">
              <div
                className="h-full bg-black transition-all duration-300"
                style={{ width: `${backendState.currentTask.progress}%` }}
              />
            </div>
            <div className="text-sm text-neutral-500 mt-3">{backendState.currentTask.message}</div>
          </div>
        ) : null}

        {backendState.error ? (
          <div className="rounded-2xl bg-red-50 border border-red-100 text-red-700 px-4 py-3 text-sm">
            {backendState.error}
          </div>
        ) : null}
      </div>
    </div>
  );
}
