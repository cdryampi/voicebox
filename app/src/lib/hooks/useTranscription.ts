import { useMutation } from '@tanstack/react-query';
import { apiClient } from '@/lib/api/client';
import type { LanguageCode } from '@/lib/constants/languages';
import { useModelPreferencesStore } from '@/stores/modelPreferencesStore';

export function useTranscription() {
  const defaultWhisperModelSize = useModelPreferencesStore((state) => state.defaultWhisperModelSize);

  return useMutation({
    mutationFn: ({
      file,
      language,
      modelSize,
    }: {
      file: File;
      language?: LanguageCode;
      modelSize?: 'base' | 'small' | 'medium' | 'large';
    }) => apiClient.transcribeAudio(file, language, modelSize ?? defaultWhisperModelSize),
  });
}
