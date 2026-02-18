import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/api/client';
import type {
  StoryComposeWithGroqRequest,
  StoryCreate,
  StoryItemBatchUpdate,
  StoryItemCreate,
  StoryItemMove,
  StoryItemReorder,
  StoryItemSplit,
  StoryItemTrim,
  StudioDraftCreateRequest,
  StudioDirectorSuggestionsRequest,
  StudioDraftLinesDeleteRequest,
  StudioDraftLinesUpdateRequest,
} from '@/lib/api/types';
import { usePlatform } from '@/platform/PlatformContext';

export function useStories() {
  return useQuery({
    queryKey: ['stories'],
    queryFn: () => apiClient.listStories(),
  });
}

export function useStory(storyId: string | null) {
  return useQuery({
    queryKey: ['stories', storyId],
    queryFn: () => apiClient.getStory(storyId!),
    enabled: !!storyId,
  });
}

export function useStoryRenderStatus(jobId: string | null) {
  return useQuery({
    queryKey: ['stories', 'jobs', jobId],
    queryFn: () => apiClient.getStoryRenderStatus(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status) return 2000;
      if (status === 'completed' || status === 'failed' || status === 'partial_failed') {
        return false;
      }
      return 2000;
    },
  });
}

export function useCreateStory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: StoryCreate) => apiClient.createStory(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
    },
  });
}

export function useUpdateStory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ storyId, data }: { storyId: string; data: StoryCreate }) =>
      apiClient.updateStory(storyId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useDeleteStory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (storyId: string) => apiClient.deleteStory(storyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
    },
  });
}

export function useAddStoryItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ storyId, data }: { storyId: string; data: StoryItemCreate }) =>
      apiClient.addStoryItem(storyId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useRemoveStoryItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ storyId, itemId }: { storyId: string; itemId: string }) =>
      apiClient.removeStoryItem(storyId, itemId),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useUpdateStoryItemTimes() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ storyId, data }: { storyId: string; data: StoryItemBatchUpdate }) =>
      apiClient.updateStoryItemTimes(storyId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useReorderStoryItems() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ storyId, data }: { storyId: string; data: StoryItemReorder }) =>
      apiClient.reorderStoryItems(storyId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useMoveStoryItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      storyId,
      itemId,
      data,
    }: {
      storyId: string;
      itemId: string;
      data: StoryItemMove;
    }) => apiClient.moveStoryItem(storyId, itemId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useTrimStoryItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      storyId,
      itemId,
      data,
    }: {
      storyId: string;
      itemId: string;
      data: StoryItemTrim;
    }) => apiClient.trimStoryItem(storyId, itemId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useSplitStoryItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      storyId,
      itemId,
      data,
    }: {
      storyId: string;
      itemId: string;
      data: StoryItemSplit;
    }) => apiClient.splitStoryItem(storyId, itemId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useDuplicateStoryItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ storyId, itemId }: { storyId: string; itemId: string }) =>
      apiClient.duplicateStoryItem(storyId, itemId),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', variables.storyId] });
    },
  });
}

export function useExportStoryAudio() {
  const platform = usePlatform();

  return useMutation({
    mutationFn: async ({ storyId, storyName }: { storyId: string; storyName: string }) => {
      const blob = await apiClient.exportStoryAudio(storyId);

      // Create safe filename
      const safeName = storyName
        .substring(0, 50)
        .replace(/[^a-z0-9]/gi, '-')
        .toLowerCase();
      const filename = `${safeName || 'story'}.wav`;

      await platform.filesystem.saveFile(filename, blob, [
        {
          name: 'Audio File',
          extensions: ['wav'],
        },
      ]);

      return blob;
    },
  });
}

export function useGroqModels() {
  return useQuery({
    queryKey: ['llm', 'groq', 'models'],
    queryFn: () => apiClient.listGroqModels(),
  });
}

export function useComposeStoryRoleplay() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: StoryComposeWithGroqRequest) => apiClient.composeStoryRoleplay(data),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', result.story_id] });
    },
  });
}

export function useStudioDraft(draftId: string | null) {
  return useQuery({
    queryKey: ['studio', 'drafts', draftId],
    queryFn: () => apiClient.getStudioDraft(draftId!),
    enabled: !!draftId,
  });
}

export function useStudioDrafts(storyId?: string | null) {
  return useQuery({
    queryKey: ['studio', 'drafts', 'list', storyId ?? 'all'],
    queryFn: () => apiClient.listStudioDrafts(storyId!),
    enabled: !!storyId,
  });
}

export function useCreateStudioDraft() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: StudioDraftCreateRequest) => apiClient.createStudioDraft(data),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', result.story_id] });
      queryClient.invalidateQueries({ queryKey: ['studio', 'drafts', result.draft_id] });
      queryClient.invalidateQueries({ queryKey: ['studio', 'drafts', 'list', result.story_id] });
    },
  });
}

export function useStudioDirectorSuggestions() {
  return useMutation({
    mutationFn: (data: StudioDirectorSuggestionsRequest) =>
      apiClient.getStudioDirectorSuggestions(data),
  });
}

export function useUpdateStudioDraftLines() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ draftId, data }: { draftId: string; data: StudioDraftLinesUpdateRequest }) =>
      apiClient.updateStudioDraftLines(draftId, data),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['studio', 'drafts', result.draft_id] });
      queryClient.invalidateQueries({ queryKey: ['studio', 'drafts', 'list', result.story_id] });
    },
  });
}

export function useDeleteStudioDraftLines() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ draftId, data }: { draftId: string; data: StudioDraftLinesDeleteRequest }) =>
      apiClient.deleteStudioDraftLines(draftId, data),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['studio', 'drafts', result.draft_id] });
      queryClient.invalidateQueries({ queryKey: ['studio', 'drafts', 'list', result.story_id] });
    },
  });
}

export function useGenerateStudioLinePreview() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ draftId, lineId }: { draftId: string; lineId: string }) =>
      apiClient.generateStudioLinePreview(draftId, lineId),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['studio', 'drafts', variables.draftId] });
    },
  });
}

export function useRenderStudioDraftFinal() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (draftId: string) => apiClient.renderStudioDraftFinal(draftId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['stories'] });
      queryClient.invalidateQueries({ queryKey: ['stories', result.story_id] });
      queryClient.invalidateQueries({ queryKey: ['studio', 'drafts', result.draft_id] });
      queryClient.invalidateQueries({ queryKey: ['studio', 'drafts', 'list', result.story_id] });
    },
  });
}
