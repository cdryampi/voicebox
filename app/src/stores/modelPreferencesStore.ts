import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type TtsModelSize = '1.7B' | '0.6B';
export type WhisperModelSize = 'base' | 'small' | 'medium' | 'large';

interface ModelPreferencesStore {
  defaultTtsModelSize: TtsModelSize;
  setDefaultTtsModelSize: (modelSize: TtsModelSize) => void;
  defaultWhisperModelSize: WhisperModelSize;
  setDefaultWhisperModelSize: (modelSize: WhisperModelSize) => void;
}

export const useModelPreferencesStore = create<ModelPreferencesStore>()(
  persist(
    (set) => ({
      defaultTtsModelSize: '0.6B',
      setDefaultTtsModelSize: (modelSize) => set({ defaultTtsModelSize: modelSize }),
      defaultWhisperModelSize: 'base',
      setDefaultWhisperModelSize: (modelSize) => set({ defaultWhisperModelSize: modelSize }),
    }),
    {
      name: 'voicebox-model-preferences',
    },
  ),
);
