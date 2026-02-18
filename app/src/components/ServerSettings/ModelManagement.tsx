import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Loader2, Trash2 } from 'lucide-react';
import { useCallback, useState } from 'react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import { useModelDownloadToast } from '@/lib/hooks/useModelDownloadToast';
import { ModelDefaults } from './ModelDefaults';

export function ModelManagement() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [downloadingModel, setDownloadingModel] = useState<string | null>(null);
  const [downloadingDisplayName, setDownloadingDisplayName] = useState<string | null>(null);
  const [activatingModel, setActivatingModel] = useState<string | null>(null);

  const { data: modelStatus, isLoading } = useQuery({
    queryKey: ['modelStatus'],
    queryFn: async () => apiClient.getModelStatus(),
    refetchInterval: (query) => {
      const data = query.state.data;
      const hasActiveDownloads = !!data?.models?.some((m) => m.downloading);
      return hasActiveDownloads ? 1500 : 15000;
    },
    staleTime: 2000,
  });

  const { data: runtimeModels } = useQuery({
    queryKey: ['runtimeModels'],
    queryFn: async () => {
      try {
        return await apiClient.getRuntimeModels();
      } catch (error) {
        const status = (error as { status?: number })?.status;
        if (status === 404) {
          return null;
        }
        throw error;
      }
    },
    refetchInterval: 5000,
    staleTime: 2000,
  });

  const { data: runtimeInfo } = useQuery({
    queryKey: ['runtimeInfo'],
    queryFn: async () => {
      try {
        return await apiClient.getRuntimeInfo();
      } catch {
        return null;
      }
    },
    refetchInterval: 15000,
    staleTime: 5000,
  });

  const { data: tasksSummary } = useQuery({
    queryKey: ['tasksSummaryForModels'],
    queryFn: () => apiClient.getTasksSummary(),
    refetchInterval: 1500,
    staleTime: 500,
  });

  // Callbacks for download completion
  const handleDownloadComplete = useCallback(() => {
    setDownloadingModel(null);
    setDownloadingDisplayName(null);
    queryClient.invalidateQueries({ queryKey: ['modelStatus'] });
  }, [queryClient]);

  const handleDownloadError = useCallback(() => {
    setDownloadingModel(null);
    setDownloadingDisplayName(null);
  }, []);

  // Use progress toast hook for the downloading model
  useModelDownloadToast({
    modelName: downloadingModel || '',
    displayName: downloadingDisplayName || '',
    enabled: !!downloadingModel && !!downloadingDisplayName,
    onComplete: handleDownloadComplete,
    onError: handleDownloadError,
  });

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [modelToDelete, setModelToDelete] = useState<{
    name: string;
    displayName: string;
    sizeMb?: number;
  } | null>(null);

  const handleDownload = async (modelName: string) => {
    if (isModelOperationBusy) {
      toast({
        title: 'Model operation in progress',
        description: `Wait for current operation to finish: ${modelOperationLabel ?? 'processing'}.`,
      });
      return;
    }
    // Find display name
    const model = modelStatus?.models.find((m) => m.model_name === modelName);
    const displayName = model?.display_name || modelName;
    
    try {
      // IMPORTANT: Call the API FIRST before setting state
      // Setting state enables the SSE EventSource in useModelDownloadToast,
      // which can block/delay the download fetch due to HTTP/1.1 connection limits
      const result = await apiClient.triggerModelDownload(modelName);
      void result;
      
      // NOW set state to enable SSE tracking (after download has started on backend)
      setDownloadingModel(modelName);
      setDownloadingDisplayName(displayName);
      
      // Download initiated successfully - state will be cleared when SSE reports completion
      // or by the polling interval detecting the model is downloaded
      queryClient.invalidateQueries({ queryKey: ['modelStatus'] });
    } catch (error) {
      setDownloadingModel(null);
      setDownloadingDisplayName(null);
      toast({
        title: 'Download failed',
        description: error instanceof Error ? error.message : 'Unknown error',
        variant: 'destructive',
      });
    }
  };

  const handleActivate = async (modelName: string) => {
    if (isModelOperationBusy) {
      toast({
        title: 'Model operation in progress',
        description: `Wait for current operation to finish: ${modelOperationLabel ?? 'processing'}.`,
      });
      return;
    }
    try {
      setActivatingModel(modelName);
      const result = await apiClient.activateModel(modelName);
      toast({
        title: 'Model activated',
        description: `${modelName} is now loaded in runtime.`,
      });
      if (result.warning) {
        toast({
          title: 'Memory safety switch',
          description: result.warning,
        });
      }
      await queryClient.invalidateQueries({ queryKey: ['modelStatus'] });
      await queryClient.invalidateQueries({ queryKey: ['runtimeModels'] });
    } catch (error) {
      const err = error as Error & { errorCode?: string };
      const isCudaAssert = err.errorCode === 'MODEL_ACTIVATE_CUDA_ASSERT';
      const requiresRestart = err.errorCode === 'MODEL_SWITCH_REQUIRES_RESTART';
      toast({
        title: requiresRestart
          ? 'Activation requires restart'
          : isCudaAssert
            ? 'Activation failed: CUDA runtime invalid'
            : 'Activation failed',
        description: requiresRestart
          ? err.message
          : isCudaAssert
          ? `${err.message} Restart backend process in Colab and retry.`
          : error instanceof Error
            ? error.message
            : 'Unknown error',
        variant: 'destructive',
      });
    } finally {
      setActivatingModel(null);
    }
  };

  const deleteMutation = useMutation({
    mutationFn: async (modelName: string) => apiClient.deleteModel(modelName),
    onSuccess: async (_data, _modelName) => {
      toast({
        title: 'Model deleted',
        description: `${modelToDelete?.displayName || 'Model'} has been deleted successfully.`,
      });
      setDeleteDialogOpen(false);
      setModelToDelete(null);
      // Invalidate AND explicitly refetch to ensure UI updates
      // Using refetchType: 'all' ensures we refetch even if the query is stale
      await queryClient.invalidateQueries({ 
        queryKey: ['modelStatus'],
        refetchType: 'all',
      });
      // Also explicitly refetch to guarantee fresh data
      await queryClient.refetchQueries({ queryKey: ['modelStatus'] });
    },
    onError: (error: Error) => {
      toast({
        title: 'Delete failed',
        description: error.message,
        variant: 'destructive',
      });
    },
  });

  const formatSize = (sizeMb?: number): string => {
    if (!sizeMb) return 'Unknown';
    if (sizeMb < 1024) return `${sizeMb.toFixed(1)} MB`;
    return `${(sizeMb / 1024).toFixed(2)} GB`;
  };

  const isModelOperationBusy = !!tasksSummary?.model_ops_busy;
  const modelOperationLabel = isModelOperationBusy
    ? `${tasksSummary?.model_op_kind ?? 'operation'} ${tasksSummary?.model_op_model_name ?? ''}`.trim()
    : null;

  return (
    <div className="space-y-4">
      <ModelDefaults />
      <Card>
      <CardHeader>
        <CardTitle>Model Management</CardTitle>
        <CardDescription>
          Download and manage AI models for voice generation and transcription
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {runtimeInfo?.colab_profile && runtimeInfo.torch_cuda_available && (
          <div className="rounded-lg border border-amber-300/50 bg-amber-50/30 p-3 text-sm text-amber-800 dark:text-amber-200">
            Colab CUDA mode: load models one by one. Activating Whisper unloads Qwen TTS and vice
            versa to avoid VRAM crashes.
          </div>
        )}
        {isModelOperationBusy && (
          <div className="rounded-lg border border-blue-300/50 bg-blue-50/30 p-3 text-sm text-blue-800 dark:text-blue-200">
            Server is processing model operation: {modelOperationLabel}
          </div>
        )}

        {runtimeModels && (
          <div className="rounded-lg border p-3 text-sm text-muted-foreground">
            <div>
              Current runtime:
              {' '}
              <span className="font-medium text-foreground">
                TTS {runtimeModels.tts_loaded_model_size ?? 'not loaded'}
              </span>
              {' · '}
              <span className="font-medium text-foreground">
                Whisper {runtimeModels.whisper_loaded_model_size ?? 'not loaded'}
              </span>
            </div>
          </div>
        )}

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : modelStatus ? (
          <div className="space-y-4">
            {/* TTS Models */}
            <div>
              <h3 className="text-sm font-semibold mb-3 text-muted-foreground">
                Voice Generation Models
              </h3>
              <div className="space-y-2">
                {modelStatus.models
                  .filter((m) => m.model_name === 'qwen-tts-1.7B')
                  .map((model) => (
                    <ModelItem
                      key={model.model_name}
                      model={model}
                      onDownload={() => handleDownload(model.model_name)}
                      onDelete={() => {
                        setModelToDelete({
                          name: model.model_name,
                          displayName: model.display_name,
                          sizeMb: model.size_mb,
                        });
                        setDeleteDialogOpen(true);
                      }}
                      onActivate={() => handleActivate(model.model_name)}
                      isDownloading={downloadingModel === model.model_name}
                      isActivating={activatingModel === model.model_name}
                      disableActions={isModelOperationBusy}
                      formatSize={formatSize}
                    />
                  ))}
              </div>
            </div>

            {/* Whisper Models */}
            <div>
              <h3 className="text-sm font-semibold mb-3 text-muted-foreground">
                Transcription Models
              </h3>
              <div className="space-y-2">
                {modelStatus.models
                  .filter((m) => m.model_name.startsWith('whisper'))
                  .map((model) => (
                    <ModelItem
                      key={model.model_name}
                      model={model}
                      onDownload={() => handleDownload(model.model_name)}
                      onDelete={() => {
                        setModelToDelete({
                          name: model.model_name,
                          displayName: model.display_name,
                          sizeMb: model.size_mb,
                        });
                        setDeleteDialogOpen(true);
                      }}
                      onActivate={() => handleActivate(model.model_name)}
                      isDownloading={downloadingModel === model.model_name}
                      isActivating={activatingModel === model.model_name}
                      disableActions={isModelOperationBusy}
                      formatSize={formatSize}
                    />
                  ))}
              </div>
            </div>

          </div>
        ) : null}
      </CardContent>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Model</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete <strong>{modelToDelete?.displayName}</strong>?
              {modelToDelete?.sizeMb && (
                <>
                  {' '}
                  This will free up {formatSize(modelToDelete.sizeMb)} of disk space. The model will
                  need to be re-downloaded if you want to use it again.
                </>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (modelToDelete) {
                  deleteMutation.mutate(modelToDelete.name);
                }
              }}
              disabled={deleteMutation.isPending || isModelOperationBusy}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Deleting...
                </>
              ) : (
                'Delete'
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      </Card>
    </div>
  );
}

interface ModelItemProps {
  model: {
    model_name: string;
    display_name: string;
    downloaded: boolean;
    downloading?: boolean;  // From server - true if download in progress
    size_mb?: number;
    loaded: boolean;
  };
  onDownload: () => void;
  onDelete: () => void;
  onActivate: () => void;
  isDownloading: boolean;  // Local state - true if user just clicked download
  isActivating: boolean;
  disableActions?: boolean;
  formatSize: (sizeMb?: number) => string;
}

function ModelItem({
  model,
  onDownload,
  onDelete,
  onActivate,
  isDownloading,
  isActivating,
  disableActions = false,
  formatSize,
}: ModelItemProps) {
  // Use server's downloading state OR local state (for immediate feedback before server updates)
  const showDownloading = model.downloading || isDownloading;
  
  return (
    <div className="flex items-center justify-between p-3 border rounded-lg">
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm">{model.display_name}</span>
          {model.loaded && (
            <Badge variant="default" className="text-xs">
              Loaded
            </Badge>
          )}
          {/* Only show Downloaded if actually downloaded AND not downloading */}
          {model.downloaded && !model.loaded && !showDownloading && (
            <Badge variant="secondary" className="text-xs">
              Downloaded
            </Badge>
          )}
        </div>
        {model.downloaded && model.size_mb && !showDownloading && (
          <div className="text-xs text-muted-foreground mt-1">
            Size: {formatSize(model.size_mb)}
          </div>
        )}
      </div>
      <div className="flex items-center gap-2">
        {model.downloaded && !showDownloading ? (
          <div className="flex items-center gap-2">
            {!model.loaded && (
              <Button
                size="sm"
                onClick={onActivate}
                variant="outline"
                disabled={isActivating || disableActions}
              >
                {isActivating ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Loading...
                  </>
                ) : (
                  'Load'
                )}
              </Button>
            )}
            <Button
              size="sm"
              onClick={onDelete}
              variant="outline"
              disabled={model.loaded || disableActions}
              title={model.loaded ? 'Unload model before deleting' : 'Delete model'}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ) : showDownloading ? (
          <Button size="sm" variant="outline" disabled>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            Downloading...
          </Button>
        ) : (
          <Button size="sm" onClick={onDownload} variant="outline" disabled={disableActions}>
            <Download className="h-4 w-4 mr-2" />
            Download
          </Button>
        )}
      </div>
    </div>
  );
}
