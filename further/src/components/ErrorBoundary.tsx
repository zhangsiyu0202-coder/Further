/* eslint-disable @typescript-eslint/no-explicit-any */
import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

// Explicit cast helpers to avoid TS language-server false positives caused by
// useDefineForClassFields:false + moduleResolution:bundler + react-jsx transform.
type EB = { state: State; props: Readonly<Props>; setState: (s: Partial<State>) => void };

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    (this as any as EB).state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  render(): ReactNode {
    const self = this as any as EB;
    if (self.state.hasError) {
      if (self.props.fallback) return self.props.fallback;
      return (
        <div className="flex flex-col items-center justify-center h-full p-12 text-center gap-4">
          <div className="text-4xl">⚠️</div>
          <h2 className="text-lg font-semibold text-neutral-800">页面渲染出错</h2>
          <p className="text-sm text-neutral-500 max-w-md">
            {self.state.error?.message || '未知错误'}
          </p>
          <button
            className="mt-2 px-4 py-2 text-sm bg-black text-white rounded-lg hover:bg-neutral-800"
            onClick={() => self.setState({ hasError: false, error: null })}
          >
            重试
          </button>
        </div>
      );
    }
    return self.props.children;
  }
}
