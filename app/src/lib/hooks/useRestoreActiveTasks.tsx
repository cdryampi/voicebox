import { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from '@/lib/api/client';
import type { ActiveDownloadTask, ActiveTasksSummaryResponse } from '@/lib/api/types';
import { useGenerationStore } from '@/stores/generationStore';

const ACTIVE_POLL_INTERVAL = 2000;
const IDLE_POLL_INTERVAL = 8000;
const HIDDEN_POLL_INTERVAL = 30000;

/**
 * Hook to monitor active tasks (downloads and generations).
 * Polls the server periodically to catch downloads triggered from anywhere
 * (transcription, generation, explicit download, etc.).
 *
 * Returns the active downloads so components can render download toasts.
 */
export function useRestoreActiveTasks() {
  const [activeDownloads, setActiveDownloads] = useState<ActiveDownloadTask[]>([]);
  const setIsGenerating = useGenerationStore((state) => state.setIsGenerating);
  const setActiveGenerationId = useGenerationStore((state) => state.setActiveGenerationId);
  const consecutiveFailuresRef = useRef(0);
  const hasActiveTasksRef = useRef(false);

  const fetchActiveTasks = useCallback(async () => {
    try {
      let summary: ActiveTasksSummaryResponse;
      try {
        summary = await apiClient.getTasksSummary();
      } catch (error) {
        const status = (error as { status?: number })?.status;
        if (status !== 404) {
          throw error;
        }
        // Backward compatibility for older backends without /tasks/summary.
        const legacyTasks = await apiClient.getActiveTasks();
        consecutiveFailuresRef.current = 0;
        hasActiveTasksRef.current = !!(legacyTasks.downloads.length || legacyTasks.generations.length);
        if (legacyTasks.generations.length > 0) {
          setIsGenerating(true);
          setActiveGenerationId(legacyTasks.generations[0].task_id);
        } else {
          const currentId = useGenerationStore.getState().activeGenerationId;
          if (currentId) {
            setIsGenerating(false);
            setActiveGenerationId(null);
          }
        }
        setActiveDownloads(legacyTasks.downloads);
        return true;
      }
      consecutiveFailuresRef.current = 0;
      hasActiveTasksRef.current = summary.has_active_tasks;

      if (!summary.has_active_tasks) {
        setActiveDownloads([]);
        const currentId = useGenerationStore.getState().activeGenerationId;
        if (currentId) {
          setIsGenerating(false);
          setActiveGenerationId(null);
        }
        return true;
      }

      const tasks = await apiClient.getActiveTasks();
      if (tasks.generations.length > 0) {
        setIsGenerating(true);
        setActiveGenerationId(tasks.generations[0].task_id);
      } else {
        const currentId = useGenerationStore.getState().activeGenerationId;
        if (currentId) {
          setIsGenerating(false);
          setActiveGenerationId(null);
        }
      }

      setActiveDownloads(tasks.downloads);
      return true;
    } catch (error) {
      // Silently fail - server might be temporarily unavailable
      console.debug('Failed to fetch active tasks:', error);
      consecutiveFailuresRef.current += 1;
      return false;
    }
  }, [setIsGenerating, setActiveGenerationId]);

  useEffect(() => {
    let timeoutId: number | null = null;
    let cancelled = false;

    const scheduleNext = (delayMs: number) => {
      if (cancelled) return;
      timeoutId = window.setTimeout(async () => {
        const ok = await fetchActiveTasks();
        if (!ok && consecutiveFailuresRef.current >= 6) {
          // Connection is probably down (ngrok/session dead). Pause polling to avoid console spam.
          scheduleNext(5 * 60 * 1000);
          return;
        }
        const visibility = document.visibilityState;
        const baseInterval =
          visibility === 'hidden'
            ? HIDDEN_POLL_INTERVAL
            : hasActiveTasksRef.current
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
  }, [fetchActiveTasks]);

  return activeDownloads;
}

/**
 * Map model names to display names for download toasts.
 */
export const MODEL_DISPLAY_NAMES: Record<string, string> = {
  'qwen-tts-1.7B': 'Qwen TTS 1.7B',
  'qwen-tts-0.6B': 'Qwen TTS 0.6B',
  'whisper-base': 'Whisper Base',
  'whisper-small': 'Whisper Small',
  'whisper-medium': 'Whisper Medium',
  'whisper-large': 'Whisper Large',
};
