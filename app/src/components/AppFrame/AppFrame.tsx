import { useRouterState } from '@tanstack/react-router';
import { TitleBarDragRegion } from '@/components/TitleBarDragRegion';
import { AudioPlayer } from '@/components/AudioPlayer/AudioPlayer';
import { GlobalStatusTopbar } from '@/components/GlobalStatusTopbar/GlobalStatusTopbar';
import { StoryTrackEditor } from '@/components/StoriesTab/StoryTrackEditor';
import { TOP_SAFE_AREA_PADDING } from '@/lib/constants/ui';
import { cn } from '@/lib/utils/cn';
import { useStoryStore } from '@/stores/storyStore';
import { useStory } from '@/lib/hooks/useStories';

interface AppFrameProps {
  children: React.ReactNode;
}

export function AppFrame({ children }: AppFrameProps) {
  const routerState = useRouterState();
  const isStudioRoute = routerState.location.pathname === '/studio';
  const isStoriesRoute = routerState.location.pathname === '/stories';
  const isStoryPlayerRoute = routerState.location.pathname === '/story-player';
  
  const selectedStoryId = useStoryStore((state) => state.selectedStoryId);
  const { data: story } = useStory(selectedStoryId);
  
  // Story timeline editor now lives in Story Player tab, not Stories tab.
  const showTrackEditor = isStoryPlayerRoute && selectedStoryId && story && story.items.length > 0;
  const showAudioPlayer = !isStudioRoute && !isStoriesRoute && !isStoryPlayerRoute && !showTrackEditor;

  return (
    <div className={cn('h-screen bg-background flex flex-col overflow-hidden', TOP_SAFE_AREA_PADDING)}>
      <TitleBarDragRegion />
      <GlobalStatusTopbar />
      {children}
      {showTrackEditor && <StoryTrackEditor storyId={story.id} items={story.items} />}
      {showAudioPlayer && <AudioPlayer />}
    </div>
  );
}
