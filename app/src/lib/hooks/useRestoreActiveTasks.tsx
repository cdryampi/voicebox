import { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from '@/lib/api/client';
import type { ActiveDownloadTask } from '@/lib/api/types';
import { useGenerationStore } from '@/stores/generationStore';

// Polling interval in milliseconds
const POLL_INTERVAL = 2000;

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

  // Track which downloads we've seen to detect new ones
  const seenDownloadsRef = useRef<Set<string>>(new Set());

  const fetchActiveTasks = useCallback(async () => {
    try {
      const tasks = await apiClient.getActiveTasks();
      consecutiveFailuresRef.current = 0;

      // Update generation state
      if (tasks.generations.length > 0) {
        setIsGenerating(true);
        setActiveGenerationId(tasks.generations[0].task_id);
      } else {
        // Only clear if we were tracking a generation
        const currentId = useGenerationStore.getState().activeGenerationId;
        if (currentId) {
          setIsGenerating(false);
          setActiveGenerationId(null);
        }
      }

      // Update active downloads
      // Keep track of all active downloads (including new ones)
      const currentDownloadNames = new Set(tasks.downloads.map((d) => d.model_name));

      // Remove completed downloads from our seen set
      for (const name of seenDownloadsRef.current) {
        if (!currentDownloadNames.has(name)) {
          seenDownloadsRef.current.delete(name);
        }
      }

      // Add new downloads to seen set
      for (const download of tasks.downloads) {
        seenDownloadsRef.current.add(download.model_name);
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
        const backoff =
          !ok && consecutiveFailuresRef.current >= 3
            ? Math.min(30000, POLL_INTERVAL * consecutiveFailuresRef.current)
            : POLL_INTERVAL;
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
