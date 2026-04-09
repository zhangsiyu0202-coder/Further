/**
 * useTaskStream — SSE hook that subscribes to a backend task progress stream.
 *
 * Usage:
 *   const { progress, status, message, error } = useTaskStream(taskId, 'world_build');
 *
 * The hook opens an EventSource to /api/v1/tasks/{taskId}/stream and closes it
 * automatically when the task reaches "completed" or "failed".
 * Pass null/undefined as taskId to disable the subscription.
 */

import { useEffect, useRef, useState } from 'react';

export interface TaskStreamState {
  status: string;
  progress: number;
  message: string;
  error: string | null;
  done: boolean;
}

const INITIAL: TaskStreamState = {
  status: 'pending',
  progress: 0,
  message: '',
  error: null,
  done: false,
};

export function useTaskStream(
  taskId: string | null | undefined,
  taskType: 'world_build' | 'graph_build' = 'graph_build',
): TaskStreamState {
  const [state, setState] = useState<TaskStreamState>(INITIAL);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!taskId) {
      setState(INITIAL);
      return;
    }

    setState(INITIAL);
    const url = `/api/v1/tasks/${taskId}/stream?task_type=${taskType}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        setState((prev) => ({
          ...prev,
          status: data.status ?? prev.status,
          progress: typeof data.progress === 'number' ? data.progress : prev.progress,
          message: data.message ?? prev.message,
          error: data.error ?? null,
        }));
      } catch {
        /* ignore parse errors */
      }
    };

    es.addEventListener('done', (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data);
        setState({
          status: data.status ?? 'completed',
          progress: 100,
          message: data.message ?? '',
          error: data.error ?? null,
          done: true,
        });
      } catch {
        setState((prev) => ({ ...prev, done: true }));
      }
      es.close();
    });

    es.addEventListener('error', (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data ?? '{}');
        setState((prev) => ({
          ...prev,
          status: 'failed',
          error: data.message ?? '连接失败',
          done: true,
        }));
      } catch {
        setState((prev) => ({ ...prev, status: 'failed', error: '连接失败', done: true }));
      }
      es.close();
    });

    es.addEventListener('timeout', () => {
      setState((prev) => ({ ...prev, done: true }));
      es.close();
    });

    es.onerror = () => {
      es.close();
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [taskId, taskType]);

  return state;
}
