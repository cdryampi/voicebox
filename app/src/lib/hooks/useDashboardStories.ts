import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api/client';
import { useServerStore } from '@/stores/serverStore';
import { useStoryStore } from '@/stores/storyStore';

const STORIES_REFETCH_MS = 30000;

export function useDashboardStories() {
  const serverUrl = useServerStore((state) => state.serverUrl);
  const selectedStoryId = useStoryStore((state) => state.selectedStoryId);

  const storiesQuery = useQuery({
    queryKey: ['dashboard', 'stories', serverUrl],
    queryFn: () => apiClient.listStories(),
    staleTime: 15000,
    refetchInterval: STORIES_REFETCH_MS,
    retry: 1,
  });

  const recentStories = useMemo(() => {
    const stories = storiesQuery.data ?? [];
    return [...stories]
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
      .slice(0, 6);
  }, [storiesQuery.data]);

  const activeStoryId = selectedStoryId ?? recentStories[0]?.id ?? null;
  const activeStory = activeStoryId
    ? (storiesQuery.data ?? []).find((story) => story.id === activeStoryId) ?? null
    : null;

  const draftsQuery = useQuery({
    queryKey: ['dashboard', 'studio-drafts', serverUrl, activeStoryId],
    queryFn: () => apiClient.listStudioDrafts(activeStoryId!),
    enabled: !!activeStoryId,
    staleTime: 10000,
    refetchInterval: STORIES_REFETCH_MS,
    retry: 1,
  });

  const recentDrafts = useMemo(() => {
    const drafts = draftsQuery.data ?? [];
    return [...drafts]
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
      .slice(0, 6);
  }, [draftsQuery.data]);

  return {
    storiesQuery,
    recentStories,
    activeStoryId,
    activeStory,
    draftsQuery,
    recentDrafts,
  };
}
