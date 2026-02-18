import { useNavigate } from '@tanstack/react-router';
import { Plus, Sparkles, Trash2, Wand2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MultiSelect } from '@/components/ui/multi-select';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import type {
  EmotionType,
  StoryCharacterMapping,
  StudioDirectorSuggestion,
  StudioDraftLineResponse,
} from '@/lib/api/types';
import { LANGUAGE_OPTIONS, type LanguageCode } from '@/lib/constants/languages';
import { useProfiles } from '@/lib/hooks/useProfiles';
import { useNotifier } from '@/lib/hooks/useNotifier';
import {
  useCreateStory,
  useCreateStudioDraft,
  useDeleteStudioDraftLines,
  useGenerateStudioLinePreview,
  useGroqModels,
  useRenderStudioDraftFinal,
  useStudioDirectorSuggestions,
  useStoryRenderStatus,
  useStories,
  useStudioDraft,
  useStudioDrafts,
  useUpdateStudioDraftLines,
} from '@/lib/hooks/useStories';
import { useStoryStore } from '@/stores/storyStore';

const EMOTION_OPTIONS: EmotionType[] = [
  'neutral',
  'happy',
  'sad',
  'angry',
  'fearful',
  'surprised',
  'calm',
];
const EMOTION_MULTISELECT_OPTIONS = EMOTION_OPTIONS.map((emotion) => ({
  value: emotion,
  label: emotion,
}));

function clamp01(value: number): number {
  if (Number.isNaN(value)) return 0.5;
  return Math.min(1, Math.max(0, value));
}

function clampLimits(value: number, min: number, max: number, fallback: number): number {
  if (Number.isNaN(value)) return fallback;
  return Math.min(max, Math.max(min, Math.round(value)));
}

function clampCharacters(value: number): number {
  if (Number.isNaN(value)) return 1;
  return Math.min(10, Math.max(1, Math.round(value)));
}

function serializeDraftLines(lines: StudioDraftLineResponse[]): string {
  return JSON.stringify(
    [...lines]
      .sort((a, b) => a.order_index - b.order_index)
      .map((line) => ({
        id: line.id,
        order_index: line.order_index,
        character_name: line.character_name,
        text: line.text,
        emotion: line.emotion,
        emotion_intensity: Number(line.emotion_intensity.toFixed(3)),
      })),
  );
}

export function StudioTab() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { notify } = useNotifier();
  const selectedStoryId = useStoryStore((state) => state.selectedStoryId);
  const setSelectedStoryId = useStoryStore((state) => state.setSelectedStoryId);

  const { data: stories } = useStories();
  const { data: profiles } = useProfiles();
  const { data: groqModels } = useGroqModels();
  const { data: studioDrafts } = useStudioDrafts(selectedStoryId);

  const createStory = useCreateStory();
  const createStudioDraft = useCreateStudioDraft();
  const updateStudioLines = useUpdateStudioDraftLines();
  const deleteStudioLines = useDeleteStudioDraftLines();
  const generatePreview = useGenerateStudioLinePreview();
  const renderFinal = useRenderStudioDraftFinal();
  const directorSuggestions = useStudioDirectorSuggestions();

  const [draftId, setDraftId] = useState<string | null>(null);
  const {
    data: draftDetail,
    isLoading: isDraftLoading,
    refetch: refetchDraft,
  } = useStudioDraft(draftId);

  const [name, setName] = useState('Studio Session');
  const [description, setDescription] = useState('');
  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState<'novela' | 'roleplay'>('roleplay');
  const [language, setLanguage] = useState<LanguageCode>('es');
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [selectedModelSize, setSelectedModelSize] = useState<'0.6B' | '1.7B'>('0.6B');
  const [maxLines, setMaxLines] = useState(20);
  const [maxCharsPerLine, setMaxCharsPerLine] = useState(300);
  const [previewSeconds, setPreviewSeconds] = useState(5);

  const [newStoryName, setNewStoryName] = useState('');
  const [characterDescription, setCharacterDescription] = useState('');
  const [ideaSuggestions, setIdeaSuggestions] = useState<StudioDirectorSuggestion[]>([]);
  const [selectedIdeaIndex, setSelectedIdeaIndex] = useState<number | null>(null);

  const [mappings, setMappings] = useState<StoryCharacterMapping[]>([
    {
      character_name: 'Narrador',
      profile_id: '',
      description: '',
      emotion_palette: ['neutral', 'happy', 'sad', 'angry', 'fearful', 'surprised', 'calm'],
      default_emotion: 'neutral',
      default_emotion_intensity: 0.5,
      default_track: 0,
    },
  ]);
  const [lines, setLines] = useState<StudioDraftLineResponse[]>([]);
  const [selectedLineIds, setSelectedLineIds] = useState<string[]>([]);
  const [previewAudioByLine, setPreviewAudioByLine] = useState<Record<string, string>>({});
  const [savedLinesHash, setSavedLinesHash] = useState('');
  const [activeLineId, setActiveLineId] = useState<string | null>(null);
  const [renderJobId, setRenderJobId] = useState<string | null>(null);
  const previewAudioUrlsRef = useRef<Map<string, string>>(new Map());
  const autosaveTimeoutRef = useRef<number | null>(null);
  const lastRenderTerminalEventRef = useRef<string | null>(null);

  const { data: renderJobStatus } = useStoryRenderStatus(renderJobId);

  const modelOptions = groqModels?.models ?? [];
  const selectedStory = useMemo(
    () => (stories ?? []).find((story) => story.id === selectedStoryId),
    [stories, selectedStoryId],
  );

  useEffect(() => {
    if (!selectedModel && groqModels?.default_model) {
      setSelectedModel(groqModels.default_model);
      return;
    }
    if (!selectedModel && modelOptions.length > 0) {
      setSelectedModel(modelOptions[0]);
    }
  }, [selectedModel, groqModels?.default_model, modelOptions]);

  useEffect(() => {
    if (!profiles?.length) return;
    setMappings((prev) =>
      prev.map((row) => (row.profile_id ? row : { ...row, profile_id: profiles[0].id })),
    );
  }, [profiles]);

  useEffect(() => {
    if (!selectedStory) return;
    setName(selectedStory.name);
    setDescription(selectedStory.description ?? '');
  }, [selectedStory]);

  useEffect(() => {
    if (!renderJobStatus || !renderJobId) return;
    if (
      renderJobStatus.status !== 'completed' &&
      renderJobStatus.status !== 'failed' &&
      renderJobStatus.status !== 'partial_failed'
    ) {
      return;
    }

    const eventKey = `${renderJobStatus.job_id}:${renderJobStatus.status}:${renderJobStatus.processed_lines}`;
    if (lastRenderTerminalEventRef.current === eventKey) {
      return;
    }
    lastRenderTerminalEventRef.current = eventKey;

    if (renderJobStatus.status === 'completed') {
      void notify({
        kind: 'completion',
        title: 'Story render completed',
        body: `Job ${renderJobStatus.job_id} finished successfully.`,
        tag: `global-task:story_render:${renderJobStatus.job_id}:completed`,
      });
      return;
    }

    const errorSummary =
      renderJobStatus.error_summary ||
      (renderJobStatus.status === 'partial_failed'
        ? 'Some lines failed. Review line errors before exporting.'
        : 'Render failed. Check backend logs for details.');
    void notify({
      kind: 'error',
      title:
        renderJobStatus.status === 'partial_failed'
          ? 'Story render completed with errors'
          : 'Story render failed',
      body: errorSummary,
      tag: `global-task:story_render:${renderJobStatus.job_id}:failed`,
    });
  }, [notify, renderJobId, renderJobStatus]);

  useEffect(() => {
    if (!studioDrafts) return;
    if (draftId && studioDrafts.some((draft) => draft.draft_id === draftId)) return;
    setDraftId(studioDrafts[0]?.draft_id ?? null);
  }, [studioDrafts, draftId]);

  useEffect(() => {
    if (!draftDetail) return;
    const sortedLines = [...draftDetail.lines].sort((a, b) => a.order_index - b.order_index);
    setLines(sortedLines);
    setSavedLinesHash(serializeDraftLines(sortedLines));
    setMappings(
      draftDetail.character_mappings.slice(0, 10).map((mapping) => ({
        ...mapping,
        emotion_palette:
          mapping.emotion_palette && mapping.emotion_palette.length > 0
            ? mapping.emotion_palette
            : ['neutral', 'happy', 'sad', 'angry', 'fearful', 'surprised', 'calm'],
      })),
    );
    setName(draftDetail.name);
    setDescription(draftDetail.description ?? '');
    setPrompt(draftDetail.prompt);
    setMode(draftDetail.mode);
    setLanguage(draftDetail.language);
    setSelectedModel(draftDetail.llm_model);
    setSelectedModelSize((draftDetail.model_size as '0.6B' | '1.7B') ?? '0.6B');
    setMaxLines(draftDetail.limits_applied.max_lines);
    setMaxCharsPerLine(draftDetail.limits_applied.max_chars_per_line);
    setPreviewSeconds(draftDetail.limits_applied.preview_seconds);
    setRenderJobId(null);
  }, [draftDetail]);

  useEffect(() => {
    setSelectedLineIds((prev) => prev.filter((lineId) => lines.some((line) => line.id === lineId)));
  }, [lines]);

  useEffect(() => {
    let cancelled = false;
    const desiredLineIds = new Set(
      draftId ? lines.filter((line) => !!line.preview_audio_url).map((line) => line.id) : [],
    );

    for (const [lineId, blobUrl] of previewAudioUrlsRef.current.entries()) {
      if (!desiredLineIds.has(lineId)) {
        URL.revokeObjectURL(blobUrl);
        previewAudioUrlsRef.current.delete(lineId);
      }
    }
    setPreviewAudioByLine(Object.fromEntries(previewAudioUrlsRef.current.entries()));

    if (!draftId) {
      return () => {
        cancelled = true;
      };
    }

    const fetchMissingPreviews = async () => {
      for (const line of lines) {
        if (!line.preview_audio_url || previewAudioUrlsRef.current.has(line.id)) {
          continue;
        }
        try {
          const blob = await apiClient.getStudioLinePreviewBlob(draftId, line.id);
          if (cancelled) return;
          const blobUrl = URL.createObjectURL(blob);
          previewAudioUrlsRef.current.set(line.id, blobUrl);
          setPreviewAudioByLine(Object.fromEntries(previewAudioUrlsRef.current.entries()));
        } catch {
          // Keep direct URL fallback below.
        }
      }
    };

    void fetchMissingPreviews();

    return () => {
      cancelled = true;
    };
  }, [draftId, lines]);

  useEffect(
    () => () => {
      for (const blobUrl of previewAudioUrlsRef.current.values()) {
        URL.revokeObjectURL(blobUrl);
      }
      previewAudioUrlsRef.current.clear();
    },
    [],
  );

  const canGenerate = useMemo(() => {
    if (!groqModels?.enabled) return false;
    if (!prompt.trim() || !selectedModel) return false;
    if (mappings.length < 1 || mappings.length > 10) return false;
    return mappings.every(
      (m) =>
        m.character_name.trim() &&
        m.profile_id &&
        (m.description ?? '').trim() &&
      (m.emotion_palette?.length ?? 0) > 0,
    );
  }, [groqModels?.enabled, prompt, selectedModel, mappings]);

  const canGenerateIdeas = useMemo(() => {
    if (!groqModels?.enabled) return false;
    if (!characterDescription.trim() || !selectedModel) return false;
    return (profiles?.length ?? 0) > 0;
  }, [characterDescription, groqModels?.enabled, profiles, selectedModel]);

  const updateMapping = (index: number, patch: Partial<StoryCharacterMapping>) => {
    setMappings((prev) => prev.map((m, i) => (i === index ? { ...m, ...patch } : m)));
  };

  const addMapping = () => {
    if (mappings.length >= 10) return;
    setMappings((prev) => [
      ...prev,
      {
        character_name: `Character ${prev.length + 1}`,
        profile_id: profiles?.[0]?.id ?? '',
        description: '',
        default_emotion: 'neutral',
        emotion_palette: ['neutral', 'happy', 'sad', 'angry', 'fearful', 'surprised', 'calm'],
        default_emotion_intensity: 0.5,
        default_track: prev.length,
      },
    ]);
  };

  const removeMapping = (index: number) => {
    if (mappings.length <= 1) return;
    setMappings((prev) => prev.filter((_, i) => i !== index));
  };

  const setCharacterCount = (nextCountRaw: number) => {
    const nextCount = clampCharacters(nextCountRaw);
    setMappings((prev) => {
      if (nextCount === prev.length) return prev;
      if (nextCount < prev.length) return prev.slice(0, nextCount);
      const additions = Array.from({ length: nextCount - prev.length }, (_, i) => ({
        character_name: `Character ${prev.length + i + 1}`,
        profile_id: profiles?.[0]?.id ?? '',
        description: '',
        emotion_palette: ['neutral', 'happy', 'sad', 'angry', 'fearful', 'surprised', 'calm'],
        default_emotion: 'neutral' as EmotionType,
        default_emotion_intensity: 0.5,
        default_track: prev.length + i,
      }));
      return [...prev, ...additions];
    });
  };

  const handleCreateStoryInline = async () => {
    const storyName = newStoryName.trim();
    if (!storyName) return;
    try {
      const story = await createStory.mutateAsync({ name: storyName });
      setSelectedStoryId(story.id);
      setNewStoryName('');
      toast({ title: 'Story created', description: `"${story.name}" is ready.` });
    } catch (error) {
      toast({
        title: 'Could not create story',
        description: error instanceof Error ? error.message : 'Unexpected error',
        variant: 'destructive',
      });
    }
  };

  const applyDirectorSuggestion = (suggestion: StudioDirectorSuggestion, index: number) => {
    const fallbackProfileId = profiles?.[0]?.id ?? '';
    const nextMappings = suggestion.character_mappings.map((mapping, mappingIndex) => {
      const hasProfile = (profiles ?? []).some((profile) => profile.id === mapping.profile_id);
      const profileId = hasProfile ? mapping.profile_id : fallbackProfileId;
      return {
        ...mapping,
        profile_id: profileId,
        character_name: mapping.character_name || `Character ${mappingIndex + 1}`,
        description: mapping.description || '',
        emotion_palette:
          mapping.emotion_palette && mapping.emotion_palette.length > 0
            ? mapping.emotion_palette
            : ['neutral', 'happy', 'sad', 'angry', 'fearful', 'surprised', 'calm'],
        default_emotion: mapping.default_emotion || 'neutral',
        default_emotion_intensity: clamp01(mapping.default_emotion_intensity ?? 0.5),
        default_track: mapping.default_track ?? mappingIndex,
      };
    });

    setName(suggestion.title);
    setDescription(suggestion.description ?? '');
    setPrompt(suggestion.prompt);
    setMode(suggestion.mode);
    setLanguage(suggestion.language);
    if (suggestion.model_size) {
      setSelectedModelSize(suggestion.model_size);
    }
    setMappings(nextMappings);
    setMaxLines(clampLimits(suggestion.limits.max_lines, 1, 80, 20));
    setMaxCharsPerLine(clampLimits(suggestion.limits.max_chars_per_line, 20, 1500, 300));
    setPreviewSeconds(clampLimits(suggestion.limits.preview_seconds, 1, 15, 5));
    setSelectedIdeaIndex(index);
    toast({
      title: 'Idea applied',
      description: `"${suggestion.title}" has filled the Studio form.`,
    });
  };

  const handleGenerateIdeas = async () => {
    if (!characterDescription.trim()) {
      toast({
        title: 'Character description required',
        description: 'Add a character description to generate idea presets.',
        variant: 'destructive',
      });
      return;
    }
    if (!selectedModel) {
      toast({
        title: 'Model required',
        description: 'Select a Groq model first.',
        variant: 'destructive',
      });
      return;
    }
    if (!profiles?.length) {
      toast({
        title: 'No voice profiles available',
        description: 'Create at least one voice profile before generating ideas.',
        variant: 'destructive',
      });
      return;
    }

    try {
      const response = await directorSuggestions.mutateAsync({
        character_description: characterDescription.trim(),
        story_name_hint: name.trim() || undefined,
        mode,
        language,
        llm_model: selectedModel,
        model_size: selectedModelSize,
        target_cards: 8,
      });
      setIdeaSuggestions(response.suggestions);
      setSelectedIdeaIndex(null);
      toast({
        title: 'Ideas generated',
        description: 'Choose one of the 4 presets to autofill the Studio form.',
      });
    } catch (error) {
      toast({
        title: 'Idea generation failed',
        description: error instanceof Error ? error.message : 'Unexpected error',
        variant: 'destructive',
      });
    }
  };

  const handleGenerateCards = async () => {
    if (!canGenerate) return;
    try {
      const created = await createStudioDraft.mutateAsync({
        story_id: selectedStoryId ?? undefined,
        name: name.trim(),
        description: description.trim() || undefined,
        prompt: prompt.trim(),
        mode,
        language,
        llm_model: selectedModel,
        model_size: selectedModelSize,
        character_mappings: mappings,
        limits: {
          max_lines: clampLimits(maxLines, 1, 80, 20),
          max_chars_per_line: clampLimits(maxCharsPerLine, 20, 1500, 300),
          preview_seconds: clampLimits(previewSeconds, 1, 15, 5),
        },
      });
      setDraftId(created.draft_id);
      setSelectedStoryId(created.story_id);
      await refetchDraft();
      toast({
        title: 'Draft generated',
        description: `${created.line_count} cards created.`,
      });
    } catch (error) {
      toast({
        title: 'Draft generation failed',
        description: error instanceof Error ? error.message : 'Unexpected error',
        variant: 'destructive',
      });
    }
  };

  const hasUnsavedLines =
    !!draftId && lines.length > 0 && serializeDraftLines(lines) !== savedLinesHash;

  const persistDraft = async (showToast = true) => {
    if (!draftId || !lines.length) return;
    try {
      const updated = await updateStudioLines.mutateAsync({
        draftId,
        data: {
          lines: lines.map((line, idx) => ({
            line_id: line.id,
            character_name: line.character_name,
            text: line.text,
            emotion: line.emotion,
            emotion_intensity: clamp01(line.emotion_intensity),
            order_index: idx,
          })),
        },
      });
      const sortedLines = [...updated.lines].sort((a, b) => a.order_index - b.order_index);
      setLines(sortedLines);
      setSavedLinesHash(serializeDraftLines(sortedLines));
      if (showToast) {
        toast({ title: 'Draft saved', description: 'Cards have been updated.' });
      }
      return updated;
    } catch (error) {
      if (showToast) {
        toast({
          title: 'Save failed',
          description: error instanceof Error ? error.message : 'Unexpected error',
          variant: 'destructive',
        });
      }
      return null;
    }
  };

  const handleSaveDraft = async () => persistDraft(true);

  const handlePreviewLine = async (lineId: string) => {
    if (!draftId) return;
    try {
      const existingUrl = previewAudioUrlsRef.current.get(lineId);
      if (existingUrl) {
        URL.revokeObjectURL(existingUrl);
        previewAudioUrlsRef.current.delete(lineId);
        setPreviewAudioByLine(Object.fromEntries(previewAudioUrlsRef.current.entries()));
      }

      if (hasUnsavedLines) {
        const saved = await persistDraft(false);
        if (!saved) return;
      }

      await generatePreview.mutateAsync({ draftId, lineId });
      await refetchDraft();
      toast({ title: 'Preview ready', description: 'Card preview generated.' });
    } catch (error) {
      toast({
        title: 'Preview failed',
        description: error instanceof Error ? error.message : 'Unexpected error',
        variant: 'destructive',
      });
    }
  };

  const handleRenderFinal = async () => {
    if (!draftId) return;
    const saved = await persistDraft(true);
    if (!saved) return;
    try {
      const result = await renderFinal.mutateAsync(draftId);
      setSelectedStoryId(result.story_id);
      setRenderJobId(result.job_id);
      toast({
        title: 'Final render queued',
        description: `Job ${result.job_id} started.`,
      });
    } catch (error) {
      toast({
        title: 'Render failed',
        description: error instanceof Error ? error.message : 'Unexpected error',
        variant: 'destructive',
      });
    }
  };

  useEffect(() => {
    if (!hasUnsavedLines || updateStudioLines.isPending) {
      if (autosaveTimeoutRef.current !== null) {
        window.clearTimeout(autosaveTimeoutRef.current);
        autosaveTimeoutRef.current = null;
      }
      return;
    }

    autosaveTimeoutRef.current = window.setTimeout(() => {
      void persistDraft(false);
    }, 800);

    return () => {
      if (autosaveTimeoutRef.current !== null) {
        window.clearTimeout(autosaveTimeoutRef.current);
        autosaveTimeoutRef.current = null;
      }
    };
  }, [hasUnsavedLines, updateStudioLines.isPending, lines]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const isCmdOrCtrl = event.metaKey || event.ctrlKey;
      if (!isCmdOrCtrl) return;

      if (event.key.toLowerCase() === 's') {
        event.preventDefault();
        void handleSaveDraft();
      }

      if (event.key === 'Enter' && activeLineId && draftId) {
        event.preventDefault();
        void handlePreviewLine(activeLineId);
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [activeLineId, draftId, lines]);

  const updateLine = (lineId: string, patch: Partial<StudioDraftLineResponse>) => {
    setLines((prev) =>
      prev.map((line) => {
        if (line.id !== lineId) return line;
        const invalidatePreview =
          patch.text !== undefined ||
          patch.character_name !== undefined ||
          patch.emotion !== undefined ||
          patch.emotion_intensity !== undefined;
        return {
          ...line,
          ...patch,
          ...(invalidatePreview
            ? {
                preview_status: 'idle',
                preview_audio_url: undefined,
                preview_duration: undefined,
                preview_error: undefined,
              }
            : {}),
        };
      }),
    );
  };

  const toggleLineSelection = (lineId: string, checked: boolean) => {
    setSelectedLineIds((prev) =>
      checked ? [...new Set([...prev, lineId])] : prev.filter((id) => id !== lineId),
    );
  };

  const allLinesSelected = lines.length > 0 && selectedLineIds.length === lines.length;

  const handleToggleSelectAll = (checked: boolean) => {
    if (!checked) {
      setSelectedLineIds([]);
      return;
    }
    setSelectedLineIds(lines.map((line) => line.id));
  };

  const handleDeleteSelected = async () => {
    if (!draftId || selectedLineIds.length === 0) return;
    if (!window.confirm(`Delete ${selectedLineIds.length} selected cards?`)) return;
    try {
      for (const lineId of selectedLineIds) {
        const existingUrl = previewAudioUrlsRef.current.get(lineId);
        if (existingUrl) {
          URL.revokeObjectURL(existingUrl);
          previewAudioUrlsRef.current.delete(lineId);
        }
      }
      const updated = await deleteStudioLines.mutateAsync({
        draftId,
        data: { line_ids: selectedLineIds },
      });
      const sortedLines = [...updated.lines].sort((a, b) => a.order_index - b.order_index);
      setLines(sortedLines);
      setSavedLinesHash(serializeDraftLines(sortedLines));
      setSelectedLineIds([]);
      setPreviewAudioByLine(Object.fromEntries(previewAudioUrlsRef.current.entries()));
      toast({
        title: 'Cards deleted',
        description: `${selectedLineIds.length} card(s) removed.`,
      });
    } catch (error) {
      toast({
        title: 'Delete failed',
        description: error instanceof Error ? error.message : 'Unexpected error',
        variant: 'destructive',
      });
    }
  };

  const moveLine = (index: number, direction: -1 | 1) => {
    const next = index + direction;
    if (next < 0 || next >= lines.length) return;
    setLines((prev) => {
      const copied = [...prev];
      const item = copied[index];
      copied[index] = copied[next];
      copied[next] = item;
      return copied.map((line, idx) => ({ ...line, order_index: idx }));
    });
  };

  const characterOptions = mappings.map((m) => m.character_name);
  const charLimit = clampLimits(maxCharsPerLine, 20, 1500, 300);

  return (
    <div className="flex h-full min-h-0 gap-6 overflow-hidden">
      <div className="w-full max-w-[360px] flex flex-col gap-4 min-h-0 overflow-y-auto pr-1">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Story Selection</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <Label>Active Story</Label>
              <Select
                value={selectedStoryId ?? ''}
                onValueChange={(value) => setSelectedStoryId(value || null)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select story" />
                </SelectTrigger>
                <SelectContent>
                  {(stories ?? []).map((story) => (
                    <SelectItem key={story.id} value={story.id}>
                      {story.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label>Create Story</Label>
              <div className="flex gap-2">
                <Input
                  value={newStoryName}
                  onChange={(e) => setNewStoryName(e.target.value)}
                  placeholder="New story name"
                />
                <Button
                  type="button"
                  size="icon"
                  variant="outline"
                  onClick={handleCreateStoryInline}
                  disabled={createStory.isPending || !newStoryName.trim()}
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            </div>

            <div className="space-y-1">
              <Label>Draft</Label>
              <Select
                value={draftId ?? ''}
                onValueChange={(value) => setDraftId(value || null)}
                disabled={!studioDrafts?.length}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select draft" />
                </SelectTrigger>
                <SelectContent>
                  {(studioDrafts ?? []).map((draft) => (
                    <SelectItem key={draft.draft_id} value={draft.draft_id}>
                      {draft.name} ({draft.line_count})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Characters (1-10)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <Label>Number of characters</Label>
              <Input
                type="number"
                min={1}
                max={10}
                value={mappings.length}
                onChange={(e) => setCharacterCount(Number(e.target.value))}
              />
            </div>
            {mappings.map((mapping, index) => (
              <div
                key={`${mapping.character_name}-${index}`}
                className="space-y-2 border rounded-md p-2"
              >
                <Input
                  value={mapping.character_name}
                  onChange={(e) => updateMapping(index, { character_name: e.target.value })}
                  placeholder="Character"
                />
                <Textarea
                  value={mapping.description ?? ''}
                  onChange={(e) => updateMapping(index, { description: e.target.value })}
                  placeholder="Personality description (required)"
                  className="min-h-[70px]"
                />
                <div className="space-y-1">
                  <Label className="text-xs">Emotion palette (Qwen3-TTS)</Label>
                  <MultiSelect
                    options={EMOTION_MULTISELECT_OPTIONS}
                    value={mapping.emotion_palette ?? []}
                    onChange={(value) => {
                      const nextPalette = (value.length ? value : ['neutral']) as EmotionType[];
                      const nextDefault = nextPalette.includes(
                        (mapping.default_emotion ?? 'neutral') as EmotionType,
                      )
                        ? (mapping.default_emotion as EmotionType)
                        : nextPalette[0];
                      updateMapping(index, {
                        emotion_palette: nextPalette,
                        default_emotion: nextDefault,
                      });
                    }}
                    placeholder="Select emotions"
                    className="rounded-md h-9 text-xs"
                  />
                </div>
                <Select
                  value={mapping.profile_id}
                  onValueChange={(value) => updateMapping(index, { profile_id: value })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Voice profile" />
                  </SelectTrigger>
                  <SelectContent>
                    {(profiles ?? []).map((profile) => (
                      <SelectItem key={profile.id} value={profile.id}>
                        {profile.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="grid grid-cols-2 gap-2">
                  <Select
                    value={mapping.default_emotion ?? 'neutral'}
                    onValueChange={(value) =>
                      updateMapping(index, { default_emotion: value as EmotionType })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(mapping.emotion_palette?.length
                        ? mapping.emotion_palette
                        : EMOTION_OPTIONS
                      ).map((emotion) => (
                        <SelectItem key={emotion} value={emotion}>
                          {emotion}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input
                    type="number"
                    min={0}
                    max={1}
                    step={0.1}
                    value={mapping.default_emotion_intensity ?? 0.5}
                    onChange={(e) =>
                      updateMapping(index, {
                        default_emotion_intensity: clamp01(Number(e.target.value)),
                      })
                    }
                  />
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => removeMapping(index)}
                  disabled={mappings.length === 1}
                >
                  Remove
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              onClick={addMapping}
              className="w-full"
              disabled={mappings.length >= 10}
            >
              Add Character
            </Button>
          </CardContent>
        </Card>
      </div>

      <div className="flex-1 min-h-0 flex flex-col gap-4 overflow-hidden">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Wand2 className="h-4 w-4" />
              Idea Generator
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              value={characterDescription}
              onChange={(e) => setCharacterDescription(e.target.value)}
              placeholder="Describe your main character. Example: age, personality, fears, desires, speaking style, emotional tone..."
              className="min-h-[95px]"
            />
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">
                Generate 4 short story presets to auto-fill Studio Director.
              </p>
              <Button
                type="button"
                variant="outline"
                onClick={handleGenerateIdeas}
                disabled={!canGenerateIdeas || directorSuggestions.isPending}
              >
                <Sparkles className="h-4 w-4 mr-2" />
                {directorSuggestions.isPending ? 'Generating 4 ideas...' : 'Generate 4 Ideas'}
              </Button>
            </div>

            {!!ideaSuggestions.length && (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                {ideaSuggestions.map((idea, index) => (
                  <Card
                    key={`${idea.title}-${index}`}
                    className={
                      selectedIdeaIndex === index ? 'border-primary ring-1 ring-primary/40' : ''
                    }
                  >
                    <CardContent className="pt-4 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-sm font-semibold truncate">{idea.title}</div>
                        <Button
                          type="button"
                          size="sm"
                          variant={selectedIdeaIndex === index ? 'default' : 'outline'}
                          onClick={() => applyDirectorSuggestion(idea, index)}
                        >
                          Use this idea
                        </Button>
                      </div>
                      {idea.description && (
                        <p className="text-xs text-muted-foreground line-clamp-2">{idea.description}</p>
                      )}
                      <ul className="text-xs text-muted-foreground space-y-1">
                        {idea.preview_outline.slice(0, 4).map((line, itemIndex) => (
                          <li key={`${index}-outline-${itemIndex}`} className="line-clamp-2">
                            • {line}
                          </li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Sparkles className="h-4 w-4" />
              LLM Story Director
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3">
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Story name"
              />
              <Select
                value={mode}
                onValueChange={(value) => setMode(value as 'novela' | 'roleplay')}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="roleplay">Roleplay</SelectItem>
                  <SelectItem value="novela">Novela</SelectItem>
                </SelectContent>
              </Select>
              <Select
                value={language}
                onValueChange={(value) => setLanguage(value as LanguageCode)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LANGUAGE_OPTIONS.map((lang) => (
                    <SelectItem key={lang.value} value={lang.value}>
                      {lang.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={selectedModel} onValueChange={setSelectedModel}>
                <SelectTrigger>
                  <SelectValue placeholder="Groq model" />
                </SelectTrigger>
                <SelectContent>
                  {modelOptions.map((model) => (
                    <SelectItem key={model} value={model}>
                      {model}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={selectedModelSize}
                onValueChange={(value) => setSelectedModelSize(value as '0.6B' | '1.7B')}
              >
                <SelectTrigger>
                  <SelectValue placeholder="TTS model size" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="0.6B">Qwen3-TTS 0.6B</SelectItem>
                  <SelectItem value="1.7B">Qwen3-TTS 1.7B</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional story description"
              className="min-h-[55px]"
            />
            <Textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe the narrative style and scene..."
              className="min-h-[110px]"
            />

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label>Max Cards</Label>
                <Input
                  type="number"
                  value={maxLines}
                  min={1}
                  max={80}
                  onChange={(e) => setMaxLines(clampLimits(Number(e.target.value), 1, 80, 20))}
                />
              </div>
              <div className="space-y-1">
                <Label>Max chars/card</Label>
                <Input
                  type="number"
                  value={maxCharsPerLine}
                  min={20}
                  max={1500}
                  onChange={(e) =>
                    setMaxCharsPerLine(clampLimits(Number(e.target.value), 20, 1500, 300))
                  }
                />
              </div>
              <div className="space-y-1">
                <Label>Preview seconds</Label>
                <Input
                  type="number"
                  value={previewSeconds}
                  min={1}
                  max={15}
                  onChange={(e) => setPreviewSeconds(clampLimits(Number(e.target.value), 1, 15, 5))}
                />
              </div>
            </div>

            <Button
              onClick={handleGenerateCards}
              disabled={!canGenerate || createStudioDraft.isPending}
              className="w-full"
            >
              <Wand2 className="h-4 w-4 mr-2" />
              {createStudioDraft.isPending ? 'Generating cards...' : 'Generate Cards'}
            </Button>
          </CardContent>
        </Card>

        <div className="flex-1 min-h-0 overflow-y-auto space-y-3 pr-1">
          {isDraftLoading && <div className="text-sm text-muted-foreground">Loading draft...</div>}

          {!draftId && !isDraftLoading && (
            <div className="text-sm text-muted-foreground border border-dashed rounded-md p-4">
              Generate a draft to start card-level auditing.
            </div>
          )}

          {!!lines.length && (
            <Card className="sticky top-0 z-10">
              <CardContent className="pt-4 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <Checkbox
                      checked={allLinesSelected}
                      onCheckedChange={(checked) => handleToggleSelectAll(!!checked)}
                    />
                    <span className="text-sm">
                      {selectedLineIds.length > 0
                        ? `${selectedLineIds.length} selected`
                        : 'Select cards'}
                    </span>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {lines.length} card(s) · {hasUnsavedLines ? 'Unsaved changes' : 'Saved'}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => void handleSaveDraft()}
                    disabled={!hasUnsavedLines || updateStudioLines.isPending}
                  >
                    Save
                  </Button>
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    onClick={handleDeleteSelected}
                    disabled={selectedLineIds.length === 0 || deleteStudioLines.isPending}
                  >
                    <Trash2 className="h-4 w-4 mr-2" />
                    Delete Selected
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {lines.map((line, index) => {
            const previewSrc =
              previewAudioByLine[line.id] ??
              (draftId ? apiClient.getStudioLinePreviewUrl(draftId, line.id) : '');
            const profileName =
              (profiles ?? []).find((p) => p.id === line.profile_id)?.name ?? line.profile_id;
            return (
              <Card key={line.id}>
                <CardContent
                  className="pt-4 space-y-3"
                  onClick={() => setActiveLineId(line.id)}
                  onFocusCapture={() => setActiveLineId(line.id)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Checkbox
                        checked={selectedLineIds.includes(line.id)}
                        onCheckedChange={(checked) => toggleLineSelection(line.id, !!checked)}
                      />
                      <span className="text-xs text-muted-foreground">#{index + 1}</span>
                      <span className="text-xs text-muted-foreground">{profileName}</span>
                      <span className="text-xs text-muted-foreground">
                        Status: {line.preview_status}
                      </span>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => moveLine(index, -1)}
                      >
                        Up
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => moveLine(index, 1)}
                      >
                        Down
                      </Button>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
                    <Input
                      value={line.character_name}
                      onChange={(e) => updateLine(line.id, { character_name: e.target.value })}
                      placeholder="Character"
                    />
                    <Select
                      value={line.emotion}
                      onValueChange={(value) =>
                        updateLine(line.id, { emotion: value as EmotionType })
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {EMOTION_OPTIONS.map((emotion) => (
                          <SelectItem key={emotion} value={emotion}>
                            {emotion}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Input
                      type="number"
                      min={0}
                      max={1}
                      step={0.1}
                      value={line.emotion_intensity}
                      onChange={(e) =>
                        updateLine(line.id, { emotion_intensity: clamp01(Number(e.target.value)) })
                      }
                    />
                    <Select
                      value={line.character_name}
                      onValueChange={(value) => updateLine(line.id, { character_name: value })}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Mapped character" />
                      </SelectTrigger>
                      <SelectContent>
                        {characterOptions.map((charName) => (
                          <SelectItem key={charName} value={charName}>
                            {charName}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <Textarea
                    value={line.text}
                    onChange={(e) => updateLine(line.id, { text: e.target.value })}
                    className="min-h-[90px]"
                  />

                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>
                      {line.text.length}/{charLimit} chars {line.truncated ? '(truncated)' : ''}
                    </span>
                    {line.preview_error && (
                      <span className="text-destructive">{line.preview_error}</span>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => handlePreviewLine(line.id)}
                      disabled={generatePreview.isPending}
                    >
                      {line.preview_audio_url
                        ? `Regenerate ${previewSeconds}s`
                        : `Preview ${previewSeconds}s`}
                    </Button>
                    {line.preview_audio_url && (
                      <audio controls src={previewSrc} className="h-8 w-full max-w-[400px]">
                        <track kind="captions" />
                      </audio>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>

        {renderJobId && (
          <Card>
            <CardContent className="pt-4 space-y-2">
              <div className="text-sm font-medium">Final Render Job</div>
              <div className="text-xs text-muted-foreground">Job: {renderJobId}</div>
              {renderJobStatus ? (
                <>
                  <div className="text-sm">
                    Status: <span className="font-medium">{renderJobStatus.status}</span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Progress: {renderJobStatus.processed_lines}/{renderJobStatus.total_lines}
                  </div>
                  {renderJobStatus.error_summary && (
                    <div className="text-xs text-destructive">{renderJobStatus.error_summary}</div>
                  )}
                  {renderJobStatus.lines.some((line) => line.status === 'failed') && (
                    <div className="text-xs text-muted-foreground">
                      Failed lines:{' '}
                      {renderJobStatus.lines
                        .filter((line) => line.status === 'failed')
                        .slice(0, 3)
                        .map((line) => `#${line.order_index + 1}`)
                        .join(', ')}
                    </div>
                  )}
                  {(renderJobStatus.status === 'completed' ||
                    renderJobStatus.status === 'partial_failed') && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => navigate({ to: '/story-player' })}
                    >
                      Open Story Player
                    </Button>
                  )}
                </>
              ) : (
                <div className="text-xs text-muted-foreground">Polling render status...</div>
              )}
            </CardContent>
          </Card>
        )}

        <div className="shrink-0 flex items-center justify-end gap-2">
          <Button
            variant="outline"
            onClick={() => void handleSaveDraft()}
            disabled={!draftId || updateStudioLines.isPending || !lines.length}
          >
            Save Draft
          </Button>
          <Button
            onClick={handleRenderFinal}
            disabled={!draftId || renderFinal.isPending || !lines.length}
          >
            Render Final
          </Button>
        </div>
      </div>
    </div>
  );
}
