import { Bell, BellOff, CheckCircle2, TriangleAlert } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { useToast } from '@/components/ui/use-toast';
import { usePlatform } from '@/platform/PlatformContext';
import type { NotificationPermissionState } from '@/platform/types';
import { useNotificationStore } from '@/stores/notificationStore';

function getPermissionLabel(permission: NotificationPermissionState, supported: boolean): string {
  if (!supported) {
    return 'Not supported';
  }
  if (permission === 'granted') {
    return 'Granted';
  }
  if (permission === 'denied') {
    return 'Blocked';
  }
  return 'Not requested';
}

export function NotificationsSettings() {
  const platform = usePlatform();
  const { toast } = useToast();
  const systemAlertsEnabled = useNotificationStore((state) => state.systemAlertsEnabled);
  const notifyOnCompletion = useNotificationStore((state) => state.notifyOnCompletion);
  const notifyOnError = useNotificationStore((state) => state.notifyOnError);
  const setSystemAlertsEnabled = useNotificationStore((state) => state.setSystemAlertsEnabled);
  const setNotifyOnCompletion = useNotificationStore((state) => state.setNotifyOnCompletion);
  const setNotifyOnError = useNotificationStore((state) => state.setNotifyOnError);

  const supported = platform.notifications.isSupported();
  const [permission, setPermission] = useState<NotificationPermissionState>(
    platform.notifications.getPermission(),
  );
  const [requesting, setRequesting] = useState(false);

  const permissionLabel = useMemo(
    () => getPermissionLabel(permission, supported),
    [permission, supported],
  );

  const requestPermission = async () => {
    if (!supported) return;
    try {
      setRequesting(true);
      const result = await platform.notifications.requestPermission();
      setPermission(result);
      if (result === 'granted') {
        toast({
          title: 'Notifications enabled',
          description: 'System alerts are now allowed by your browser/system.',
        });
      } else {
        toast({
          title: 'Permission not granted',
          description: 'System alerts will use in-app toasts as fallback.',
        });
      }
    } catch (error) {
      toast({
        title: 'Permission request failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      });
    } finally {
      setRequesting(false);
    }
  };

  const handleToggleSystemAlerts = async (checked: boolean) => {
    setSystemAlertsEnabled(checked);
    if (checked && supported && permission !== 'granted') {
      await requestPermission();
    }
  };

  const handleTestAlert = async () => {
    if (!systemAlertsEnabled) {
      toast({
        title: 'System alerts are disabled',
        description: 'Enable alerts first to test notifications.',
      });
      return;
    }

    if (!supported) {
      toast({
        title: 'Notifications unsupported',
        description: 'This runtime does not support system notifications. Toast fallback is active.',
      });
      return;
    }

    try {
      if (permission !== 'granted') {
        await requestPermission();
        if (platform.notifications.getPermission() !== 'granted') {
          return;
        }
      }
      await platform.notifications.send('voicebox test alert', {
        body: 'Backend status and job alerts are active.',
        tag: 'voicebox:test-alert',
      });
      toast({
        title: 'Test alert sent',
        description: 'If you did not see it, verify OS/browser notification settings.',
      });
    } catch (error) {
      toast({
        title: 'Test alert failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      });
    } finally {
      setPermission(platform.notifications.getPermission());
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {systemAlertsEnabled ? <Bell className="h-4 w-4" /> : <BellOff className="h-4 w-4" />}
          Notifications
        </CardTitle>
        <CardDescription>Get completion/error alerts for long-running tasks.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm font-medium">System alerts</div>
            <div className="text-xs text-muted-foreground">
              Permission: <span className="font-medium">{permissionLabel}</span>
            </div>
          </div>
          <Checkbox
            checked={systemAlertsEnabled}
            onCheckedChange={(checked) => void handleToggleSystemAlerts(!!checked)}
          />
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <label className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm">
            <span className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              Notify on completion
            </span>
            <Checkbox
              checked={notifyOnCompletion}
              onCheckedChange={(checked) => setNotifyOnCompletion(!!checked)}
            />
          </label>
          <label className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm">
            <span className="flex items-center gap-2">
              <TriangleAlert className="h-4 w-4 text-destructive" />
              Notify on error
            </span>
            <Checkbox
              checked={notifyOnError}
              onCheckedChange={(checked) => setNotifyOnError(!!checked)}
            />
          </label>
        </div>

        {!supported && (
          <div className="text-xs text-muted-foreground">
            Your environment does not support system notifications. In-app toast fallback remains
            active.
          </div>
        )}

        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => void requestPermission()}
            disabled={!supported || requesting}
          >
            {requesting ? 'Requesting...' : 'Request Permission'}
          </Button>
          <Button type="button" variant="outline" onClick={() => void handleTestAlert()}>
            Test alert
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
