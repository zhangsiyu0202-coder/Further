import { useState, type ReactNode } from 'react';
import { Zap, FileText, ChevronDown, ChevronUp, CheckCircle, AlertCircle } from 'lucide-react';
import type { WorldSnapshot } from '../lib/api';
import { applyIntervention, generateReport } from '../lib/api';

type FeedbackState = { type: 'success' | 'error'; message: string } | null;

function FieldRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs text-neutral-500 uppercase tracking-[0.15em]">{label}</label>
      {children}
    </div>
  );
}

function inputCls() {
  return 'w-full px-3 py-2 rounded-xl border border-neutral-200 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-black/10';
}

export default function OperatorPanel({
  projectId,
  snapshot,
  onReportLoaded,
}: {
  projectId: string | null;
  snapshot: WorldSnapshot | null;
  onReportLoaded?: (report: { title: string; sections: { title: string; content: string }[] }) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState('');
  const [feedback, setFeedback] = useState<FeedbackState>(null);

  const entities = snapshot?.entities || [];

  // --- policy shock form ---
  const [policyName, setPolicyName] = useState('');
  const [policyDesc, setPolicyDesc] = useState('');
  const [policySeverity, setPolicySeverity] = useState('0.5');
  const [policyReason, setPolicyReason] = useState('');

  // --- opinion shift form ---
  const [opinionTopic, setOpinionTopic] = useState('');
  const [opinionDir, setOpinionDir] = useState<'positive' | 'negative'>('negative');
  const [opinionMag, setOpinionMag] = useState('0.3');
  const [opinionReason, setOpinionReason] = useState('');

  // --- resource change form ---
  const [resEntityId, setResEntityId] = useState('');
  const [resType, setResType] = useState('');
  const [resDelta, setResDelta] = useState('');
  const [resReason, setResReason] = useState('');

  // --- attitude change form ---
  const [attEntityId, setAttEntityId] = useState('');
  const [attTargetId, setAttTargetId] = useState('');
  const [attPolarity, setAttPolarity] = useState<'positive' | 'neutral' | 'negative'>('neutral');
  const [attReason, setAttReason] = useState('');

  // --- set global variable form ---
  const [gvName, setGvName] = useState('');
  const [gvValue, setGvValue] = useState('');
  const [gvDesc, setGvDesc] = useState('');
  const [operatorCommand, setOperatorCommand] = useState('');

  const showFeedback = (type: 'success' | 'error', message: string) => {
    setFeedback({ type, message });
    setTimeout(() => setFeedback(null), 4000);
  };

  const run = async (action: string, fn: () => Promise<unknown>) => {
    if (!projectId) return;
    setBusy(action);
    try {
      await fn();
      showFeedback('success', `${action} 已执行`);
    } catch (e: unknown) {
      showFeedback('error', e instanceof Error ? e.message : String(e));
    } finally {
      setBusy('');
    }
  };

  const handlePolicyShock = () =>
    run('policy_shock', () =>
      applyIntervention(projectId!, 'policy_shock', {
        policy_name: policyName,
        description: policyDesc,
        severity: parseFloat(policySeverity) || 0.5,
      }, policyReason),
    );

  const handleOpinionShift = () =>
    run('opinion_shift', () =>
      applyIntervention(projectId!, 'opinion_shift', {
        topic: opinionTopic,
        direction: opinionDir,
        magnitude: parseFloat(opinionMag) || 0.3,
      }, opinionReason),
    );

  const handleResourceChange = () =>
    run('resource_change', () =>
      applyIntervention(projectId!, 'resource_change', {
        entity_id: resEntityId,
        resource_type: resType,
        delta: parseFloat(resDelta) || 0,
      }, resReason),
    );

  const handleAttitudeChange = () =>
    run('attitude_change', () =>
      applyIntervention(projectId!, 'attitude_change', {
        entity_id: attEntityId,
        target_entity_id: attTargetId,
        new_polarity: attPolarity,
      }, attReason),
    );

  const handleSetGlobalVar = () =>
    run('set_global_variable', () => {
      let val: unknown = gvValue;
      try { val = JSON.parse(gvValue); } catch { /* keep as string */ }
      return applyIntervention(projectId!, 'set_global_variable', {
        variable_name: gvName,
        value: val,
        description: gvDesc,
      });
    });

  const handleGenerateReport = () =>
    run('report', async () => {
      const report = await generateReport(projectId!);
      onReportLoaded?.(report);
    });

  const handleOperatorCommand = () => {
    showFeedback('error', '自然语言操作者命令暂未启用');
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-neutral-200 overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-6 py-4 hover:bg-neutral-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-neutral-900 text-white flex items-center justify-center">
            <Zap className="w-4 h-4" />
          </div>
          <div className="text-left">
            <div className="font-semibold text-neutral-900">操作者控制台</div>
            <div className="text-xs text-neutral-500">干预注入 · 报告生成（仅操作者可用，不影响 agent 工具集）</div>
          </div>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-neutral-400" /> : <ChevronDown className="w-4 h-4 text-neutral-400" />}
      </button>

      {expanded && (
        <div className="border-t border-neutral-100 px-6 py-5 space-y-6">
          {feedback && (
            <div className={`flex items-center gap-2 px-4 py-3 rounded-xl text-sm ${feedback.type === 'success' ? 'bg-emerald-50 text-emerald-700 border border-emerald-100' : 'bg-red-50 text-red-700 border border-red-100'}`}>
              {feedback.type === 'success' ? <CheckCircle className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
              {feedback.message}
            </div>
          )}

          <div className="rounded-2xl border border-neutral-200 p-4 space-y-3 bg-neutral-50">
            <div className="text-sm font-semibold text-neutral-900">自然语言操作者命令</div>
            <div className="text-xs text-neutral-500">
              适合复合操作，例如“先给 A 群体施加 opinion shift，再生成一份 summary report”。
            </div>
            <FieldRow label="Command">
              <textarea
                className={`${inputCls()} min-h-[96px] resize-y`}
                value={operatorCommand}
                onChange={(e) => setOperatorCommand(e.target.value)}
                placeholder="输入自然语言操作者命令"
              />
            </FieldRow>
            <button
              type="button"
              onClick={handleOperatorCommand}
              disabled={!projectId || !operatorCommand.trim()}
              className="w-full py-2 bg-neutral-900 text-white rounded-xl text-sm font-medium hover:bg-neutral-800 transition-colors disabled:opacity-50"
            >
              执行操作者命令
            </button>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Policy Shock */}
            <div className="rounded-2xl border border-neutral-200 p-4 space-y-3">
              <div className="text-sm font-semibold text-neutral-900">注入政策冲击</div>
              <FieldRow label="政策名称">
                <input className={inputCls()} value={policyName} onChange={(e) => setPolicyName(e.target.value)} placeholder="e.g. 新监管法案" />
              </FieldRow>
              <FieldRow label="描述">
                <input className={inputCls()} value={policyDesc} onChange={(e) => setPolicyDesc(e.target.value)} placeholder="政策内容说明" />
              </FieldRow>
              <FieldRow label={`严重程度 (${policySeverity})`}>
                <input type="range" min="0" max="1" step="0.05" value={policySeverity} onChange={(e) => setPolicySeverity(e.target.value)} className="w-full" />
              </FieldRow>
              <FieldRow label="原因（可选）">
                <input className={inputCls()} value={policyReason} onChange={(e) => setPolicyReason(e.target.value)} placeholder="为什么注入" />
              </FieldRow>
              <button
                type="button"
                onClick={handlePolicyShock}
                disabled={!projectId || !policyName || busy === 'policy_shock'}
                className="w-full py-2 bg-black text-white rounded-xl text-sm font-medium hover:bg-neutral-800 transition-colors disabled:opacity-50"
              >
                {busy === 'policy_shock' ? '注入中...' : '注入政策冲击'}
              </button>
            </div>

            {/* Opinion Shift */}
            <div className="rounded-2xl border border-neutral-200 p-4 space-y-3">
              <div className="text-sm font-semibold text-neutral-900">注入舆论偏移</div>
              <FieldRow label="话题">
                <input className={inputCls()} value={opinionTopic} onChange={(e) => setOpinionTopic(e.target.value)} placeholder="e.g. 经济政策" />
              </FieldRow>
              <FieldRow label="方向">
                <select className={inputCls()} value={opinionDir} onChange={(e) => setOpinionDir(e.target.value as 'positive' | 'negative')}>
                  <option value="positive">正向（支持）</option>
                  <option value="negative">负向（反对）</option>
                </select>
              </FieldRow>
              <FieldRow label={`幅度 (${opinionMag})`}>
                <input type="range" min="0" max="1" step="0.05" value={opinionMag} onChange={(e) => setOpinionMag(e.target.value)} className="w-full" />
              </FieldRow>
              <FieldRow label="原因（可选）">
                <input className={inputCls()} value={opinionReason} onChange={(e) => setOpinionReason(e.target.value)} placeholder="为什么注入" />
              </FieldRow>
              <button
                type="button"
                onClick={handleOpinionShift}
                disabled={!projectId || !opinionTopic || busy === 'opinion_shift'}
                className="w-full py-2 bg-black text-white rounded-xl text-sm font-medium hover:bg-neutral-800 transition-colors disabled:opacity-50"
              >
                {busy === 'opinion_shift' ? '注入中...' : '注入舆论偏移'}
              </button>
            </div>

            {/* Resource Change */}
            <div className="rounded-2xl border border-neutral-200 p-4 space-y-3">
              <div className="text-sm font-semibold text-neutral-900">注入资源变化</div>
              <FieldRow label="目标实体">
                <select className={inputCls()} value={resEntityId} onChange={(e) => setResEntityId(e.target.value)}>
                  <option value="">-- 选择实体 --</option>
                  {entities.map((e) => (
                    <option key={e.id} value={e.id}>{e.name}</option>
                  ))}
                </select>
              </FieldRow>
              <FieldRow label="资源类型">
                <input className={inputCls()} value={resType} onChange={(e) => setResType(e.target.value)} placeholder="e.g. funds, reputation" />
              </FieldRow>
              <FieldRow label="变化量（正/负）">
                <input type="number" className={inputCls()} value={resDelta} onChange={(e) => setResDelta(e.target.value)} placeholder="e.g. 100 or -50" />
              </FieldRow>
              <FieldRow label="原因（可选）">
                <input className={inputCls()} value={resReason} onChange={(e) => setResReason(e.target.value)} placeholder="为什么注入" />
              </FieldRow>
              <button
                type="button"
                onClick={handleResourceChange}
                disabled={!projectId || !resEntityId || !resType || !resDelta || busy === 'resource_change'}
                className="w-full py-2 bg-black text-white rounded-xl text-sm font-medium hover:bg-neutral-800 transition-colors disabled:opacity-50"
              >
                {busy === 'resource_change' ? '注入中...' : '注入资源变化'}
              </button>
            </div>

            {/* Attitude Change */}
            <div className="rounded-2xl border border-neutral-200 p-4 space-y-3">
              <div className="text-sm font-semibold text-neutral-900">注入态度改变</div>
              <FieldRow label="主体实体">
                <select className={inputCls()} value={attEntityId} onChange={(e) => setAttEntityId(e.target.value)}>
                  <option value="">-- 选择实体 --</option>
                  {entities.map((e) => (
                    <option key={e.id} value={e.id}>{e.name}</option>
                  ))}
                </select>
              </FieldRow>
              <FieldRow label="目标实体">
                <select className={inputCls()} value={attTargetId} onChange={(e) => setAttTargetId(e.target.value)}>
                  <option value="">-- 选择目标 --</option>
                  {entities.map((e) => (
                    <option key={e.id} value={e.id}>{e.name}</option>
                  ))}
                </select>
              </FieldRow>
              <FieldRow label="新态度极性">
                <select className={inputCls()} value={attPolarity} onChange={(e) => setAttPolarity(e.target.value as 'positive' | 'neutral' | 'negative')}>
                  <option value="positive">正向（支持）</option>
                  <option value="neutral">中立</option>
                  <option value="negative">负向（反对）</option>
                </select>
              </FieldRow>
              <FieldRow label="原因（可选）">
                <input className={inputCls()} value={attReason} onChange={(e) => setAttReason(e.target.value)} placeholder="为什么改变态度" />
              </FieldRow>
              <button
                type="button"
                onClick={handleAttitudeChange}
                disabled={!projectId || !attEntityId || !attTargetId || busy === 'attitude_change'}
                className="w-full py-2 bg-black text-white rounded-xl text-sm font-medium hover:bg-neutral-800 transition-colors disabled:opacity-50"
              >
                {busy === 'attitude_change' ? '注入中...' : '注入态度改变'}
              </button>
            </div>

            {/* Set Global Variable */}
            <div className="rounded-2xl border border-neutral-200 p-4 space-y-3">
              <div className="text-sm font-semibold text-neutral-900">设置全局变量</div>
              <FieldRow label="变量名">
                <input className={inputCls()} value={gvName} onChange={(e) => setGvName(e.target.value)} placeholder="e.g. crisis_level" />
              </FieldRow>
              <FieldRow label="值（支持 JSON）">
                <input className={inputCls()} value={gvValue} onChange={(e) => setGvValue(e.target.value)} placeholder='e.g. "high" or 3 or {"active":true}' />
              </FieldRow>
              <FieldRow label="说明（可选）">
                <input className={inputCls()} value={gvDesc} onChange={(e) => setGvDesc(e.target.value)} placeholder="变量含义" />
              </FieldRow>
              <button
                type="button"
                onClick={handleSetGlobalVar}
                disabled={!projectId || !gvName || !gvValue || busy === 'set_global_variable'}
                className="w-full py-2 bg-black text-white rounded-xl text-sm font-medium hover:bg-neutral-800 transition-colors disabled:opacity-50"
              >
                {busy === 'set_global_variable' ? '设置中...' : '设置全局变量'}
              </button>
            </div>
          </div>

          {/* Report */}
          <div className="rounded-2xl border border-neutral-200 p-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="text-sm font-semibold text-neutral-900 flex items-center gap-2">
                  <FileText className="w-4 h-4" />
                  生成分析报告
                </div>
                <div className="text-xs text-neutral-500 mt-1">基于当前仿真状态生成预测分析报告（prediction 类型）</div>
              </div>
              <button
                type="button"
                onClick={handleGenerateReport}
                disabled={!projectId || busy === 'report'}
                className="shrink-0 px-4 py-2 bg-neutral-100 text-neutral-800 rounded-xl text-sm font-medium hover:bg-neutral-200 transition-colors border border-neutral-200 disabled:opacity-50"
              >
                {busy === 'report' ? '生成中...' : '生成报告'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
