import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router';
import { AppFrame } from '@/components/AppFrame/AppFrame';
import { AudioTab } from '@/components/AudioTab/AudioTab';
import { DashboardTab } from '@/components/DashboardTab/DashboardTab';
import { MainEditor } from '@/components/MainEditor/MainEditor';
import { ModelsTab } from '@/components/ModelsTab/ModelsTab';
import { ServerTab } from '@/components/ServerTab/ServerTab';
import { Sidebar } from '@/components/Sidebar';
import { StudioTab } from '@/components/StudioTab/StudioTab';
import { StoryPlayerTab } from '@/components/StoryPlayerTab/StoryPlayerTab';
import { StoriesTab } from '@/components/StoriesTab/StoriesTab';
import { Toaster } from '@/components/ui/toaster';
import { apiClient } from '@/lib/api/client';
import { VoicesTab } from '@/components/VoicesTab/VoicesTab';
import { useModelDownloadToast } from '@/lib/hooks/useModelDownloadToast';
import { MODEL_DISPLAY_NAMES, useRestoreActiveTasks } from '@/lib/hooks/useRestoreActiveTasks';
import { useModelPreferencesStore } from '@/stores/modelPreferencesStore';
import { useServerStore } from '@/stores/serverStore';
import { useEffect } from 'react';
// Simple platform check that works in both web and Tauri
const isMacOS = () => navigator.platform.toLowerCase().includes('mac');

// Root layout component
function RootLayout() {
  // Monitor active downloads/generations and show toasts for them
  const activeDownloads = useRestoreActiveTasks();
  const serverUrl = useServerStore((state) => state.serverUrl);
  const setDefaultTtsModelSize = useModelPreferencesStore((state) => state.setDefaultTtsModelSize);
  const setDefaultWhisperModelSize = useModelPreferencesStore(
    (state) => state.setDefaultWhisperModelSize,
  );

  useEffect(() => {
    let cancelled = false;
    const syncDefaults = async () => {
      try {
        const capabilities = await apiClient.getCapabilities(true);
        if (!capabilities.runtime_defaults) return;
        const defaults = await apiClient.getModelDefaults();
        if (cancelled) return;
        setDefaultTtsModelSize(defaults.default_tts_model_size);
        setDefaultWhisperModelSize(defaults.default_whisper_model_size);
      } catch {
        // Ignore transient remote connectivity/capability errors.
      }
    };
    void syncDefaults();
    return () => {
      cancelled = true;
    };
  }, [serverUrl, setDefaultTtsModelSize, setDefaultWhisperModelSize]);

  return (
    <AppFrame>
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <Sidebar isMacOS={isMacOS()} />

        <main className="flex-1 ml-24 overflow-hidden flex flex-col">
          <div className="container mx-auto px-8 max-w-[1800px] h-full overflow-y-auto flex flex-col">
            <Outlet />
          </div>
        </main>
      </div>

      {/* Show download toasts for any active downloads (from anywhere) */}
      {activeDownloads.map((download) => {
        const displayName = MODEL_DISPLAY_NAMES[download.model_name] || download.model_name;
        return (
          <DownloadToastRestorer
            key={download.model_name}
            modelName={download.model_name}
            displayName={displayName}
          />
        );
      })}

      <Toaster />
    </AppFrame>
  );
}

/**
 * Component that restores a download toast for a specific model.
 */
function DownloadToastRestorer({
  modelName,
  displayName,
}: {
  modelName: string;
  displayName: string;
}) {
  // Use the download toast hook to restore the toast
  useModelDownloadToast({
    modelName,
    displayName,
    enabled: true,
  });

  return null;
}

// Root route with layout
const rootRoute = createRootRoute({
  component: RootLayout,
});

// Home route (dashboard)
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: DashboardTab,
});

// Fast generator route
const generateRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/generate',
  component: MainEditor,
});

// Stories route
const storiesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/stories',
  component: StoriesTab,
});

// Studio route
const studioRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/studio',
  component: StudioTab,
});

// Story player route
const storyPlayerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/story-player',
  component: StoryPlayerTab,
});

// Voices route
const voicesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/voices',
  component: VoicesTab,
});

// Audio route
const audioRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/audio',
  component: AudioTab,
});

// Models route
const modelsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/models',
  component: ModelsTab,
});

// Server route
const serverRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/server',
  component: ServerTab,
});

// Route tree
const routeTree = rootRoute.addChildren([
  indexRoute,
  generateRoute,
  studioRoute,
  storiesRoute,
  storyPlayerRoute,
  voicesRoute,
  audioRoute,
  modelsRoute,
  serverRoute,
]);

// Create router
export const router = createRouter({ routeTree });

// Register router for type safety
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
