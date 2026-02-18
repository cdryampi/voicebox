import { Loader2, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { apiClient } from '@/lib/api/client';
import type { ModelProgress as ModelProgressType } from '@/lib/api/types';
import { useServerStore } from '@/stores/serverStore';

interface ModelProgressProps {
  modelName: string;
  displayName: string;
  /** Only poll when actively downloading. */
  isDownloading?: boolean;
}

export function ModelProgress({
  modelName,
  displayName,
  isDownloading = false,
}: ModelProgressProps) {
  const [progress, setProgress] = useState<ModelProgressType | null>(null);
  const serverUrl = useServerStore((state) => state.serverUrl);

  useEffect(() => {
    if (!serverUrl || !isDownloading) {
      return;
    }

    let cancelled = false;
    let intervalId: number | null = null;

    const applyProgress = (data: ModelProgressType) => {
      if (cancelled) return;
      setProgress(data);
      if (data.status === 'complete' || data.status === 'error') {
        if (intervalId !== null) {
          window.clearInterval(intervalId);
          intervalId = null;
        }
      }
    };

    const poll = async () => {
      if (cancelled) return;
      try {
        const data = await apiClient.getModelProgressSnapshot(modelName);
        if (data) {
          applyProgress(data);
          return;
        }

        const modelStatus = await apiClient.getModelStatus();
        const model = modelStatus.models.find((entry) => entry.model_name === modelName);
        if (model?.downloaded || model?.loaded) {
          applyProgress({
            model_name: modelName,
            current: 1,
            total: 1,
            progress: 100,
            status: 'complete',
            filename: undefined,
            timestamp: new Date().toISOString(),
          });
        } else if (model?.downloading) {
          applyProgress({
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
        // Keep polling; transient errors are common with remote tunnels.
      }
    };

    void poll();
    intervalId = window.setInterval(() => {
      void poll();
    }, 1500);

    return () => {
      cancelled = true;
      if (intervalId !== null) {
        window.clearInterval(intervalId);
      }
    };
  }, [serverUrl, modelName, isDownloading]);

  // Don't render if no progress or if complete/error and some time has passed
  if (
    !progress ||
    (progress.status === 'complete' && Date.now() - new Date(progress.timestamp).getTime() > 5000)
  ) {
    return null;
  }

  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / k ** i).toFixed(1)} ${sizes[i]}`;
  };

  const getStatusIcon = () => {
    switch (progress.status) {
      case 'error':
        return <XCircle className="h-4 w-4 text-destructive" />;
      case 'downloading':
      case 'extracting':
        return <Loader2 className="h-4 w-4 animate-spin" />;
      default:
        return null;
    }
  };

  const getStatusText = () => {
    switch (progress.status) {
      case 'complete':
        return 'Download complete';
      case 'error':
        return `Error: ${progress.error || 'Unknown error'}`;
      case 'downloading':
        return progress.filename ? `Downloading ${progress.filename}...` : 'Downloading...';
      case 'extracting':
        return 'Extracting...';
      default:
        return 'Processing...';
    }
  };

  return (
    <Card className="mb-4">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          {getStatusIcon()}
          {displayName}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{getStatusText()}</span>
            {progress.total > 0 && (
              <span>
                {formatBytes(progress.current)} / {formatBytes(progress.total)} (
                {progress.progress.toFixed(1)}%)
              </span>
            )}
          </div>
          {progress.total > 0 && <Progress value={progress.progress} className="h-2" />}
        </div>
      </CardContent>
    </Card>
  );
}
