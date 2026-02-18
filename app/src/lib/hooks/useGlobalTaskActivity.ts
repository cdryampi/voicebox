import { useCallback, useEffect, useRef } from 'react';
import { apiClient } from '@/lib/api/client';
import type {
  ActiveDownloadTask,
  ActiveGenerationTask,
  ActiveStoryRenderTask,
  TaskTerminalEvent,
} from '@/lib/api/types';
import { useGenerationStore } from '@/stores/generationStore';
import { useGlobalTaskActivityStore } from '@/stores/globalTaskActivityStore';

const ACTIVE_POLL_INTERVAL = 2000;
const IDLE_POLL_INTERVAL = 8000;
const HIDDEN_POLL_INTERVAL = 30000;
const HEALTH_POLL_INTERVAL = 30000;

export function useGlobalTaskActivity() {
  const setSnapshot = useGlobalTaskActivityStore((state) => state.setSnapshot);
  const setConnectionState = useGlobalTaskActivityStore((state) => state.setConnectionState);
  const appendTerminalEvents = useGlobalTaskActivityStore((state) => state.appendTerminalEvents);
  const setHealthErrorStreak = useGlobalTaskActivityStore((state) => state.setHealthErrorStreak);
  const setIsGenerating = useGenerationStore((state) => state.setIsGenerating);
  const setActiveGenerationId = useGenerationStore((state) => state.setActiveGenerationId);
  const lastEventIdRef = useRef<number>(useGlobalTaskActivityStore.getState().lastTerminalEventId || 0);
  const consecutiveFailuresRef = useRef(0);
  const healthErrorStreakRef = useRef(0);

  const fetchTaskSnapshot = useCallback(async () => {
    try {
      let activeDownloads: ActiveDownloadTask[] = [];
      let activeGenerations: ActiveGenerationTask[] = [];
      let activeStoryRenders: ActiveStoryRenderTask[] = [];
      let hasActiveTasks = false;
      let counts = { downloads: 0, generations: 0, storyRenders: 0 };
      let summaryModelBusy = false;
      let summaryModelKind: 'download' | 'activate' | 'delete' | undefined;
      let summaryModelName: string | undefined;
      let summaryModelStartedAt: string | undefined;
      let summaryLastTerminalEvent: TaskTerminalEvent | undefined;

      try {
        const summary = await apiClient.getTasksSummary();
        hasActiveTasks = summary.has_active_tasks;
        counts = {
          downloads: summary.downloads_active,
          generations: summary.generations_active,
          storyRenders: summary.story_renders_active,
        };
        summaryModelBusy = summary.model_ops_busy;
        summaryModelKind = summary.model_op_kind;
        summaryModelName = summary.model_op_model_name;
        summaryModelStartedAt = summary.model_op_started_at;
        summaryLastTerminalEvent = summary.last_terminal_event;
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

      if (summaryLastTerminalEvent) {
        appendTerminalEvents([summaryLastTerminalEvent]);
        lastEventIdRef.current = Math.max(lastEventIdRef.current, summaryLastTerminalEvent.id);
      }

      if (hasActiveTasks && (!activeDownloads.length && !activeGenerations.length && !activeStoryRenders.length)) {
        const detailed = await apiClient.getActiveTasks();
        activeDownloads = detailed.downloads;
        activeGenerations = detailed.generations;
        activeStoryRenders = detailed.story_renders ?? [];
      }

      try {
        const eventBatch = await apiClient.getTaskEvents({
          since_id: lastEventIdRef.current || undefined,
          limit: 100,
        });
        const terminalEvents: TaskTerminalEvent[] = eventBatch.events ?? [];
        if (terminalEvents.length > 0) {
          appendTerminalEvents(terminalEvents);
          lastEventIdRef.current = eventBatch.last_id;
        } else if (eventBatch.last_id && eventBatch.last_id > lastEventIdRef.current) {
          lastEventIdRef.current = eventBatch.last_id;
        }
      } catch (error) {
        const status = (error as { status?: number })?.status;
        if (status !== 404) {
          throw error;
        }
      }

      setSnapshot({
        hasActiveTasks:
          hasActiveTasks ||
          !!(activeDownloads.length || activeGenerations.length || activeStoryRenders.length),
        activeDownloads,
        activeGenerations,
        activeStoryRenders,
        activeCounts: counts,
        modelOperation: {
          busy: summaryModelBusy,
          kind: summaryModelKind,
          modelName: summaryModelName,
          startedAt: summaryModelStartedAt,
        },
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
