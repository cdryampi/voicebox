import { CheckCircle2, Loader2, XCircle } from 'lucide-react';
import { useCallback, useEffect, useRef } from 'react';
import { Progress } from '@/components/ui/progress';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import type { ModelProgress } from '@/lib/api/types';
import { useServerStore } from '@/stores/serverStore';

interface UseModelDownloadToastOptions {
  modelName: string;
  displayName: string;
  enabled?: boolean;
  onComplete?: () => void;
  onError?: () => void;
}

/**
 * Hook to show and update a toast notification with model download progress.
 * Uses authenticated polling so it works in remote deployments behind ngrok.
 */
export function useModelDownloadToast({
  modelName,
  displayName,
  enabled = false,
  onComplete,
  onError,
}: UseModelDownloadToastOptions) {
  const { toast } = useToast();
  const serverUrl = useServerStore((state) => state.serverUrl);
  const toastIdRef = useRef<string | null>(null);
  // biome-ignore lint: Using any for toast update ref to handle complex toast types
  const toastUpdateRef = useRef<any>(null);
  const pollIntervalRef = useRef<number | null>(null);
  const failedPollsRef = useRef<number>(0);
  const finishedRef = useRef<boolean>(false);

  const formatBytes = useCallback((bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / k ** i).toFixed(1)} ${sizes[i]}`;
  }, []);

  const clearPolling = useCallback(() => {
    if (pollIntervalRef.current !== null) {
      window.clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  const finishWithError = useCallback(() => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    clearPolling();

    if (toastIdRef.current && toastUpdateRef.current) {
      toastUpdateRef.current({
        title: displayName,
        description: 'Failed to track download progress',
        variant: 'destructive',
        duration: 5000,
      });
    }

    if (onError) {
      onError();
    }
  }, [clearPolling, displayName, onError]);

  const applyProgressUpdate = useCallback(
    (progress: ModelProgress) => {
      if (!toastIdRef.current || !toastUpdateRef.current || finishedRef.current) {
        return;
      }

      const progressPercent = progress.total > 0 ? progress.progress : 0;
      const progressText =
        progress.total > 0
          ? `${formatBytes(progress.current)} / ${formatBytes(progress.total)} (${progress.progress.toFixed(1)}%)`
          : '';

      let statusIcon: JSX.Element | null = null;
      let statusText = 'Processing...';

      switch (progress.status) {
        case 'complete':
          statusIcon = <CheckCircle2 className="h-4 w-4 text-green-500" />;
          statusText = 'Download complete';
          break;
        case 'error':
          statusIcon = <XCircle className="h-4 w-4 text-destructive" />;
          statusText = `Error: ${progress.error || 'Unknown error'}`;
          break;
        case 'downloading':
          statusIcon = <Loader2 className="h-4 w-4 animate-spin" />;
          statusText = progress.filename || 'Downloading...';
          break;
        case 'extracting':
          statusIcon = <Loader2 className="h-4 w-4 animate-spin" />;
          statusText = 'Extracting...';
          break;
      }

      toastUpdateRef.current({
        title: (
          <div className="flex items-center gap-2">
            {statusIcon}
            <span>{displayName}</span>
          </div>
        ),
        description: (
          <div className="space-y-2">
            <div className="text-sm">{statusText}</div>
            {progress.total > 0 && (
              <>
                <Progress value={progressPercent} className="h-2" />
                <div className="text-xs text-muted-foreground">{progressText}</div>
              </>
            )}
          </div>
        ),
        duration: progress.status === 'complete' ? 5000 : Infinity,
        variant: progress.status === 'error' ? 'destructive' : 'default',
      });

      const isComplete = progress.status === 'complete' || progress.progress >= 100;
      const isError = progress.status === 'error';
      if (!isComplete && !isError) {
        return;
      }

      finishedRef.current = true;
      clearPolling();

      if (isComplete && toastUpdateRef.current) {
        toastUpdateRef.current({
          title: (
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-green-500" />
              <span>{displayName}</span>
            </div>
          ),
          description: 'Download complete',
          duration: 3000,
        });
      }

      if (isComplete && onComplete) {
        onComplete();
      } else if (isError && onError) {
        onError();
      }
    },
    [clearPolling, displayName, formatBytes, onComplete, onError],
  );

  useEffect(() => {
    if (!enabled || !serverUrl || !modelName) {
      return;
    }

    // Create initial toast
    const toastResult = toast({
      title: displayName,
      description: (
        <div className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>Connecting to download...</span>
        </div>
      ),
      duration: Infinity, // Don't auto-dismiss, we'll handle it manually
    });
    toastIdRef.current = toastResult.id;
    toastUpdateRef.current = toastResult.update;
    failedPollsRef.current = 0;
    finishedRef.current = false;

    const pollProgress = async () => {
      if (finishedRef.current) return;
      try {
        const progress = await apiClient.getModelProgressSnapshot(modelName);
        if (progress) {
          failedPollsRef.current = 0;
          applyProgressUpdate(progress);
          return;
        }

        // Snapshot may be null at start/end; infer completion from model status.
        const modelStatus = await apiClient.getModelStatus();
        const model = modelStatus.models.find((entry) => entry.model_name === modelName);
        if (model?.downloaded || model?.loaded) {
          applyProgressUpdate({
            model_name: modelName,
            current: 1,
            total: 1,
            progress: 100,
            status: 'complete',
            filename: undefined,
            timestamp: new Date().toISOString(),
          });
        } else if (model?.downloading) {
          applyProgressUpdate({
            model_name: modelName,
            current: 0,
            total: 0,
            progress: 0,
            status: 'downloading',
            filename: 'Downloading...',
            timestamp: new Date().toISOString(),
          });
        }
      } catch {
        failedPollsRef.current += 1;
        if (failedPollsRef.current >= 5) {
          finishWithError();
        }
      }
    };

    void pollProgress();
    pollIntervalRef.current = window.setInterval(() => {
      void pollProgress();
    }, 1500);

    // Cleanup on unmount or when disabled
    return () => {
      clearPolling();
    };
  }, [
    enabled,
    serverUrl,
    modelName,
    displayName,
    toast,
    applyProgressUpdate,
    clearPolling,
    finishWithError,
  ]);

  return {
    isTracking: enabled && pollIntervalRef.current !== null,
  };
}
