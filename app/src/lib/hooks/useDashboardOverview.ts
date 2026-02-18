import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api/client';
import { useServerStore } from '@/stores/serverStore';
import { useGlobalTaskActivityStore } from '@/stores/globalTaskActivityStore';

const DASHBOARD_REFETCH_MS = 30000;

export function useDashboardOverview() {
  const serverUrl = useServerStore((state) => state.serverUrl);

  const connectionState = useGlobalTaskActivityStore((state) => state.connectionState);
  const healthErrorStreak = useGlobalTaskActivityStore((state) => state.healthErrorStreak);
  const hasActiveTasks = useGlobalTaskActivityStore((state) => state.hasActiveTasks);
  const activeCounts = useGlobalTaskActivityStore((state) => state.activeCounts);
  const activeDownloads = useGlobalTaskActivityStore((state) => state.activeDownloads);
  const activeGenerations = useGlobalTaskActivityStore((state) => state.activeGenerations);
  const activeStoryRenders = useGlobalTaskActivityStore((state) => state.activeStoryRenders);
  const terminalEvents = useGlobalTaskActivityStore((state) => state.terminalEvents);

  const healthQuery = useQuery({
    queryKey: ['dashboard', 'health', serverUrl],
    queryFn: () => apiClient.getHealth(),
    staleTime: 10000,
    refetchInterval: DASHBOARD_REFETCH_MS,
    retry: 1,
  });

  const runtimeQuery = useQuery({
    queryKey: ['dashboard', 'runtime', serverUrl],
    queryFn: () => apiClient.getRuntimeInfo(),
    staleTime: 15000,
    refetchInterval: DASHBOARD_REFETCH_MS,
    retry: 1,
  });

  const runtimeModelsQuery = useQuery({
    queryKey: ['dashboard', 'runtime-models', serverUrl],
    queryFn: () => apiClient.getRuntimeModels(),
    staleTime: 10000,
    refetchInterval: DASHBOARD_REFETCH_MS,
    retry: 1,
  });

  const modelDefaultsQuery = useQuery({
    queryKey: ['dashboard', 'model-defaults', serverUrl],
    queryFn: () => apiClient.getModelDefaults(),
    staleTime: 15000,
    refetchInterval: DASHBOARD_REFETCH_MS,
    retry: 1,
  });

  const modelStatusQuery = useQuery({
    queryKey: ['dashboard', 'model-status', serverUrl],
    queryFn: () => apiClient.getModelStatus(),
    staleTime: 15000,
    refetchInterval: hasActiveTasks ? 15000 : DASHBOARD_REFETCH_MS,
    retry: 1,
  });

  const recentTerminalEvents = useMemo(
    () => [...terminalEvents].slice(-8).reverse(),
    [terminalEvents],
  );

  const downloadedModelsCount =
    modelStatusQuery.data?.models.filter((model) => model.downloaded).length ?? 0;
  const loadedModelsCount = modelStatusQuery.data?.models.filter((model) => model.loaded).length ?? 0;

  return {
    connectionState,
    healthErrorStreak,
    hasActiveTasks,
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
  };
}
