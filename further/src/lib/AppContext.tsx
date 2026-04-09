/**
 * AppContext — 全局共享状态 Context。
 *
 * 将 App.tsx 中的 backendState、predictionData、actions 提取到 Context，
 * 方便深层子组件访问，避免逐层 props 传递。
 */

import { createContext, useContext, type ReactNode } from 'react';
import type {
  GraphData,
  GraphStatus,
  ReportData,
  SimulationAgent,
  SimulationStatus,
  TaskRecord,
  WorldSnapshot,
  WorldTimelineEvent,
} from './api';

// ---------------------------------------------------------------------------
// BackendState shape
// ---------------------------------------------------------------------------

export interface BackendState {
  apiReady: boolean;
  projectId: string;
  projectStatus: string;
  graphStatus: GraphStatus | null;
  graphData: GraphData;
  simulationStatus: SimulationStatus;
  worldSnapshot: WorldSnapshot | null;
  worldTimeline: WorldTimelineEvent[];
  agents: SimulationAgent[];
  report: ReportData | null;
  currentTask: TaskRecord | null;
  busyAction: string;
  simSteps: number;
  activity: string[];
  error: string;
}

// ---------------------------------------------------------------------------
// PredictionData shape
// ---------------------------------------------------------------------------

export interface SeedMaterialItem {
  id: string;
  title: string;
  kind: string;
  content: string;
  source: string;
  notes: string;
}

export interface PredictionData {
  objective: string;
  seedMaterials: SeedMaterialItem[];
}

// ---------------------------------------------------------------------------
// Actions shape
// ---------------------------------------------------------------------------

export interface AppActions {
  syncProject: () => Promise<void>;
  initializeSimulation: () => Promise<void>;
  runSingleStep: () => Promise<void>;
  runMultipleSteps: () => Promise<void>;
  setSimSteps: (n: number) => void;
  loadReport: () => Promise<void>;
  loadLatestReport: () => Promise<void>;
  branchFromTimeline: (anchorTick: number, command: string) => Promise<void>;
  setReport: (report: ReportData) => void;
  refreshGraphPanel: () => Promise<void>;
  refreshWorldOverview: () => Promise<void>;
  goToPage: (page: string) => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface AppContextValue {
  backendState: BackendState;
  predictionData: PredictionData;
  updateData: (data: Partial<PredictionData>) => void;
  actions: AppActions;
}

export const AppContext = createContext<AppContextValue | null>(null);

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useAppContext must be used within AppContext.Provider');
  return ctx;
}

// Re-export for convenience
export type { ReactNode };
