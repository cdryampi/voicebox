import { useGlobalTaskActivity } from '@/lib/hooks/useGlobalTaskActivity';
import type { ActiveDownloadTask } from '@/lib/api/types';
import { useGlobalTaskActivityStore } from '@/stores/globalTaskActivityStore';

/**
 * Hook to monitor active tasks (downloads and generations).
 * Polls the server periodically to catch downloads triggered from anywhere
 * (transcription, generation, explicit download, etc.).
 *
 * Returns the active downloads so components can render download toasts.
 */
export function useRestoreActiveTasks() {
  useGlobalTaskActivity();
  const activeDownloads = useGlobalTaskActivityStore(
    (state) => state.activeDownloads,
  ) as ActiveDownloadTask[];
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
