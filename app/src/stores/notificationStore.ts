import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface NotificationStoreState {
  systemAlertsEnabled: boolean;
  notifyOnCompletion: boolean;
  notifyOnError: boolean;
  notifyOnStart: boolean;
  setSystemAlertsEnabled: (enabled: boolean) => void;
  setNotifyOnCompletion: (enabled: boolean) => void;
  setNotifyOnError: (enabled: boolean) => void;
  setNotifyOnStart: (enabled: boolean) => void;
}

export const useNotificationStore = create<NotificationStoreState>()(
  persist(
    (set) => ({
      systemAlertsEnabled: true,
      notifyOnCompletion: true,
      notifyOnError: true,
      notifyOnStart: false,
      setSystemAlertsEnabled: (enabled) => set({ systemAlertsEnabled: enabled }),
      setNotifyOnCompletion: (enabled) => set({ notifyOnCompletion: enabled }),
      setNotifyOnError: (enabled) => set({ notifyOnError: enabled }),
      setNotifyOnStart: (enabled) => set({ notifyOnStart: enabled }),
    }),
    {
      name: 'voicebox-notifications',
    },
  ),
);

