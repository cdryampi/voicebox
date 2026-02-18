import { create } from 'zustand';
import type {
  ActiveDownloadTask,
  ActiveGenerationTask,
  ActiveStoryRenderTask,
  TaskTerminalEvent,
} from '@/lib/api/types';

export type ConnectionState = 'connected' | 'degraded' | 'disconnected';

interface GlobalTaskActivityStore {
  connectionState: ConnectionState;
  healthErrorStreak: number;
  hasActiveTasks: boolean;
  activeDownloads: ActiveDownloadTask[];
  activeGenerations: ActiveGenerationTask[];
  activeStoryRenders: ActiveStoryRenderTask[];
  activeCounts: {
    downloads: number;
    generations: number;
    storyRenders: number;
  };
  modelOperation: {
    busy: boolean;
    kind?: 'download' | 'activate' | 'delete';
    modelName?: string;
    startedAt?: string;
  };
  lastTerminalEvent: TaskTerminalEvent | null;
  terminalEvents: TaskTerminalEvent[];
  lastTerminalEventId: number;
  setSnapshot: (payload: {
    hasActiveTasks: boolean;
    activeDownloads: ActiveDownloadTask[];
    activeGenerations: ActiveGenerationTask[];
    activeStoryRenders: ActiveStoryRenderTask[];
    activeCounts: {
      downloads: number;
      generations: number;
      storyRenders: number;
    };
    modelOperation?: {
      busy: boolean;
      kind?: 'download' | 'activate' | 'delete';
      modelName?: string;
      startedAt?: string;
    };
  }) => void;
  setConnectionState: (connectionState: ConnectionState) => void;
  setHealthErrorStreak: (healthErrorStreak: number) => void;
  appendTerminalEvents: (events: TaskTerminalEvent[]) => void;
}

export const useGlobalTaskActivityStore = create<GlobalTaskActivityStore>((set) => ({
  connectionState: 'connected',
  healthErrorStreak: 0,
  hasActiveTasks: false,
  activeDownloads: [],
  activeGenerations: [],
  activeStoryRenders: [],
  activeCounts: {
    downloads: 0,
    generations: 0,
    storyRenders: 0,
  },
  modelOperation: {
    busy: false,
  },
  lastTerminalEvent: null,
  terminalEvents: [],
  lastTerminalEventId: 0,
  setSnapshot: ({
    hasActiveTasks,
    activeDownloads,
    activeGenerations,
    activeStoryRenders,
    activeCounts,
    modelOperation,
  }) =>
    set({
      hasActiveTasks,
      activeDownloads,
      activeGenerations,
      activeStoryRenders,
      activeCounts,
      modelOperation: modelOperation ?? { busy: false },
    }),
  setConnectionState: (connectionState) => set({ connectionState }),
  setHealthErrorStreak: (healthErrorStreak) => set({ healthErrorStreak }),
  appendTerminalEvents: (events) =>
    set((state) => {
      if (!events.length) {
        return state;
      }
      const byId = new Map<number, TaskTerminalEvent>();
      for (const event of state.terminalEvents) byId.set(event.id, event);
      for (const event of events) byId.set(event.id, event);
      const merged = [...byId.values()].sort((a, b) => a.id - b.id).slice(-30);
      const last = merged[merged.length - 1] ?? null;
      return {
        terminalEvents: merged,
        lastTerminalEvent: last,
        lastTerminalEventId: last?.id ?? state.lastTerminalEventId,
      };
    }),
}));
