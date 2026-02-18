import { Link } from '@tanstack/react-router';
import { AlertTriangle, Loader2, ServerCrash, ServerIcon, Sparkles } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useNotifier } from '@/lib/hooks/useNotifier';
import { useGlobalTaskActivityStore } from '@/stores/globalTaskActivityStore';

function formatTerminalEventLabel(
  kind: 'download' | 'generation' | 'story_render',
  message: string,
): string {
  if (kind === 'download') return `Model download: ${message}`;
  if (kind === 'story_render') return `Story render: ${message}`;
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
  const { notify } = useNotifier();

  const [isExpanded, setIsExpanded] = useState(false);
  const previousConnectionStateRef = useRef(connectionState);

  useEffect(() => {
    const shouldExpand =
      connectionState !== 'connected' || hasActiveTasks || lastTerminalEvent?.state === 'failed';
    setIsExpanded(shouldExpand);
  }, [connectionState, hasActiveTasks, lastTerminalEvent?.state]);

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

  const stateColorClass =
    connectionState === 'connected'
      ? hasActiveTasks
        ? 'bg-amber-500'
        : 'bg-emerald-500'
      : connectionState === 'degraded'
        ? 'bg-amber-500'
        : 'bg-red-500';

  const stateText =
    connectionState === 'connected'
      ? hasActiveTasks
        ? 'Working'
        : 'Connected'
      : connectionState === 'degraded'
        ? 'Degraded'
        : 'Disconnected';

  return (
    <div className="w-full border-b border-border/70 bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
      <div className="ml-20 px-6 py-2 flex flex-col gap-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <span className={`h-2.5 w-2.5 rounded-full ${stateColorClass}`} />
            <div className="text-xs font-medium">{stateText}</div>
            {(hasActiveTasks || connectionState !== 'connected') && (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
            )}
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <span>Gen {activeCounts.generations}</span>
              <span>Render {activeCounts.storyRenders}</span>
              <span>DL {activeCounts.downloads}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" asChild className="h-7 px-2 text-xs">
              <Link to="/studio">Studio</Link>
            </Button>
            <Button size="sm" variant="ghost" asChild className="h-7 px-2 text-xs">
              <Link to="/models">Models</Link>
            </Button>
            <Button size="sm" variant="ghost" asChild className="h-7 px-2 text-xs">
              <Link to="/server">Server</Link>
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
