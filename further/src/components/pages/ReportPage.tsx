import { useEffect } from 'react';
import { Download, FileText, Loader2, MessageCircle, RefreshCcw } from 'lucide-react';
import type { ReportData } from '../../lib/api';

function downloadText(filename: string, content: string, mime = 'text/plain;charset=utf-8') {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function exportMarkdown(report: ReportData | null) {
  if (!report) return;
  downloadText(`${report.title || 'report'}.md`, report.markdown || '');
}

function exportJson(report: ReportData | null) {
  if (!report) return;
  downloadText(
    `${report.title || 'report'}.json`,
    JSON.stringify(report, null, 2),
    'application/json;charset=utf-8',
  );
}

export default function ReportPage({ backendState, actions }: any) {
  const report = backendState.report;
  const isLoadingReport = backendState.busyAction === 'loadReport';
  const isLoadingLatest = backendState.busyAction === 'loadLatestReport';

  useEffect(() => {
    if (!report && backendState.projectId && !isLoadingReport && !isLoadingLatest) {
      actions.loadLatestReport();
    }
  }, [report, backendState.projectId, isLoadingReport, isLoadingLatest, actions]);

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight text-neutral-900">报告详情</h2>
          <p className="text-neutral-500 mt-2 text-lg">
            第一阶段先把报告从旧的“最终预测”步骤中抽离，单独做成阅读与导出页面。
          </p>
        </div>
        <div className="flex flex-wrap gap-3 justify-end">
          <button
            onClick={actions.loadLatestReport}
            disabled={isLoadingLatest || !backendState.projectId}
            className="px-4 py-2.5 bg-white text-neutral-900 rounded-xl font-medium hover:bg-neutral-100 border border-neutral-200 disabled:opacity-50 flex items-center gap-2"
          >
            {isLoadingLatest ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCcw className="w-4 h-4" />}
            {isLoadingLatest ? '读取中...' : '读取最新报告'}
          </button>
          <button
            onClick={actions.loadReport}
            disabled={isLoadingReport || !backendState.projectId}
            className="px-4 py-2.5 bg-black text-white rounded-xl font-medium hover:bg-neutral-800 disabled:opacity-50 flex items-center gap-2"
          >
            {isLoadingReport ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCcw className="w-4 h-4" />}
            {isLoadingReport ? '生成中...' : report ? '重新生成报告' : '生成报告'}
          </button>
          <button
            onClick={() => exportMarkdown(report)}
            disabled={!report}
            className="px-4 py-2.5 bg-white text-neutral-900 rounded-xl font-medium hover:bg-neutral-100 border border-neutral-200 disabled:opacity-50 flex items-center gap-2"
          >
            <Download className="w-4 h-4" />
            导出 Markdown
          </button>
          <button
            onClick={() => exportJson(report)}
            disabled={!report}
            className="px-4 py-2.5 bg-white text-neutral-900 rounded-xl font-medium hover:bg-neutral-100 border border-neutral-200 disabled:opacity-50 flex items-center gap-2"
          >
            <Download className="w-4 h-4" />
            导出 JSON
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-2xl p-5 border border-neutral-200 shadow-sm">
          <div className="text-sm text-neutral-500">当前世界</div>
          <div className="text-sm font-medium text-neutral-900 mt-2 break-all">
            {backendState.projectId || '尚未创建'}
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 border border-neutral-200 shadow-sm">
          <div className="text-sm text-neutral-500">报告状态</div>
          <div className="text-lg font-semibold text-neutral-900 mt-2">
            {report ? '已生成' : '未生成'}
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 border border-neutral-200 shadow-sm">
          <div className="text-sm text-neutral-500">章节数</div>
          <div className="text-2xl font-semibold text-neutral-900 mt-2">
            {report?.sections?.length || 0}
          </div>
        </div>
        <div className="bg-white rounded-2xl p-5 border border-neutral-200 shadow-sm">
          <div className="text-sm text-neutral-500">报告时间</div>
          <div className="text-sm font-medium text-neutral-900 mt-2">
            {report?.created_at ? new Date(report.created_at).toLocaleString('zh-CN') : '未记录'}
          </div>
        </div>
        <button
          onClick={() => actions.goToPage('agent-interaction')}
          className="bg-white rounded-2xl p-5 border border-neutral-200 shadow-sm text-left hover:bg-neutral-50"
        >
          <div className="flex items-center gap-3 text-sm text-neutral-500 mb-3">
            <MessageCircle className="w-4 h-4" />
            深度交互
          </div>
          <div className="text-lg font-semibold text-neutral-900">打开 Agent 交互</div>
        </button>
      </div>

      {report ? (
        <div className="grid grid-cols-1 xl:grid-cols-[260px_minmax(0,1fr)] gap-6">
          <div className="bg-white rounded-2xl p-5 border border-neutral-200 shadow-sm h-fit xl:sticky xl:top-4">
            <div className="text-xs uppercase tracking-[0.18em] text-neutral-400 mb-4">目录</div>
            <div className="space-y-2">
              <div className="rounded-xl bg-neutral-50 border border-neutral-200 px-3 py-3">
                <div className="font-medium text-neutral-900">{report.title}</div>
              </div>
              {report.sections.map((section: any, index: number) => (
                <a
                  key={section.title}
                  href={`#report-section-${index}`}
                  className="block rounded-xl border border-neutral-200 px-3 py-3 text-sm text-neutral-700 hover:bg-neutral-50"
                >
                  {section.title}
                </a>
              ))}
            </div>
          </div>

          <div className="bg-white rounded-2xl p-8 border border-neutral-200 shadow-sm">
              <div className="rounded-2xl bg-neutral-50 border border-neutral-200 p-5 mb-6">
              <div className="text-sm uppercase tracking-[0.18em] text-neutral-400 mb-2">报告标题</div>
              <h3 className="text-2xl font-semibold text-neutral-900">{report.title}</h3>
              <div className="text-sm text-neutral-500 mt-2">
                类型：{report.report_type || 'prediction'}
                {report.focus ? ` · Focus: ${report.focus}` : ''}
              </div>
            </div>

            <div className="space-y-6">
              {report.sections.map((section: any, index: number) => (
                <section
                  key={section.title}
                  id={`report-section-${index}`}
                  className="rounded-2xl border border-neutral-200 bg-neutral-50 p-5"
                >
                  <div className="text-lg font-semibold text-neutral-900 mb-3">{section.title}</div>
                  <div className="text-sm text-neutral-700 whitespace-pre-wrap leading-7">
                    {section.content}
                  </div>
                </section>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="bg-white rounded-2xl p-12 border border-neutral-200 shadow-sm text-center">
          <div className="w-16 h-16 rounded-full bg-neutral-50 border border-neutral-200 flex items-center justify-center mx-auto mb-4">
            <FileText className="w-7 h-7 text-neutral-400" />
          </div>
          <div className="text-xl font-semibold text-neutral-900">还没有报告</div>
          <div className="text-neutral-500 mt-2 max-w-xl mx-auto">
            请先在世界总览或本页面生成报告。第一阶段先提供阅读和 Markdown/JSON 导出，PDF 放到后续阶段。
          </div>
        </div>
      )}

      {backendState.error ? (
        <div className="rounded-2xl bg-red-50 border border-red-100 text-red-700 px-4 py-3 text-sm">
          {backendState.error}
        </div>
      ) : null}
    </div>
  );
}
