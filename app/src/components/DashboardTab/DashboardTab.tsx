import { Link } from '@tanstack/react-router';
import {
  Activity,
  AlertTriangle,
  BookOpen,
  Brain,
  Clapperboard,
  Cpu,
  Download,
  Gauge,
  ListChecks,
  Sparkles,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useDashboardOverview } from '@/lib/hooks/useDashboardOverview';
import { useDashboardStories } from '@/lib/hooks/useDashboardStories';
import { useStoryStore } from '@/stores/storyStore';

function formatDate(value?: string | number | null): string {
  if (!value) return 'unknown';
  const date = typeof value === 'number' ? new Date(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return 'unknown';
  return date.toLocaleString();
}

function formatRelative(value?: string | number | null): string {
  if (!value) return 'unknown';
  const date = typeof value === 'number' ? new Date(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return 'unknown';
  const deltaSeconds = Math.round((Date.now() - date.getTime()) / 1000);
  const abs = Math.abs(deltaSeconds);
  if (abs < 60) return `${abs}s ago`;
  if (abs < 3600) return `${Math.round(abs / 60)}m ago`;
  if (abs < 86400) return `${Math.round(abs / 3600)}h ago`;
  return `${Math.round(abs / 86400)}d ago`;
}

export function DashboardTab() {
  const setSelectedStoryId = useStoryStore((state) => state.setSelectedStoryId);
  const {
    connectionState,
    healthErrorStreak,
    activeCounts,
    activeDownloads,
    activeGenerations,
    activeStoryRenders,
    recentTerminalEvents,
    healthQuery,
    runtimeQuery,
    runtimeModelsQuery,
    modelDefaultsQuery,
    modelStatusQuery,
    downloadedModelsCount,
    loadedModelsCount,
  } = useDashboardOverview();
  const { recentStories, activeStoryId, activeStory, recentDrafts, storiesQuery, draftsQuery } =
    useDashboardStories();

  const connectionLabel =
    connectionState === 'connected'
      ? 'Connected'
      : connectionState === 'degraded'
        ? 'Degraded'
        : 'Disconnected';

  const connectionVariant =
    connectionState === 'connected'
      ? 'secondary'
      : connectionState === 'degraded'
        ? 'outline'
        : 'destructive';

  return (
    <div className="h-full min-h-0 overflow-y-auto py-2 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Operational overview for remote/local voice generation workflows.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to="/generate">Open Fast Generator</Link>
          </Button>
          <Button asChild size="sm">
            <Link to="/studio">Open Studio</Link>
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Gauge className="h-4 w-4" />
              Server Health & Runtime
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              <Badge variant={connectionVariant}>{connectionLabel}</Badge>
              {healthErrorStreak > 0 && (
                <span className="text-xs text-muted-foreground">
                  health errors: {healthErrorStreak}
                </span>
              )}
            </div>
            {healthQuery.isLoading || runtimeQuery.isLoading ? (
              <div className="text-muted-foreground">Loading runtime status...</div>
            ) : healthQuery.error || runtimeQuery.error ? (
              <div className="text-destructive">Could not load runtime diagnostics.</div>
            ) : (
              <>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  <div>Backend: {healthQuery.data?.backend_type ?? runtimeQuery.data?.backend_type ?? 'unknown'}</div>
                  <div>GPU: {healthQuery.data?.gpu_available ? 'yes' : 'no'}</div>
                  <div>GPU type: {healthQuery.data?.gpu_type ?? 'n/a'}</div>
                  <div>CUDA device: {runtimeQuery.data?.torch_cuda_device ?? 'n/a'}</div>
                  <div>TTS loaded: {runtimeQuery.data?.tts_loaded ? 'yes' : 'no'}</div>
                  <div>Torch dtype: {runtimeQuery.data?.tts_torch_dtype ?? 'n/a'}</div>
                </div>
                <div className="text-xs text-muted-foreground">
                  Data dir: {runtimeQuery.data?.data_dir ?? 'unknown'}
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Active Work
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">Generations: {activeCounts.generations}</Badge>
              <Badge variant="outline">Renders: {activeCounts.storyRenders}</Badge>
              <Badge variant="outline">Downloads: {activeCounts.downloads}</Badge>
            </div>
            {!activeCounts.generations && !activeCounts.storyRenders && !activeCounts.downloads ? (
              <div className="text-muted-foreground">No active work.</div>
            ) : (
              <div className="space-y-1 text-xs">
                {activeGenerations.slice(0, 3).map((task) => (
                  <div key={task.task_id} className="rounded border p-2">
                    <span className="font-medium">Generation:</span> {task.text_preview || task.task_id}
                  </div>
                ))}
                {activeStoryRenders.slice(0, 3).map((task) => (
                  <div key={task.job_id} className="rounded border p-2">
                    <span className="font-medium">Render:</span> {task.processed_lines}/{task.total_lines} lines
                  </div>
                ))}
                {activeDownloads.slice(0, 3).map((task) => (
                  <div key={task.model_name} className="rounded border p-2">
                    <span className="font-medium">Download:</span> {task.model_name}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Cpu className="h-4 w-4" />
              Model Runtime
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {runtimeModelsQuery.isLoading || modelDefaultsQuery.isLoading || modelStatusQuery.isLoading ? (
              <div className="text-muted-foreground">Loading model state...</div>
            ) : modelStatusQuery.error ? (
              <div className="text-destructive">Could not load model status.</div>
            ) : (
              <>
                <div>TTS loaded: {runtimeModelsQuery.data?.tts_loaded_model_size ?? 'none'}</div>
                <div>Whisper loaded: {runtimeModelsQuery.data?.whisper_loaded_model_size ?? 'none'}</div>
                <div>Default TTS: {modelDefaultsQuery.data?.default_tts_model_size ?? 'unknown'}</div>
                <div>
                  Default Whisper: {modelDefaultsQuery.data?.default_whisper_model_size ?? 'unknown'}
                </div>
                <div className="text-xs text-muted-foreground">
                  Downloaded models: {downloadedModelsCount} · Loaded models: {loadedModelsCount}
                </div>
              </>
            )}
            <Button asChild variant="outline" size="sm">
              <Link to="/models">Go to Models</Link>
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <BookOpen className="h-4 w-4" />
              Recent Story Activity
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {storiesQuery.isLoading ? (
              <div className="text-muted-foreground">Loading stories...</div>
            ) : !recentStories.length ? (
              <div className="text-muted-foreground">No stories yet.</div>
            ) : (
              recentStories.map((story) => (
                <div key={story.id} className="rounded border p-2 space-y-1">
                  <div className="font-medium">{story.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {story.item_count} items · updated {formatRelative(story.updated_at)}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      asChild
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedStoryId(story.id)}
                    >
                      <Link to="/studio">Open Studio</Link>
                    </Button>
                    <Button
                      asChild
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedStoryId(story.id)}
                    >
                      <Link to="/story-player">Open Player</Link>
                    </Button>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Clapperboard className="h-4 w-4" />
              Studio Draft Activity
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {activeStory && (
              <div className="text-xs text-muted-foreground">
                Active story: <span className="text-foreground">{activeStory.name}</span>
              </div>
            )}
            {draftsQuery.isLoading ? (
              <div className="text-muted-foreground">Loading drafts...</div>
            ) : !recentDrafts.length ? (
              <div className="text-muted-foreground">No drafts for selected story.</div>
            ) : (
              recentDrafts.map((draft) => (
                <div key={draft.draft_id} className="rounded border p-2">
                  <div className="font-medium">{draft.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {draft.line_count} cards · {draft.status} · updated {formatRelative(draft.updated_at)}
                  </div>
                </div>
              ))
            )}
            <div className="flex items-center gap-2">
              {activeStoryId ? (
                <Button
                  asChild
                  variant="outline"
                  size="sm"
                  onClick={() => setSelectedStoryId(activeStoryId)}
                >
                  <Link to="/studio">Resume Draft</Link>
                </Button>
              ) : (
                <Button variant="outline" size="sm" disabled>
                  Resume Draft
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <ListChecks className="h-4 w-4" />
              Incidents / Last Events
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {!recentTerminalEvents.length ? (
              <div className="text-muted-foreground">No recent terminal events.</div>
            ) : (
              recentTerminalEvents.map((event) => (
                <div key={`${event.id}-${event.createdAt}`} className="rounded border p-2">
                  <div className="flex items-center gap-2">
                    {event.state === 'failed' ? (
                      <AlertTriangle className="h-3.5 w-3.5 text-destructive" />
                    ) : event.kind === 'download' ? (
                      <Download className="h-3.5 w-3.5 text-muted-foreground" />
                    ) : event.kind === 'generation' ? (
                      <Sparkles className="h-3.5 w-3.5 text-muted-foreground" />
                    ) : (
                      <Brain className="h-3.5 w-3.5 text-muted-foreground" />
                    )}
                    <span className={event.state === 'failed' ? 'text-destructive' : ''}>
                      {event.kind}: {event.message}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    {formatDate(event.createdAt)}
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
