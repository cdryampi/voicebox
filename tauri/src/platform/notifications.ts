import type { NotificationPermissionState, PlatformNotifications } from '@/platform/types';

function isNotificationSupported(): boolean {
  return typeof window !== 'undefined' && 'Notification' in window;
}

function getPermission(): NotificationPermissionState {
  if (!isNotificationSupported()) {
    return 'denied';
  }
  return Notification.permission as NotificationPermissionState;
}

export const tauriNotifications: PlatformNotifications = {
  isSupported(): boolean {
    return isNotificationSupported();
  },
  getPermission(): NotificationPermissionState {
    return getPermission();
  },
  async requestPermission(): Promise<NotificationPermissionState> {
    if (!isNotificationSupported()) {
      return 'denied';
    }
    return (await Notification.requestPermission()) as NotificationPermissionState;
  },
  async send(title: string, options?: { body?: string; tag?: string }): Promise<void> {
    if (!isNotificationSupported()) {
      throw new Error('System notifications are not supported by this runtime.');
    }
    if (Notification.permission !== 'granted') {
      throw new Error('Notification permission is not granted.');
    }
    new Notification(title, {
      body: options?.body,
      tag: options?.tag,
    });
  },
};

