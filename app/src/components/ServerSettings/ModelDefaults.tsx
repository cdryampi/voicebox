import { useMutation, useQueryClient } from '@tanstack/react-query';
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
  const defaultTtsModelSize = useModelPreferencesStore((state) => state.defaultTtsModelSize);
  const setDefaultTtsModelSize = useModelPreferencesStore((state) => state.setDefaultTtsModelSize);
  const defaultWhisperModelSize = useModelPreferencesStore((state) => state.defaultWhisperModelSize);
  const setDefaultWhisperModelSize = useModelPreferencesStore(
    (state) => state.setDefaultWhisperModelSize,
  );

  const loadDefaults = useMutation({
    mutationFn: async () => {
      await apiClient.triggerModelDownload(`qwen-tts-${defaultTtsModelSize}`);
      await apiClient.triggerModelDownload(`whisper-${defaultWhisperModelSize}`);
    },
    onSuccess: async () => {
      toast({
        title: 'Default models queued',
        description: `Loading qwen-tts-${defaultTtsModelSize} and whisper-${defaultWhisperModelSize}.`,
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
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">Voice Generation</div>
          <Select
            value={defaultTtsModelSize}
            onValueChange={(value) => setDefaultTtsModelSize(value as '1.7B' | '0.6B')}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1.7B">Qwen TTS 1.7B</SelectItem>
              <SelectItem value="0.6B">Qwen TTS 0.6B</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">Transcription</div>
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
        </div>

        <div className="flex items-end">
          <Button
            onClick={() => loadDefaults.mutate()}
            variant="outline"
            className="w-full"
            disabled={loadDefaults.isPending}
          >
            {loadDefaults.isPending ? 'Loading...' : 'Load Defaults'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
