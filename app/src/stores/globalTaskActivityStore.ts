import { create } from 'zustand';
import type {
  ActiveDownloadTask,
  ActiveGenerationTask,
  ActiveStoryRenderTask,
} from '@/lib/api/types';

export type ConnectionState = 'connected' | 'degraded' | 'disconnected';
export type GlobalTaskKind = 'generation' | 'story_render' | 'download';
export type GlobalTaskState = 'running' | 'completed' | 'failed';

export interface GlobalTaskTerminalEvent {
  id: string;
  kind: GlobalTaskKind;
  state: Exclude<GlobalTaskState, 'running'>;
  message: string;
  createdAt: number;
}

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
  lastTerminalEvent: GlobalTaskTerminalEvent | null;
  terminalEvents: GlobalTaskTerminalEvent[];
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
  }) => void;
  setConnectionState: (connectionState: ConnectionState) => void;
  setHealthErrorStreak: (healthErrorStreak: number) => void;
  appendTerminalEvents: (events: GlobalTaskTerminalEvent[]) => void;
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
  lastTerminalEvent: null,
  terminalEvents: [],
  setSnapshot: ({
    hasActiveTasks,
    activeDownloads,
    activeGenerations,
    activeStoryRenders,
    activeCounts,
  }) =>
    set({
      hasActiveTasks,
      activeDownloads,
      activeGenerations,
      activeStoryRenders,
      activeCounts,
    }),
  setConnectionState: (connectionState) => set({ connectionState }),
  setHealthErrorStreak: (healthErrorStreak) => set({ healthErrorStreak }),
  appendTerminalEvents: (events) =>
    set((state) => {
      if (!events.length) {
        return state;
      }
      const merged = [...state.terminalEvents, ...events].slice(-30);
      return {
        terminalEvents: merged,
        lastTerminalEvent: merged[merged.length - 1] ?? null,
      };
    }),
}));

