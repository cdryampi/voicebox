import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import { useModelPreferencesStore } from '@/stores/modelPreferencesStore';

export function ModelDefaults() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const setDefaultTtsModelSize = useModelPreferencesStore((state) => state.setDefaultTtsModelSize);
  const defaultWhisperModelSize = useModelPreferencesStore((state) => state.defaultWhisperModelSize);
  const setDefaultWhisperModelSize = useModelPreferencesStore(
    (state) => state.setDefaultWhisperModelSize,
  );

  const defaultsQuery = useQuery({
    queryKey: ['modelDefaults'],
    queryFn: () => apiClient.getModelDefaults(),
    staleTime: 30000,
  });
  const runtimeInfoQuery = useQuery({
    queryKey: ['runtimeInfoForDefaults'],
    queryFn: () => apiClient.getRuntimeInfo(),
    staleTime: 10000,
  });
  const isRemoteStt = runtimeInfoQuery.data?.stt_provider === 'groq' && runtimeInfoQuery.data?.colab_profile;

  useEffect(() => {
    if (!defaultsQuery.data) return;
    setDefaultTtsModelSize(defaultsQuery.data.default_tts_model_size);
    setDefaultWhisperModelSize(defaultsQuery.data.default_whisper_model_size);
  }, [defaultsQuery.data, setDefaultTtsModelSize, setDefaultWhisperModelSize]);

  const saveDefaults = useMutation({
    mutationFn: () =>
      apiClient.updateModelDefaults({
        default_tts_model_size: '1.7B',
        default_whisper_model_size: defaultWhisperModelSize,
      }),
    onSuccess: async (saved) => {
      setDefaultTtsModelSize(saved.default_tts_model_size);
      setDefaultWhisperModelSize(saved.default_whisper_model_size);
      toast({
        title: 'Defaults saved',
        description: 'Server defaults updated successfully.',
      });
      await queryClient.invalidateQueries({ queryKey: ['modelDefaults'] });
      await queryClient.invalidateQueries({ queryKey: ['runtimeModels'] });
    },
    onError: (error) => {
      toast({
        title: 'Failed to save defaults',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      });
    },
  });

  const loadDefaults = useMutation({
    mutationFn: async () => {
      await apiClient.triggerModelDownload('qwen-tts-1.7B');
      if (!isRemoteStt) {
        await apiClient.triggerModelDownload(`whisper-${defaultWhisperModelSize}`);
      }
    },
    onSuccess: async () => {
      toast({
        title: 'Default models queued',
        description: isRemoteStt
          ? 'Loading qwen-tts-1.7B. Transcription uses Groq remote STT in this environment.'
          : `Loading qwen-tts-1.7B and whisper-${defaultWhisperModelSize}.`,
      });
      await queryClient.invalidateQueries({ queryKey: ['modelStatus'] });
    },
    onError: (error) => {
      toast({
        title: 'Failed to load defaults',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      });
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Default Runtime Models</CardTitle>
        <CardDescription>
          Define which models are preselected for generation and transcription.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {defaultsQuery.isError && (
          <div className="md:col-span-3 text-sm text-muted-foreground">
            Runtime defaults are not available on this backend version.
          </div>
        )}
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">Voice Generation</div>
          <Select value="1.7B" onValueChange={() => setDefaultTtsModelSize('1.7B')}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1.7B">Qwen TTS 1.7B</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">Transcription</div>
          {isRemoteStt ? (
            <div className="rounded border px-3 py-2 text-sm text-muted-foreground">
              Groq Remote STT ({runtimeInfoQuery.data?.stt_provider ?? 'groq'})
            </div>
          ) : (
            <Select
              value={defaultWhisperModelSize}
              onValueChange={(value) =>
                setDefaultWhisperModelSize(value as 'base' | 'small' | 'medium' | 'large')
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="base">Whisper Base</SelectItem>
                <SelectItem value="small">Whisper Small</SelectItem>
                <SelectItem value="medium">Whisper Medium</SelectItem>
                <SelectItem value="large">Whisper Large</SelectItem>
              </SelectContent>
            </Select>
          )}
        </div>

        <div className="flex items-end">
          <div className="w-full space-y-2">
            <Button
              onClick={() => saveDefaults.mutate()}
              variant="default"
              className="w-full"
              disabled={saveDefaults.isPending || defaultsQuery.isLoading || defaultsQuery.isError}
            >
              {saveDefaults.isPending ? 'Saving...' : 'Save Defaults'}
            </Button>
            <Button
              onClick={() => loadDefaults.mutate()}
              variant="outline"
              className="w-full"
              disabled={loadDefaults.isPending}
            >
              {loadDefaults.isPending ? 'Loading...' : 'Preload Defaults'}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
