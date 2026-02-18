import { useCallback } from 'react';
import { useToast } from '@/components/ui/use-toast';
import { buildNotificationTag, canEmitNotification } from '@/lib/notifications/notificationCenter';
import { usePlatform } from '@/platform/PlatformContext';
import { useNotificationStore } from '@/stores/notificationStore';

type NotificationKind = 'completion' | 'error' | 'info';

interface NotifyOptions {
  title: string;
  body?: string;
  tag?: string;
  kind?: NotificationKind;
  fallbackToToast?: boolean;
}

export function useNotifier() {
  const platform = usePlatform();
  const { toast } = useToast();
  const systemAlertsEnabled = useNotificationStore((state) => state.systemAlertsEnabled);
  const notifyOnCompletion = useNotificationStore((state) => state.notifyOnCompletion);
  const notifyOnError = useNotificationStore((state) => state.notifyOnError);

  const notify = useCallback(
    async ({
      title,
      body,
      tag,
      kind = 'info',
      fallbackToToast = true,
    }: NotifyOptions): Promise<void> => {
      const effectiveTag = tag || buildNotificationTag(kind, title, body);
      if (!canEmitNotification(effectiveTag)) {
        return;
      }

      if (kind === 'completion' && !notifyOnCompletion) {
        return;
      }
      if (kind === 'error' && !notifyOnError) {
        return;
      }

      const supportsSystem = platform.notifications.isSupported();
      const canTrySystem = systemAlertsEnabled && supportsSystem;
      let deliveredSystem = false;

      if (canTrySystem && platform.notifications.getPermission() === 'granted') {
        try {
          await platform.notifications.send(title, { body, tag: effectiveTag });
          deliveredSystem = true;
        } catch {
          deliveredSystem = false;
        }
      }

      if (!deliveredSystem && fallbackToToast) {
        toast({
          title,
          description: body,
          variant: kind === 'error' ? 'destructive' : 'default',
        });
      }
    },
    [
      notifyOnCompletion,
      notifyOnError,
      platform.notifications,
      systemAlertsEnabled,
      toast,
    ],
  );

  return {
    notify,
  };
}

