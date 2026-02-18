import {
  AudioWaveform,
  Download,
  FileArchive,
  Loader2,
  MoreHorizontal,
  Play,
  Trash2,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import type {
  HistoryBulkDeleteRequest,
  HistoryBulkDeleteResponse,
  HistoryResponse,
} from '@/lib/api/types';
import { BOTTOM_SAFE_AREA_PADDING } from '@/lib/constants/ui';
import {
  useBulkDeleteHistory,
  useDeleteGeneration,
  useExportGeneration,
  useExportGenerationAudio,
  useHistory,
} from '@/lib/hooks/useHistory';
import { useStories } from '@/lib/hooks/useStories';
import { cn } from '@/lib/utils/cn';
import { formatDate, formatDuration } from '@/lib/utils/format';
import { usePlayerStore } from '@/stores/playerStore';

type OriginFilter = 'all' | 'linked' | 'orphan';

export function HistoryTable() {
  const [page, setPage] = useState(0);
  const [allHistory, setAllHistory] = useState<HistoryResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [isScrolled, setIsScrolled] = useState(false);
  const [originFilter, setOriginFilter] = useState<OriginFilter>('all');
  const [storyFilterId, setStoryFilterId] = useState<string>('');
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false);
  const [bulkPreview, setBulkPreview] = useState<HistoryBulkDeleteResponse | null>(null);
  const [pendingBulkRequest, setPendingBulkRequest] = useState<HistoryBulkDeleteRequest | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [generationToDelete, setGenerationToDelete] = useState<HistoryResponse | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const loadMoreRef = useRef<HTMLDivElement>(null);
  const limit = 20;
  const { toast } = useToast();

  const { data: stories = [] } = useStories();
  const {
    data: historyData,
    isLoading,
    isFetching,
    refetch,
  } = useHistory({
    limit,
    offset: page * limit,
    origin: originFilter,
    story_id: storyFilterId || undefined,
  });

  const deleteGeneration = useDeleteGeneration();
  const bulkDeleteHistory = useBulkDeleteHistory();
  const exportGeneration = useExportGeneration();
  const exportGenerationAudio = useExportGenerationAudio();

  const setAudioWithAutoPlay = usePlayerStore((state) => state.setAudioWithAutoPlay);
  const restartCurrentAudio = usePlayerStore((state) => state.restartCurrentAudio);
  const currentAudioId = usePlayerStore((state) => state.audioId);
  const isPlaying = usePlayerStore((state) => state.isPlaying);
  const audioUrl = usePlayerStore((state) => state.audioUrl);
  const isPlayerVisible = !!audioUrl;

  const selectedStoryName = useMemo(() => {
    if (!storyFilterId) return '';
    return stories.find((story) => story.id === storyFilterId)?.name ?? storyFilterId;
  }, [stories, storyFilterId]);

  useEffect(() => {
    setPage(0);
    setAllHistory([]);
  }, [originFilter, storyFilterId]);

  useEffect(() => {
    if (!historyData?.items) return;
    setTotal(historyData.total);
    if (page === 0) {
      setAllHistory(historyData.items);
      return;
    }
    setAllHistory((prev) => {
      const existingIds = new Set(prev.map((item) => item.id));
      const newItems = historyData.items.filter((item) => !existingIds.has(item.id));
      return [...prev, ...newItems];
    });
  }, [historyData, page]);

  useEffect(() => {
    if (deleteGeneration.isSuccess || bulkDeleteHistory.isSuccess) {
      setPage(0);
      setAllHistory([]);
      void refetch();
    }
  }, [deleteGeneration.isSuccess, bulkDeleteHistory.isSuccess, refetch]);

  useEffect(() => {
    const loadMoreEl = loadMoreRef.current;
    if (!loadMoreEl) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const target = entries[0];
        if (target.isIntersecting && !isFetching && allHistory.length < total) {
          setPage((prev) => prev + 1);
        }
      },
      {
        root: scrollRef.current,
        rootMargin: '100px',
        threshold: 0.1,
      },
    );

    observer.observe(loadMoreEl);
    return () => observer.disconnect();
  }, [isFetching, allHistory.length, total]);

  useEffect(() => {
    const scrollEl = scrollRef.current;
    if (!scrollEl) return;
    const handleScroll = () => setIsScrolled(scrollEl.scrollTop > 0);
    scrollEl.addEventListener('scroll', handleScroll);
    return () => scrollEl.removeEventListener('scroll', handleScroll);
  }, []);

  const history = allHistory;
  const hasMore = allHistory.length < total;

  const handlePlay = (audioId: string, text: string, profileId: string) => {
    if (currentAudioId === audioId) {
      restartCurrentAudio();
      return;
    }
    const trackUrl = apiClient.getAudioUrl(audioId);
    setAudioWithAutoPlay(trackUrl, audioId, profileId, text.substring(0, 50));
  };

  const handleDownloadAudio = (generationId: string, text: string) => {
    exportGenerationAudio.mutate(
      { generationId, text },
      {
        onError: (error) => {
          toast({
            title: 'Failed to download audio',
            description: error.message,
            variant: 'destructive',
          });
        },
      },
    );
  };

  const handleExportPackage = (generationId: string, text: string) => {
    exportGeneration.mutate(
      { generationId, text },
      {
        onError: (error) => {
          toast({
            title: 'Failed to export generation',
            description: error.message,
            variant: 'destructive',
          });
        },
      },
    );
  };

  const handleDeleteClick = (generation: HistoryResponse) => {
    setGenerationToDelete(generation);
    setDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = () => {
    if (!generationToDelete) return;
    deleteGeneration.mutate(generationToDelete.id, {
      onSuccess: () => {
        toast({
          title: 'Audio deleted',
          description: 'Generation removed successfully.',
        });
      },
      onError: (error) => {
        toast({
          title: 'Delete blocked',
          description: error.message,
          variant: 'destructive',
        });
      },
    });
    setDeleteDialogOpen(false);
    setGenerationToDelete(null);
  };

  const buildBulkRequest = (scope: 'all' | 'orphans' | 'story', dryRun: boolean) => {
    const payload: HistoryBulkDeleteRequest = {
      scope,
      dry_run: dryRun,
    };
    if (scope === 'story') {
      payload.story_id = storyFilterId;
      payload.detach_story_items = true;
    }
    return payload;
  };

  const openBulkPreview = async (scope: 'all' | 'orphans' | 'story') => {
    if (scope === 'story' && !storyFilterId) {
      toast({
        title: 'Collection required',
        description: 'Select a Story collection before deleting by collection.',
        variant: 'destructive',
      });
      return;
    }

    try {
      const request = buildBulkRequest(scope, true);
      const preview = await bulkDeleteHistory.mutateAsync(request);
      setPendingBulkRequest(buildBulkRequest(scope, false));
      setBulkPreview(preview);
      setBulkDialogOpen(true);
    } catch (error) {
      toast({
        title: 'Preview failed',
        description: error instanceof Error ? error.message : 'Unexpected error',
        variant: 'destructive',
      });
    }
  };

  const handleBulkConfirm = async () => {
    if (!pendingBulkRequest) return;
    try {
      const result = await bulkDeleteHistory.mutateAsync(pendingBulkRequest);
      setBulkDialogOpen(false);
      setPendingBulkRequest(null);
      setBulkPreview(null);
      toast({
        title: 'Bulk cleanup completed',
        description: [
          `Deleted: ${result.deleted_generations}`,
          `Protected: ${result.protected_generations}`,
          `Shared kept: ${result.retained_shared_generations}`,
          `Story cards removed: ${result.deleted_story_items}`,
        ].join(' · '),
      });
    } catch (error) {
      toast({
        title: 'Bulk cleanup failed',
        description: error instanceof Error ? error.message : 'Unexpected error',
        variant: 'destructive',
      });
    }
  };

  if (isLoading && page === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0 relative">
      <div className="mb-3 border rounded-md p-3 bg-card/60 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">Origin filter</div>
            <Select value={originFilter} onValueChange={(value) => setOriginFilter(value as OriginFilter)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                <SelectItem value="linked">Linked to Story</SelectItem>
                <SelectItem value="orphan">Orphans</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">Collection (Story)</div>
            <Select value={storyFilterId || '__all__'} onValueChange={(value) => setStoryFilterId(value === '__all__' ? '' : value)}>
              <SelectTrigger>
                <SelectValue placeholder="All stories" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">All stories</SelectItem>
                {stories.map((story) => (
                  <SelectItem key={story.id} value={story.id}>
                    {story.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">Quick cleanup</div>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void openBulkPreview('all')}
                disabled={bulkDeleteHistory.isPending}
              >
                Delete All
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void openBulkPreview('orphans')}
                disabled={bulkDeleteHistory.isPending}
              >
                Delete Orphans
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => void openBulkPreview('story')}
                disabled={bulkDeleteHistory.isPending || !storyFilterId}
              >
                Delete Collection
              </Button>
            </div>
          </div>
        </div>
      </div>

      {history.length === 0 ? (
        <div className="text-center py-12 px-5 border-2 border-dashed mb-5 border-muted rounded-md text-muted-foreground flex-1 flex items-center justify-center">
          No voice generations found for current filter.
        </div>
      ) : (
        <>
          {isScrolled && (
            <div className="absolute top-0 left-0 right-0 h-16 bg-gradient-to-b from-background to-transparent z-10 pointer-events-none" />
          )}
          <div
            ref={scrollRef}
            className={cn(
              'flex-1 min-h-0 overflow-y-auto space-y-2 pb-4',
              isPlayerVisible && BOTTOM_SAFE_AREA_PADDING,
            )}
          >
            {history.map((gen) => {
              const isCurrentlyPlaying = currentAudioId === gen.id && isPlaying;
              const storyLabels = gen.story_links.map((link) => `${link.story_name} (${link.item_count})`);
              return (
                <div
                  key={gen.id}
                  className={cn(
                    'flex items-stretch gap-4 h-26 border rounded-md p-3 bg-card hover:bg-muted/70 transition-colors text-left w-full',
                    isCurrentlyPlaying && 'bg-muted/70',
                  )}
                  onMouseDown={(e) => {
                    const target = e.target as HTMLElement;
                    if (target.closest('textarea') || window.getSelection()?.toString()) {
                      return;
                    }
                    handlePlay(gen.id, gen.text, gen.profile_id);
                  }}
                >
                  <div className="flex items-center shrink-0">
                    <AudioWaveform className="h-5 w-5 text-muted-foreground" />
                  </div>

                  <div className="flex flex-col gap-1.5 w-60 shrink-0 justify-center">
                    <div className="font-medium text-sm truncate" title={gen.profile_name}>
                      {gen.profile_name}
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs text-muted-foreground">{gen.language}</span>
                      <span className="text-xs text-muted-foreground">
                        {formatDuration(gen.duration)}
                      </span>
                      {gen.is_orphan ? (
                        <Badge variant="outline" className="text-[10px]">
                          Orphan
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="text-[10px]">
                          Story x{gen.linked_story_count}
                        </Badge>
                      )}
                    </div>
                    <div
                      className="text-xs text-muted-foreground truncate"
                      title={storyLabels.join(', ')}
                    >
                      {gen.is_orphan ? 'Not linked to any story' : storyLabels.join(', ')}
                    </div>
                    <div className="text-xs text-muted-foreground">{formatDate(gen.created_at)}</div>
                  </div>

                  <div className="flex-1 min-w-0 flex">
                    <Textarea
                      value={gen.text}
                      className="flex-1 resize-none text-sm text-muted-foreground select-text"
                      readOnly
                    />
                  </div>

                  <div
                    className="w-10 shrink-0 flex justify-end"
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Actions">
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => handlePlay(gen.id, gen.text, gen.profile_id)}>
                          <Play className="mr-2 h-4 w-4" />
                          Play
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => handleDownloadAudio(gen.id, gen.text)}
                          disabled={exportGenerationAudio.isPending}
                        >
                          <Download className="mr-2 h-4 w-4" />
                          Export Audio
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => handleExportPackage(gen.id, gen.text)}
                          disabled={exportGeneration.isPending}
                        >
                          <FileArchive className="mr-2 h-4 w-4" />
                          Export Package
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => handleDeleteClick(gen)}
                          disabled={deleteGeneration.isPending || !gen.is_orphan}
                          className="text-destructive focus:text-destructive"
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          {gen.is_orphan ? 'Delete' : 'Delete (protected)'}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
              );
            })}

            {hasMore && (
              <div ref={loadMoreRef} className="flex items-center justify-center py-4">
                {isFetching && <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />}
              </div>
            )}

            {!hasMore && history.length > 0 && (
              <div className="text-center py-4 text-xs text-muted-foreground">You've reached the end</div>
            )}
          </div>
        </>
      )}

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Generation</DialogTitle>
            <DialogDescription>
              {generationToDelete?.is_orphan
                ? 'This orphan audio will be permanently deleted.'
                : 'This generation is linked to story cards and is protected.'}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setDeleteDialogOpen(false);
                setGenerationToDelete(null);
              }}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={deleteGeneration.isPending || !generationToDelete?.is_orphan}
            >
              {deleteGeneration.isPending ? 'Deleting...' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={bulkDialogOpen} onOpenChange={setBulkDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm Bulk Cleanup</DialogTitle>
            <DialogDescription>
              Review the dry-run result before deleting audio history.
            </DialogDescription>
          </DialogHeader>
          {bulkPreview && (
            <div className="space-y-2 text-sm">
              <div>Scope: {bulkPreview.scope}</div>
              {bulkPreview.scope === 'story' && (
                <div>
                  Collection: <span className="font-medium">{selectedStoryName || bulkPreview.story_id}</span>
                </div>
              )}
              <div>Requested generations: {bulkPreview.requested_generations}</div>
              <div>Will delete generations: {bulkPreview.deleted_generations}</div>
              <div>Protected generations: {bulkPreview.protected_generations}</div>
              <div>Shared generations retained: {bulkPreview.retained_shared_generations}</div>
              <div>Story cards to remove: {bulkPreview.deleted_story_items}</div>
              {bulkPreview.errors.length > 0 && (
                <div className="text-xs text-muted-foreground">
                  Notes: {bulkPreview.errors.slice(0, 3).join(' | ')}
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setBulkDialogOpen(false);
                setBulkPreview(null);
                setPendingBulkRequest(null);
              }}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleBulkConfirm()}
              disabled={bulkDeleteHistory.isPending || !pendingBulkRequest}
            >
              {bulkDeleteHistory.isPending ? 'Deleting...' : 'Execute Cleanup'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
