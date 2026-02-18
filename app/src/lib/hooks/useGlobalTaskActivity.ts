import { useCallback, useEffect, useRef } from 'react';
import { apiClient } from '@/lib/api/client';
import type {
  ActiveDownloadTask,
  ActiveGenerationTask,
  ActiveStoryRenderTask,
} from '@/lib/api/types';
import { useGenerationStore } from '@/stores/generationStore';
import type { GlobalTaskTerminalEvent } from '@/stores/globalTaskActivityStore';
import { useGlobalTaskActivityStore } from '@/stores/globalTaskActivityStore';

const ACTIVE_POLL_INTERVAL = 2000;
const IDLE_POLL_INTERVAL = 8000;
const HIDDEN_POLL_INTERVAL = 30000;
const HEALTH_POLL_INTERVAL = 30000;

function buildTaskKey(kind: 'download' | 'generation' | 'story_render', id: string): string {
  return `${kind}:${id}`;
}

export function useGlobalTaskActivity() {
  const setSnapshot = useGlobalTaskActivityStore((state) => state.setSnapshot);
  const setConnectionState = useGlobalTaskActivityStore((state) => state.setConnectionState);
  const appendTerminalEvents = useGlobalTaskActivityStore((state) => state.appendTerminalEvents);
  const setHealthErrorStreak = useGlobalTaskActivityStore((state) => state.setHealthErrorStreak);
  const setIsGenerating = useGenerationStore((state) => state.setIsGenerating);
  const setActiveGenerationId = useGenerationStore((state) => state.setActiveGenerationId);

  const previousActiveTasksRef = useRef<Map<string, { message: string; kind: 'download' | 'generation' | 'story_render' }>>(
    new Map(),
  );
  const consecutiveFailuresRef = useRef(0);
  const healthErrorStreakRef = useRef(0);

  const fetchTaskSnapshot = useCallback(async () => {
    try {
      let activeDownloads: ActiveDownloadTask[] = [];
      let activeGenerations: ActiveGenerationTask[] = [];
      let activeStoryRenders: ActiveStoryRenderTask[] = [];
      let hasActiveTasks = false;
      let counts = { downloads: 0, generations: 0, storyRenders: 0 };

      try {
        const summary = await apiClient.getTasksSummary();
        hasActiveTasks = summary.has_active_tasks;
        counts = {
          downloads: summary.downloads_active,
          generations: summary.generations_active,
          storyRenders: summary.story_renders_active,
        };
      } catch (error) {
        const status = (error as { status?: number })?.status;
        if (status !== 404) {
          throw error;
        }
        const legacy = await apiClient.getActiveTasks();
        activeDownloads = legacy.downloads;
        activeGenerations = legacy.generations;
        activeStoryRenders = legacy.story_renders ?? [];
        hasActiveTasks = !!(
          activeDownloads.length ||
          activeGenerations.length ||
          activeStoryRenders.length
        );
        counts = {
          downloads: activeDownloads.length,
          generations: activeGenerations.length,
          storyRenders: activeStoryRenders.length,
        };
      }

      if (hasActiveTasks && (!activeDownloads.length && !activeGenerations.length && !activeStoryRenders.length)) {
        const detailed = await apiClient.getActiveTasks();
        activeDownloads = detailed.downloads;
        activeGenerations = detailed.generations;
        activeStoryRenders = detailed.story_renders ?? [];
      }

      const currentActive = new Map<string, { message: string; kind: 'download' | 'generation' | 'story_render' }>();
      for (const download of activeDownloads) {
        currentActive.set(buildTaskKey('download', download.model_name), {
          message: download.model_name,
          kind: 'download',
        });
      }
      for (const generation of activeGenerations) {
        currentActive.set(buildTaskKey('generation', generation.task_id), {
          message: generation.text_preview || generation.task_id,
          kind: 'generation',
        });
      }
      for (const render of activeStoryRenders) {
        currentActive.set(buildTaskKey('story_render', render.job_id), {
          message: `Story job ${render.job_id}`,
          kind: 'story_render',
        });
      }

      const terminalEvents: GlobalTaskTerminalEvent[] = [];
      for (const [taskKey, previousTask] of previousActiveTasksRef.current.entries()) {
        if (currentActive.has(taskKey)) {
          continue;
        }
        terminalEvents.push({
          id: taskKey,
          kind: previousTask.kind,
          state: 'completed',
          message: previousTask.message,
          createdAt: Date.now(),
        });
      }
      previousActiveTasksRef.current = currentActive;

      if (terminalEvents.length) {
        appendTerminalEvents(terminalEvents);
      }

      setSnapshot({
        hasActiveTasks:
          hasActiveTasks ||
          !!(activeDownloads.length || activeGenerations.length || activeStoryRenders.length),
        activeDownloads,
        activeGenerations,
        activeStoryRenders,
        activeCounts: counts,
      });

      if (activeGenerations.length > 0) {
        setIsGenerating(true);
        setActiveGenerationId(activeGenerations[0].task_id);
      } else if (useGenerationStore.getState().activeGenerationId) {
        setIsGenerating(false);
        setActiveGenerationId(null);
      }

      consecutiveFailuresRef.current = 0;
      setConnectionState('connected');
      return true;
    } catch {
      consecutiveFailuresRef.current += 1;
      const state = consecutiveFailuresRef.current >= 3 ? 'disconnected' : 'degraded';
      setConnectionState(state);
      return false;
    }
  }, [
    appendTerminalEvents,
    setActiveGenerationId,
    setConnectionState,
    setIsGenerating,
    setSnapshot,
  ]);

  const pollHealth = useCallback(async () => {
    try {
      await apiClient.getHealth();
      healthErrorStreakRef.current = 0;
      setHealthErrorStreak(0);
      if (consecutiveFailuresRef.current === 0) {
        setConnectionState('connected');
      }
    } catch {
      healthErrorStreakRef.current += 1;
      setHealthErrorStreak(healthErrorStreakRef.current);
      if (healthErrorStreakRef.current >= 3) {
        setConnectionState('disconnected');
      } else if (consecutiveFailuresRef.current === 0) {
        setConnectionState('degraded');
      }
    }
  }, [setConnectionState, setHealthErrorStreak]);

  useEffect(() => {
    let timeoutId: number | null = null;
    let cancelled = false;

    const scheduleNext = (delayMs: number) => {
      if (cancelled) return;
      timeoutId = window.setTimeout(async () => {
        const ok = await fetchTaskSnapshot();
        const visibility = document.visibilityState;
        const hasActiveTasks = useGlobalTaskActivityStore.getState().hasActiveTasks;
        const baseInterval =
          visibility === 'hidden'
            ? HIDDEN_POLL_INTERVAL
            : hasActiveTasks
              ? ACTIVE_POLL_INTERVAL
              : IDLE_POLL_INTERVAL;
        const backoff =
          !ok && consecutiveFailuresRef.current >= 3
            ? Math.min(30000, baseInterval * consecutiveFailuresRef.current)
            : baseInterval;
        scheduleNext(backoff);
      }, delayMs);
    };

    scheduleNext(0);

    return () => {
      cancelled = true;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [fetchTaskSnapshot]);

  useEffect(() => {
    void pollHealth();
    const intervalId = window.setInterval(() => {
      void pollHealth();
    }, HEALTH_POLL_INTERVAL);
    return () => {
      window.clearInterval(intervalId);
    };
  }, [pollHealth]);
}

