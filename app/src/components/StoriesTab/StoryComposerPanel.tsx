import { Plus, Sparkles, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/components/ui/use-toast';
import { LANGUAGE_OPTIONS, type LanguageCode } from '@/lib/constants/languages';
import { useProfiles } from '@/lib/hooks/useProfiles';
import { useComposeStoryRoleplay, useGroqModels } from '@/lib/hooks/useStories';
import type { EmotionType, StoryCharacterMapping } from '@/lib/api/types';
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

type MappingRow = StoryCharacterMapping;

function clamp01(value: number): number {
  if (Number.isNaN(value)) return 0.5;
  return Math.min(1, Math.max(0, value));
}

function clampLines(value: number): number {
  if (Number.isNaN(value)) return 8;
  return Math.min(40, Math.max(2, Math.round(value)));
}

function clampCharacters(value: number): number {
  if (Number.isNaN(value)) return 1;
  return Math.min(10, Math.max(1, Math.round(value)));
}

export function StoryComposerPanel() {
  const { toast } = useToast();
  const setSelectedStoryId = useStoryStore((state) => state.setSelectedStoryId);
  const { data: profiles } = useProfiles();
  const { data: groqModels } = useGroqModels();
  const composeStory = useComposeStoryRoleplay();

  const [storyName, setStoryName] = useState('Roleplay Session');
  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState<'novela' | 'roleplay'>('roleplay');
  const [language, setLanguage] = useState<LanguageCode>('es');
  const [targetLines, setTargetLines] = useState(8);
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [mappings, setMappings] = useState<MappingRow[]>([
    {
      character_name: 'Narrador',
      profile_id: '',
      description: '',
      default_emotion: 'neutral',
      default_emotion_intensity: 0.5,
      default_track: 0,
    },
  ]);

  const modelOptions = groqModels?.models ?? [];
  const groqEnabled = groqModels?.enabled ?? false;

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
      prev.map((row) =>
        row.profile_id ? row : { ...row, profile_id: profiles[0].id },
      ),
    );
  }, [profiles]);

  const canSubmit = useMemo(() => {
    if (!groqEnabled) return false;
    if (!storyName.trim() || prompt.trim().length < 5) return false;
    if (!selectedModel) return false;
    if (mappings.length < 1 || mappings.length > 10) return false;
    return mappings.every(
      (m) => m.character_name.trim() && m.profile_id && (m.description ?? '').trim(),
    );
  }, [groqEnabled, storyName, prompt, selectedModel, mappings]);

  const updateMapping = (index: number, patch: Partial<MappingRow>) => {
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
        default_emotion: 'neutral' as EmotionType,
        default_emotion_intensity: 0.5,
        default_track: prev.length + i,
      }));
      return [...prev, ...additions];
    });
  };

  const handleCompose = async () => {
    if (!canSubmit) {
      toast({
        title: 'Missing data',
        description: 'Configure prompt, model, and character mappings.',
        variant: 'destructive',
      });
      return;
    }

    try {
      const result = await composeStory.mutateAsync({
        name: storyName.trim(),
        prompt: prompt.trim(),
        mode,
        language,
        target_lines: targetLines,
        llm_model: selectedModel,
        character_mappings: mappings,
      });

      setSelectedStoryId(result.story_id);
      toast({
        title: 'Story queued',
        description: `Render job ${result.job_id} started with ${result.total_lines} lines.`,
      });
    } catch (error) {
      toast({
        title: 'Compose failed',
        description: error instanceof Error ? error.message : 'Unexpected error',
        variant: 'destructive',
      });
    }
  };

  return (
    <Card className="mb-4">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Sparkles className="h-4 w-4" />
          LLM Story Director
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {!groqEnabled && (
          <p className="text-sm text-destructive">
            Groq no está habilitado en backend. Configura `GROQ_API_KEY` o `VOICEBOX_GROQ_API_KEY`.
          </p>
        )}

        <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
          <div className="md:col-span-2 space-y-1">
            <Label htmlFor="story-name-ai">Story Name</Label>
            <Input
              id="story-name-ai"
              value={storyName}
              onChange={(e) => setStoryName(e.target.value)}
              placeholder="Roleplay Session"
            />
          </div>

          <div className="space-y-1">
            <Label>Mode</Label>
            <Select value={mode} onValueChange={(v) => setMode(v as 'novela' | 'roleplay')}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="roleplay">Roleplay</SelectItem>
                <SelectItem value="novela">Novela</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label>Language</Label>
            <Select value={language} onValueChange={(v) => setLanguage(v as LanguageCode)}>
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
          </div>

          <div className="space-y-1">
            <Label>Groq Model</Label>
            <Select value={selectedModel} onValueChange={setSelectedModel}>
              <SelectTrigger>
                <SelectValue placeholder="Select model" />
              </SelectTrigger>
              <SelectContent>
                {modelOptions.map((model) => (
                  <SelectItem key={model} value={model}>
                    {model}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-1">
          <Label htmlFor="story-prompt-ai">Prompt</Label>
          <Textarea
            id="story-prompt-ai"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe the scenario, tone, and conflict for the story..."
            className="min-h-[90px]"
          />
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>Character Mapping (1-10)</Label>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={addMapping}
              disabled={mappings.length >= 10}
            >
              <Plus className="h-4 w-4 mr-1" />
              Add Character
            </Button>
          </div>
          <div className="grid grid-cols-12 gap-2 items-end">
            <Label className="col-span-6">Number of characters</Label>
            <Input
              className="col-span-6"
              type="number"
              min={1}
              max={10}
              value={mappings.length}
              onChange={(e) => setCharacterCount(Number(e.target.value))}
            />
          </div>
          <div className="space-y-2">
            {mappings.map((mapping, index) => (
              <div key={`${mapping.character_name}-${index}`} className="grid grid-cols-12 gap-2">
                <Input
                  className="col-span-3"
                  value={mapping.character_name}
                  onChange={(e) =>
                    updateMapping(index, {
                      character_name: e.target.value,
                    })
                  }
                  placeholder="Character"
                />
                <Textarea
                  className="col-span-5 min-h-[72px]"
                  value={mapping.description ?? ''}
                  onChange={(e) =>
                    updateMapping(index, {
                      description: e.target.value,
                    })
                  }
                  placeholder="Personality description (required)"
                />
                <Select
                  value={mapping.profile_id}
                  onValueChange={(value) => updateMapping(index, { profile_id: value })}
                >
                  <SelectTrigger className="col-span-4">
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
                <Select
                  value={mapping.default_emotion ?? 'neutral'}
                  onValueChange={(value) =>
                    updateMapping(index, { default_emotion: value as EmotionType })
                  }
                >
                  <SelectTrigger className="col-span-2">
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
                  className="col-span-1"
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
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="col-span-1"
                  onClick={() => removeMapping(index)}
                  disabled={mappings.length === 1}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Label htmlFor="target-lines-ai">Target Lines</Label>
            <Input
              id="target-lines-ai"
              type="number"
              min={2}
              max={40}
              value={targetLines}
              onChange={(e) => setTargetLines(clampLines(Number(e.target.value)))}
              className="w-24"
            />
          </div>
          <Button onClick={handleCompose} disabled={!canSubmit || composeStory.isPending}>
            {composeStory.isPending ? 'Composing...' : 'Compose + Render'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
