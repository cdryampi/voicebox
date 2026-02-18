import { StoryContent } from '@/components/StoriesTab/StoryContent';
import { StoryList } from '@/components/StoriesTab/StoryList';

export function StoryPlayerTab() {
  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      <div className="flex-1 min-h-0 flex gap-6 overflow-hidden">
        <div className="flex flex-col min-h-0 overflow-hidden w-full max-w-[360px] shrink-0">
          <StoryList />
        </div>

        <div className="flex flex-col min-h-0 overflow-hidden flex-1">
          <StoryContent />
        </div>
      </div>
    </div>
  );
}
