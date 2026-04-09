import { useEffect, useRef, useState, Fragment, type KeyboardEvent, type ReactNode, type RefObject } from 'react';
import {
  Send,
  Loader2,
  User,
  Globe,
  ClipboardList,
  Copy,
  Check,
  CheckSquare,
  Square,
  MessageCircle,
} from 'lucide-react';
import type { WorldSnapshot } from '../../lib/api';
import { chatWithAgent, chatWithWorld } from '../../lib/api';

type Tab = 'interview' | 'survey' | 'world';

interface ChatMsg {
  role: 'user' | 'agent' | 'world';
  content: string;
  label?: string;
}

interface SurveyRow {
  entityId: string;
  name: string;
  status: 'idle' | 'loading' | 'done' | 'error';
  answer: string;
}

function Bubble({ msg }: { msg: ChatMsg }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex gap-2 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div
        className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-bold ${
          isUser ? 'bg-black text-white' : 'bg-neutral-200 text-neutral-600'
        }`}
      >
        {isUser ? '你' : msg.label?.[0] ?? (msg.role === 'world' ? '世' : 'A')}
      </div>
      <div
        className={`max-w-[75%] px-3 py-2 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
          isUser
            ? 'bg-black text-white rounded-tr-sm'
            : 'bg-neutral-100 text-neutral-900 rounded-tl-sm'
        }`}
      >
        {msg.label && !isUser ? (
          <div className="text-xs text-neutral-500 mb-1 font-medium">{msg.label}</div>
        ) : null}
        {msg.content}
      </div>
    </div>
  );
}

function TabBtn({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
        active ? 'bg-black text-white' : 'text-neutral-500 hover:bg-neutral-100'
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function ChatInput({
  value,
  onChange,
  onSend,
  busy,
  placeholder,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  busy: boolean;
  placeholder: string;
  disabled?: boolean;
}) {
  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <div className="flex gap-2 items-end border-t border-neutral-100 pt-3">
      <textarea
        rows={2}
        className="flex-1 resize-none px-3 py-2 rounded-xl border border-neutral-200 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-black/10"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKey}
        disabled={disabled || busy}
      />
      <button
        type="button"
        onClick={onSend}
        disabled={disabled || busy || !value.trim()}
        className="p-2.5 bg-black text-white rounded-xl hover:bg-neutral-800 transition-colors disabled:opacity-40"
      >
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
      </button>
    </div>
  );
}

export default function AgentInteractionPage({
  projectId,
  snapshot,
}: {
  projectId: string | null;
  snapshot: WorldSnapshot | null;
}) {
  const [tab, setTab] = useState<Tab>('interview');
  const [ivAgentId, setIvAgentId] = useState('');
  const [ivHistory, setIvHistory] = useState<ChatMsg[]>([]);
  const [ivInput, setIvInput] = useState('');
  const [ivBusy, setIvBusy] = useState(false);
  const ivBottomRef = useRef<HTMLDivElement>(null);
  const [svQuestion, setSvQuestion] = useState('');
  const [svSelected, setSvSelected] = useState<Set<string>>(new Set());
  const [svRows, setSvRows] = useState<SurveyRow[]>([]);
  const [svBusy, setSvBusy] = useState(false);
  const [svCopied, setSvCopied] = useState(false);
  const [wdHistory, setWdHistory] = useState<ChatMsg[]>([]);
  const [wdInput, setWdInput] = useState('');
  const [wdBusy, setWdBusy] = useState(false);
  const wdBottomRef = useRef<HTMLDivElement>(null);
  const entities = snapshot?.entities ?? [];

  useEffect(() => {
    if (entities.length > 0 && !ivAgentId) setIvAgentId(entities[0].id);
  }, [entities, ivAgentId]);

  useEffect(() => {
    setSvSelected(new Set(entities.map((e) => e.id)));
  }, [entities.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const scrollDown = (ref: RefObject<HTMLDivElement | null>) =>
    setTimeout(() => ref.current?.scrollIntoView({ behavior: 'smooth' }), 50);

  const sendInterview = async () => {
    if (!projectId || !ivAgentId || !ivInput.trim() || ivBusy) return;
    const msg = ivInput.trim();
    setIvInput('');
    setIvHistory((h) => [...h, { role: 'user', content: msg }]);
    setIvBusy(true);
    scrollDown(ivBottomRef);
    try {
      const res = await chatWithAgent(projectId, ivAgentId, msg);
      const agentName = entities.find((e) => e.id === ivAgentId)?.name ?? ivAgentId;
      setIvHistory((h) => [
        ...h,
        { role: 'agent', content: res.answer ?? res.error ?? '（无回复）', label: agentName },
      ]);
    } catch (e: unknown) {
      setIvHistory((h) => [
        ...h,
        { role: 'agent', content: `错误: ${e instanceof Error ? e.message : String(e)}`, label: '系统' },
      ]);
    } finally {
      setIvBusy(false);
      scrollDown(ivBottomRef);
    }
  };

  const runSurvey = async () => {
    if (!projectId || !svQuestion.trim() || svSelected.size === 0 || svBusy) return;
    const targets = entities.filter((e) => svSelected.has(e.id));
    const initial: SurveyRow[] = targets.map((e) => ({
      entityId: e.id,
      name: e.name,
      status: 'loading',
      answer: '',
    }));
    setSvRows(initial);
    setSvBusy(true);

    await Promise.all(
      targets.map(async (e) => {
        try {
          const res = await chatWithAgent(projectId, e.id, svQuestion.trim());
          setSvRows((prev) =>
            prev.map((r) =>
              r.entityId === e.id
                ? { ...r, status: 'done', answer: res.answer ?? res.error ?? '（无回复）' }
                : r,
            ),
          );
        } catch (err: unknown) {
          setSvRows((prev) =>
            prev.map((r) =>
              r.entityId === e.id
                ? { ...r, status: 'error', answer: err instanceof Error ? err.message : '错误' }
                : r,
            ),
          );
        }
      }),
    );
    setSvBusy(false);
  };

  const copySurveyResults = () => {
    const lines = svRows.map((r) => `【${r.name}】\n${r.answer}`).join('\n\n');
    navigator.clipboard.writeText(`问题：${svQuestion}\n\n${lines}`);
    setSvCopied(true);
    setTimeout(() => setSvCopied(false), 2000);
  };

  const toggleAll = () => {
    setSvSelected(
      svSelected.size === entities.length ? new Set() : new Set(entities.map((e) => e.id)),
    );
  };

  const toggleOne = (id: string) => {
    setSvSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const sendWorld = async () => {
    if (!projectId || !wdInput.trim() || wdBusy) return;
    const msg = wdInput.trim();
    setWdInput('');
    setWdHistory((h) => [...h, { role: 'user', content: msg }]);
    setWdBusy(true);
    scrollDown(wdBottomRef);
    try {
      const res = await chatWithWorld(projectId, msg);
      setWdHistory((h) => [
        ...h,
        { role: 'world', content: res.answer ?? res.error ?? '（无回复）', label: '世界' },
      ]);
    } catch (e: unknown) {
      setWdHistory((h) => [
        ...h,
        { role: 'world', content: `错误: ${e instanceof Error ? e.message : String(e)}`, label: '系统' },
      ]);
    } finally {
      setWdBusy(false);
      scrollDown(wdBottomRef);
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight text-neutral-900">与 Agent 交互</h2>
          <p className="text-neutral-500 mt-2 text-lg">
            将采访、问卷调查和世界观察拆成独立页面，集中处理交互式探索。
          </p>
        </div>
        <div className="w-12 h-12 rounded-2xl bg-indigo-600 text-white flex items-center justify-center shrink-0">
          <MessageCircle className="w-5 h-5" />
        </div>
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-neutral-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-neutral-100">
          <div className="font-semibold text-neutral-900">交互工作台</div>
          <div className="text-xs text-neutral-500 mt-0.5">采访 · 问卷 · 世界观察</div>
        </div>

        <div className="flex gap-1 px-5 py-3 border-b border-neutral-100">
          <TabBtn
            active={tab === 'interview'}
            onClick={() => setTab('interview')}
            icon={<User className="w-3.5 h-3.5" />}
            label="单 Agent 采访"
          />
          <TabBtn
            active={tab === 'survey'}
            onClick={() => setTab('survey')}
            icon={<ClipboardList className="w-3.5 h-3.5" />}
            label="问卷调查"
          />
          <TabBtn
            active={tab === 'world'}
            onClick={() => setTab('world')}
            icon={<Globe className="w-3.5 h-3.5" />}
            label="世界观察"
          />
        </div>

        {!projectId ? (
          <div className="px-5 py-10 text-sm text-neutral-500">
            请先在工作台创建世界，再进入交互页面。
          </div>
        ) : (
          <div className="min-h-[640px]">
            {tab === 'interview' ? (
              <div className="flex flex-col h-[640px] px-5 py-4 gap-3">
                <select
                  className="w-full px-3 py-2 rounded-xl border border-neutral-200 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-black/10"
                  value={ivAgentId}
                  onChange={(e) => {
                    setIvAgentId(e.target.value);
                    setIvHistory([]);
                  }}
                >
                  {entities.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                      {e.entity_type ? ` (${e.entity_type})` : ''}
                    </option>
                  ))}
                </select>

                <div className="flex-1 overflow-y-auto space-y-3 min-h-0">
                  {ivHistory.length === 0 ? (
                    <div className="text-sm text-neutral-400 text-center py-8">
                      选择 Agent 后输入问题开始采访
                    </div>
                  ) : null}
                  {ivHistory.map((msg, i) => (
                    <Fragment key={i}><Bubble msg={msg} /></Fragment>
                  ))}
                  {ivBusy ? (
                    <div className="flex gap-2 items-center text-sm text-neutral-400">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      等待回复...
                    </div>
                  ) : null}
                  <div ref={ivBottomRef} />
                </div>

                <ChatInput
                  value={ivInput}
                  onChange={setIvInput}
                  onSend={sendInterview}
                  busy={ivBusy}
                  placeholder="输入问题，Shift+Enter 换行，Enter 发送"
                  disabled={!ivAgentId}
                />
              </div>
            ) : null}

            {tab === 'survey' ? (
              <div className="flex flex-col px-5 py-4 gap-3">
                <div>
                  <label className="text-xs text-neutral-500 uppercase tracking-[0.12em] mb-1 block">
                    问卷问题
                  </label>
                  <textarea
                    rows={3}
                    className="w-full resize-none px-3 py-2 rounded-xl border border-neutral-200 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-black/10"
                    placeholder="请描述你对当前局势的看法..."
                    value={svQuestion}
                    onChange={(e) => setSvQuestion(e.target.value)}
                  />
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs text-neutral-500 uppercase tracking-[0.12em]">
                      发送对象 ({svSelected.size}/{entities.length})
                    </label>
                    <button
                      type="button"
                      onClick={toggleAll}
                      className="text-xs text-neutral-500 hover:text-black transition-colors flex items-center gap-1"
                    >
                      {svSelected.size === entities.length ? (
                        <CheckSquare className="w-3.5 h-3.5" />
                      ) : (
                        <Square className="w-3.5 h-3.5" />
                      )}
                      {svSelected.size === entities.length ? '取消全选' : '全选'}
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto p-1">
                    {entities.map((e) => (
                      <button
                        key={e.id}
                        type="button"
                        onClick={() => toggleOne(e.id)}
                        className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors border ${
                          svSelected.has(e.id)
                            ? 'bg-black text-white border-black'
                            : 'bg-white text-neutral-600 border-neutral-200 hover:border-neutral-400'
                        }`}
                      >
                        {e.name}
                      </button>
                    ))}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={runSurvey}
                  disabled={!svQuestion.trim() || svSelected.size === 0 || svBusy}
                  className="w-full py-2.5 bg-black text-white rounded-xl text-sm font-medium hover:bg-neutral-800 transition-colors disabled:opacity-40 flex items-center justify-center gap-2"
                >
                  {svBusy ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      问卷进行中...
                    </>
                  ) : (
                    '运行问卷'
                  )}
                </button>

                {svRows.length > 0 ? (
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <div className="text-xs text-neutral-500 uppercase tracking-[0.12em]">结果</div>
                      <button
                        type="button"
                        onClick={copySurveyResults}
                        className="flex items-center gap-1 text-xs text-neutral-500 hover:text-black transition-colors"
                      >
                        {svCopied ? (
                          <Check className="w-3.5 h-3.5 text-emerald-500" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                        {svCopied ? '已复制' : '复制全部'}
                      </button>
                    </div>
                    <div className="space-y-2 pb-2">
                      {svRows.map((row) => (
                        <div
                          key={row.entityId}
                          className="rounded-xl border border-neutral-200 px-3 py-2.5"
                        >
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-sm font-medium text-neutral-900">{row.name}</span>
                            {row.status === 'loading' ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin text-neutral-400" />
                            ) : null}
                            {row.status === 'done' ? (
                              <Check className="w-3.5 h-3.5 text-emerald-500" />
                            ) : null}
                            {row.status === 'error' ? (
                              <span className="text-xs text-red-500">错误</span>
                            ) : null}
                          </div>
                          {row.status !== 'loading' && row.answer ? (
                            <p className="text-sm text-neutral-600 leading-relaxed whitespace-pre-wrap">
                              {row.answer}
                            </p>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}

            {tab === 'world' ? (
              <div className="flex flex-col h-[640px] px-5 py-4 gap-3">
                <div className="flex-1 overflow-y-auto space-y-3 min-h-0">
                  {wdHistory.length === 0 ? (
                    <div className="text-sm text-neutral-400 text-center py-8">
                      向世界提问，查看整体局势、关键矛盾和潜在走向。
                    </div>
                  ) : null}
                  {wdHistory.map((msg, i) => (
                    <Fragment key={i}><Bubble msg={msg} /></Fragment>
                  ))}
                  {wdBusy ? (
                    <div className="flex gap-2 items-center text-sm text-neutral-400">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      世界思考中...
                    </div>
                  ) : null}
                  <div ref={wdBottomRef} />
                </div>

                <ChatInput
                  value={wdInput}
                  onChange={setWdInput}
                  onSend={sendWorld}
                  busy={wdBusy}
                  placeholder="例：当前最大风险是什么？Enter 发送"
                />
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
