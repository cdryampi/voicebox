import { Link } from '@tanstack/react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Loader2, ServerCrash, ServerIcon, Sparkles } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import { useNotifier } from '@/lib/hooks/useNotifier';
import { useGlobalTaskActivityStore } from '@/stores/globalTaskActivityStore';

function formatTerminalEventLabel(
  kind: 'download' | 'generation' | 'story_render' | 'model_op',
  message: string,
): string {
  if (kind === 'download') return `Model download: ${message}`;
  if (kind === 'story_render') return `Story render: ${message}`;
  if (kind === 'model_op') return `Model op: ${message}`;
  return `Generation: ${message}`;
}

export function GlobalStatusTopbar() {
  const connectionState = useGlobalTaskActivityStore((state) => state.connectionState);
  const healthErrorStreak = useGlobalTaskActivityStore((state) => state.healthErrorStreak);
  const hasActiveTasks = useGlobalTaskActivityStore((state) => state.hasActiveTasks);
  const activeCounts = useGlobalTaskActivityStore((state) => state.activeCounts);
  const activeDownloads = useGlobalTaskActivityStore((state) => state.activeDownloads);
  const activeGenerations = useGlobalTaskActivityStore((state) => state.activeGenerations);
  const activeStoryRenders = useGlobalTaskActivityStore((state) => state.activeStoryRenders);
  const lastTerminalEvent = useGlobalTaskActivityStore((state) => state.lastTerminalEvent);
  const modelOperation = useGlobalTaskActivityStore((state) => state.modelOperation);
  const { notify } = useNotifier();
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [isExpanded, setIsExpanded] = useState(false);
  const previousConnectionStateRef = useRef(connectionState);
  const lastNotifiedTerminalIdRef = useRef(
    useGlobalTaskActivityStore.getState().lastTerminalEvent?.id ?? 0,
  );

  const cancelRendersMutation = useMutation({
    mutationFn: () => apiClient.cancelAllStoryRenders(),
    onSuccess: async (result) => {
      toast({
        title: 'Render cancellation requested',
        description: result.message,
      });
      await queryClient.invalidateQueries({ queryKey: ['tasksSummary'] });
      await queryClient.invalidateQueries({ queryKey: ['activeTasks'] });
      await queryClient.invalidateQueries({ queryKey: ['taskEvents'] });
    },
    onError: (error) => {
      toast({
        title: 'Cancel failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      });
    },
  });

  const resetRuntimeMutation = useMutation({
    mutationFn: () => apiClient.resetRuntime(),
    onSuccess: async (result) => {
      toast({
        title: 'Runtime reset requested',
        description: result.message,
      });
      await queryClient.invalidateQueries({ queryKey: ['tasksSummary'] });
      await queryClient.invalidateQueries({ queryKey: ['activeTasks'] });
      await queryClient.invalidateQueries({ queryKey: ['taskEvents'] });
      await queryClient.invalidateQueries({ queryKey: ['modelStatus'] });
      await queryClient.invalidateQueries({ queryKey: ['runtimeModels'] });
      await queryClient.invalidateQueries({ queryKey: ['runtimeInfo'] });
    },
    onError: (error) => {
      toast({
        title: 'Runtime reset failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      });
    },
  });

  useEffect(() => {
    const shouldExpand =
      connectionState !== 'connected' ||
      hasActiveTasks ||
      modelOperation.busy ||
      lastTerminalEvent?.state === 'failed';
    setIsExpanded(shouldExpand);
  }, [connectionState, hasActiveTasks, modelOperation.busy, lastTerminalEvent?.state]);

  useEffect(() => {
    const previous = previousConnectionStateRef.current;
    if (previous !== connectionState) {
      if (connectionState === 'disconnected') {
        void notify({
          kind: 'error',
          title: 'Server disconnected',
          body: 'Cannot reach backend. Check Colab/ngrok/server status.',
          tag: 'server:disconnected',
          fallbackToToast: true,
        });
      } else if (previous === 'disconnected' && connectionState === 'connected') {
        void notify({
          kind: 'completion',
          title: 'Server reconnected',
          body: 'Connection to backend has been restored.',
          tag: 'server:reconnected',
          fallbackToToast: true,
        });
      }
    }
    previousConnectionStateRef.current = connectionState;
  }, [connectionState, notify]);

  useEffect(() => {
    if (!lastTerminalEvent) return;
    if (lastTerminalEvent.id <= lastNotifiedTerminalIdRef.current) return;
    lastNotifiedTerminalIdRef.current = lastTerminalEvent.id;
    if (lastTerminalEvent.kind !== 'generation') return;

    if (lastTerminalEvent.state === 'completed') {
      void notify({
        kind: 'completion',
        title: 'Audio generation completed',
        body: lastTerminalEvent.message,
        tag: `global-task:generation:${lastTerminalEvent.entity_id}:completed`,
        fallbackToToast: true,
      });
      return;
    }

    void notify({
      kind: 'error',
      title: 'Audio generation failed',
      body: lastTerminalEvent.message,
      tag: `global-task:generation:${lastTerminalEvent.entity_id}:failed`,
      fallbackToToast: true,
    });
  }, [lastTerminalEvent, notify]);

  const isBusy = hasActiveTasks || modelOperation.busy;
  const stateColorClass =
    connectionState === 'connected'
      ? isBusy
        ? 'bg-amber-500'
        : 'bg-emerald-500'
      : connectionState === 'degraded'
        ? 'bg-amber-500'
        : 'bg-red-500';

  const stateText =
    connectionState === 'connected'
      ? isBusy
        ? 'Working'
        : 'Connected'
      : connectionState === 'degraded'
        ? 'Degraded'
        : 'Disconnected';

  return (
    <div className="w-full border-b border-border/70 bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
      <div className="ml-24 px-6 py-2 flex flex-col gap-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <span className={`h-2.5 w-2.5 rounded-full ${stateColorClass}`} />
            <div className="text-xs font-medium">{stateText}</div>
            {(isBusy || connectionState !== 'connected') && (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
            )}
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <span>Gen {activeCounts.generations}</span>
              <span>Render {activeCounts.storyRenders}</span>
              <span>DL {activeCounts.downloads}</span>
              {modelOperation.busy && (
                <span>
                  Model {modelOperation.kind}:{' '}
                  {modelOperation.modelName || 'processing'}
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" asChild className="h-7 px-2 text-xs">
              <Link to="/">Dashboard</Link>
            </Button>
            <Button size="sm" variant="ghost" asChild className="h-7 px-2 text-xs">
              <Link to="/generate">Fast Gen</Link>
            </Button>
            <Button size="sm" variant="ghost" asChild className="h-7 px-2 text-xs">
              <Link to="/studio">Studio</Link>
            </Button>
            <Button size="sm" variant="ghost" asChild className="h-7 px-2 text-xs">
              <Link to="/models">Models</Link>
            </Button>
            <Button size="sm" variant="ghost" asChild className="h-7 px-2 text-xs">
              <Link to="/server">Server</Link>
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-2 text-xs"
              onClick={() => cancelRendersMutation.mutate()}
              disabled={
                cancelRendersMutation.isPending ||
                !activeCounts.storyRenders ||
                connectionState === 'disconnected'
              }
            >
              {cancelRendersMutation.isPending ? 'Cancelling…' : 'Cancel Renders'}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-2 text-xs"
              onClick={() => resetRuntimeMutation.mutate()}
              disabled={
                resetRuntimeMutation.isPending ||
                connectionState === 'disconnected' ||
                modelOperation.busy
              }
            >
              {resetRuntimeMutation.isPending ? 'Resetting…' : 'Reset Runtime'}
            </Button>
          </div>
        </div>

        {isExpanded && (
          <div className="rounded-md border border-border/60 bg-background/60 px-3 py-2">
            {connectionState !== 'connected' ? (
              <div className="flex items-start gap-2 text-xs text-destructive">
                {connectionState === 'disconnected' ? (
                  <ServerCrash className="h-3.5 w-3.5 mt-0.5" />
                ) : (
                  <AlertTriangle className="h-3.5 w-3.5 mt-0.5" />
                )}
                <span>
                  {connectionState === 'disconnected'
                    ? 'Backend unreachable. Review Colab/ngrok and restart server if needed.'
                    : `Server unstable (${healthErrorStreak} health errors).`}
                </span>
              </div>
            ) : (
              <div className="space-y-1">
                {!!activeGenerations.length && (
                  <div className="text-xs flex items-center gap-2">
                    <Sparkles className="h-3.5 w-3.5 text-amber-500" />
                    <span className="truncate">
                      Generating: {activeGenerations[0].text_preview || activeGenerations[0].task_id}
                    </span>
                  </div>
                )}
                {!!activeStoryRenders.length && (
                  <div className="text-xs flex items-center gap-2">
                    <ServerIcon className="h-3.5 w-3.5 text-amber-500" />
                    <span>
                      Rendering stories: {activeStoryRenders.length} active job(s)
                    </span>
                  </div>
                )}
                {!!activeDownloads.length && (
                  <div className="flex flex-wrap gap-1 pt-1">
                    {activeDownloads.slice(0, 4).map((download) => (
                      <Badge key={download.model_name} variant="outline" className="text-[10px]">
                        DL {download.model_name}
                      </Badge>
                    ))}
                  </div>
                )}
                {modelOperation.busy && (
                  <div className="text-xs flex items-center gap-2">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" />
                    <span>
                      Model operation in progress: {modelOperation.kind} {modelOperation.modelName}
                    </span>
                  </div>
                )}
                {lastTerminalEvent && (
                  <div className="pt-1 text-xs text-muted-foreground">
                    Last event:{' '}
                    <span
                      className={
                        lastTerminalEvent.state === 'failed' ? 'text-destructive' : 'text-foreground'
                      }
                    >
                      {formatTerminalEventLabel(lastTerminalEvent.kind, lastTerminalEvent.message)}
                    </span>
                    {lastTerminalEvent.error_code && (
                      <span className="ml-2 text-[10px] uppercase tracking-wide text-muted-foreground/80">
                        {lastTerminalEvent.error_code}
                      </span>
                    )}
                    {lastTerminalEvent.state === 'failed' && (
                      <Button size="sm" variant="ghost" asChild className="ml-2 h-6 px-2 text-[11px]">
                        <Link to="/server">Open Logs</Link>
                      </Button>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
