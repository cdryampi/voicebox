import { Copy, Pause, Play, RefreshCcw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import type { ServerLogEntry, ServerLogLevel, ServerLogsQuery } from '@/lib/api/types';

type StreamState = 'connecting' | 'connected' | 'reconnecting' | 'error' | 'paused';
type LevelFilter = 'ALL' | ServerLogLevel;

const SNAPSHOT_LIMIT = 200;
const MAX_VISIBLE_LOGS = 600;
const RECONNECT_DELAY_MS = 3000;
const FALLBACK_POLL_MS = 3000;

function getLevelColor(level: ServerLogLevel): string {
  if (level === 'ERROR' || level === 'CRITICAL') return 'text-destructive';
  if (level === 'WARNING') return 'text-amber-600';
  if (level === 'INFO') return 'text-foreground';
  return 'text-muted-foreground';
}

function formatLogTime(ts: string): string {
  const parsed = new Date(ts);
  if (Number.isNaN(parsed.getTime())) return ts;
  return parsed.toLocaleTimeString();
}

function mergeLogs(current: ServerLogEntry[], incoming: ServerLogEntry[]): ServerLogEntry[] {
  if (!incoming.length) return current;
  const byId = new Map<number, ServerLogEntry>();
  for (const item of current) byId.set(item.id, item);
  for (const item of incoming) byId.set(item.id, item);
  const merged = [...byId.values()].sort((a, b) => a.id - b.id);
  if (merged.length <= MAX_VISIBLE_LOGS) return merged;
  return merged.slice(-MAX_VISIBLE_LOGS);
}

export function ServerLogsPanel() {
  const { toast } = useToast();
  const [levelFilter, setLevelFilter] = useState<LevelFilter>('ALL');
  const [containsDraft, setContainsDraft] = useState('');
  const [containsFilter, setContainsFilter] = useState('');
  const [logs, setLogs] = useState<ServerLogEntry[]>([]);
  const [streamState, setStreamState] = useState<StreamState>('connecting');
  const [isSnapshotLoading, setIsSnapshotLoading] = useState(false);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [totalBuffered, setTotalBuffered] = useState(0);
  const [droppedCount, setDroppedCount] = useState(0);
  const [isPaused, setIsPaused] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const cudaToastShownRef = useRef(false);

  const effectiveLevel = useMemo<ServerLogLevel | undefined>(() => {
    if (levelFilter === 'ALL') return undefined;
    return levelFilter;
  }, [levelFilter]);

  const query = useMemo<ServerLogsQuery>(
    () => ({
      limit: SNAPSHOT_LIMIT,
      level: effectiveLevel,
      contains: containsFilter || undefined,
    }),
    [containsFilter, effectiveLevel],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setContainsFilter(containsDraft.trim());
    }, 350);
    return () => window.clearTimeout(timer);
  }, [containsDraft]);

  const maybeNotifyCudaAssert = useCallback(
    (entry: ServerLogEntry) => {
      if (cudaToastShownRef.current) return;
      const msg = entry.message.toLowerCase();
      if (!msg.includes('model_activate_cuda_assert') && !msg.includes('device-side assert')) {
        return;
      }
      cudaToastShownRef.current = true;
      toast({
        title: 'CUDA assert in backend',
        description:
          'Restart backend process in Colab, then retry model activation. CUDA state is now invalid.',
        variant: 'destructive',
        duration: 120000,
      });
    },
    [toast],
  );

  const loadSnapshot = useCallback(
    async (replace: boolean) => {
      try {
        if (replace) setIsSnapshotLoading(true);
        const snapshot = await apiClient.getServerLogs(query);
        setTotalBuffered(snapshot.total_buffered);
        setDroppedCount(snapshot.dropped_count);
        setLogs((previous) =>
          replace ? snapshot.items.slice(-MAX_VISIBLE_LOGS) : mergeLogs(previous, snapshot.items),
        );
        for (const entry of snapshot.items) {
          maybeNotifyCudaAssert(entry);
        }
        setSnapshotError(null);
      } catch (error) {
        setSnapshotError(error instanceof Error ? error.message : 'Could not fetch server logs');
      } finally {
        if (replace) setIsSnapshotLoading(false);
      }
    },
    [maybeNotifyCudaAssert, query],
  );

  useEffect(() => {
    void loadSnapshot(true);
  }, [loadSnapshot]);

  useEffect(() => {
    if (!autoScrollRef.current) return;
    const el = containerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [logs]);

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;
    let reconnectTimer: number | null = null;
    let fallbackPollTimer: number | null = null;
    let hasConnected = false;

    const stopFallbackPolling = () => {
      if (fallbackPollTimer !== null) {
        window.clearInterval(fallbackPollTimer);
        fallbackPollTimer = null;
      }
    };

    const startFallbackPolling = () => {
      if (fallbackPollTimer !== null) return;
      fallbackPollTimer = window.setInterval(() => {
        void loadSnapshot(false);
      }, FALLBACK_POLL_MS);
    };

    const closeSource = () => {
      if (source) {
        source.close();
        source = null;
      }
    };

    const connect = () => {
      if (cancelled || isPaused) return;
      setStreamState(hasConnected ? 'reconnecting' : 'connecting');
      closeSource();
      const url = apiClient.getServerLogsStreamUrl(query);
      source = new EventSource(url);

      const onLogEvent = (event: MessageEvent<string>) => {
        if (!event.data) return;
        try {
          const parsed = JSON.parse(event.data) as ServerLogEntry;
          setLogs((previous) => mergeLogs(previous, [parsed]));
          maybeNotifyCudaAssert(parsed);
          setSnapshotError(null);
        } catch {
          // Ignore malformed entries and keep stream alive.
        }
      };

      source.addEventListener('log', onLogEvent as EventListener);
      source.onopen = () => {
        hasConnected = true;
        setStreamState('connected');
        stopFallbackPolling();
      };
      source.onerror = () => {
        closeSource();
        if (cancelled || isPaused) return;
        setStreamState(hasConnected ? 'reconnecting' : 'error');
        startFallbackPolling();
        reconnectTimer = window.setTimeout(() => connect(), RECONNECT_DELAY_MS);
      };
    };

    if (isPaused) {
      setStreamState('paused');
      stopFallbackPolling();
      closeSource();
      return () => {
        stopFallbackPolling();
        closeSource();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      stopFallbackPolling();
      closeSource();
    };
  }, [isPaused, loadSnapshot, maybeNotifyCudaAssert, query]);

  const handleScroll = () => {
    const element = containerRef.current;
    if (!element) return;
    const distanceToBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    autoScrollRef.current = distanceToBottom < 24;
  };

  const handleRefresh = async () => {
    await loadSnapshot(true);
  };

  const handleCopyVisible = async () => {
    if (!logs.length) {
      toast({
        title: 'No logs to copy',
        description: 'The visible log list is empty.',
      });
      return;
    }
    const payload = logs
      .map(
        (entry) =>
          `[${entry.ts}] ${entry.level} ${entry.logger}${entry.tags.length ? ` [${entry.tags.join(',')}]` : ''}\n${entry.message}`,
      )
      .join('\n\n');
    try {
      await navigator.clipboard.writeText(payload);
      toast({
        title: 'Copied',
        description: `${logs.length} log lines copied to clipboard.`,
      });
    } catch (error) {
      toast({
        title: 'Copy failed',
        description: error instanceof Error ? error.message : 'Could not copy logs.',
        variant: 'destructive',
      });
    }
  };

  const streamBadgeVariant =
    streamState === 'connected'
      ? 'default'
      : streamState === 'paused'
        ? 'secondary'
        : streamState === 'error'
          ? 'destructive'
          : 'outline';

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Server Logs
          <Badge variant={streamBadgeVariant}>{streamState}</Badge>
        </CardTitle>
        <CardDescription>
          Live backend logs from runtime buffer (access logs excluded, secrets redacted).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-2 md:grid-cols-[180px_1fr_auto_auto_auto_auto]">
          <Select
            value={levelFilter}
            onValueChange={(value) => setLevelFilter(value as LevelFilter)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All levels</SelectItem>
              <SelectItem value="INFO">Info+</SelectItem>
              <SelectItem value="WARNING">Warning+</SelectItem>
              <SelectItem value="ERROR">Error+</SelectItem>
            </SelectContent>
          </Select>
          <Input
            value={containsDraft}
            onChange={(event) => setContainsDraft(event.target.value)}
            placeholder="Filter text (contains)"
          />
          <Button
            variant="outline"
            type="button"
            onClick={() => setIsPaused((prev) => !prev)}
            className="gap-1"
          >
            {isPaused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
            {isPaused ? 'Resume' : 'Pause'}
          </Button>
          <Button variant="outline" type="button" onClick={() => setLogs([])}>
            Clear view
          </Button>
          <Button variant="outline" type="button" onClick={() => void handleCopyVisible()}>
            <Copy className="h-4 w-4 mr-1" />
            Copy visible
          </Button>
          <Button variant="outline" type="button" onClick={() => void handleRefresh()}>
            <RefreshCcw className="h-4 w-4 mr-1" />
            Refresh
          </Button>
        </div>

        <div className="text-xs text-muted-foreground">
          Buffered: {totalBuffered} · Dropped: {droppedCount} · Showing: {logs.length}
        </div>

        <div className="rounded-md border bg-muted/20 p-2 text-xs text-muted-foreground">
          Runbook: if you see <span className="font-mono">MODEL_ACTIVATE_CUDA_ASSERT</span>, restart
          backend process in Colab, clear GPU state, and retry activation.
        </div>

        {snapshotError && (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
            Snapshot error: {snapshotError}
          </div>
        )}

        <div
          ref={containerRef}
          onScroll={handleScroll}
          className="max-h-[380px] overflow-y-auto rounded-md border bg-background font-mono text-xs"
        >
          {isSnapshotLoading ? (
            <div className="p-3 text-muted-foreground">Loading logs...</div>
          ) : logs.length === 0 ? (
            <div className="p-3 text-muted-foreground">No log lines available.</div>
          ) : (
            logs.map((entry) => (
              <div key={entry.id} className="border-b border-border/60 px-3 py-2 last:border-b-0">
                <div className="mb-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                  <span>[{formatLogTime(entry.ts)}]</span>
                  <span className={getLevelColor(entry.level)}>{entry.level}</span>
                  <span>{entry.logger}</span>
                  {!!entry.tags.length && <span>[{entry.tags.join(', ')}]</span>}
                </div>
                <pre className="whitespace-pre-wrap break-words text-[11px] leading-relaxed">
                  {entry.message}
                </pre>
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}

