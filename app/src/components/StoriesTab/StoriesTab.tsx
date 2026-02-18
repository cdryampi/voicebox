import { Link } from '@tanstack/react-router';
import { Button } from '@/components/ui/button';
import { StoryComposerPanel } from './StoryComposerPanel';

export function StoriesTab() {
  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      <div className="w-full max-w-[1400px] mx-auto py-2 overflow-y-auto">
        <div className="mb-4 rounded-lg border p-3 flex items-center justify-between gap-3">
          <div className="text-sm text-muted-foreground">
            Legacy quick composer. For full draft/audit flow, use Studio.
          </div>
          <Button asChild size="sm" variant="outline">
            <Link to="/studio">Open Studio</Link>
          </Button>
        </div>
        <StoryComposerPanel />
      </div>
    </div>
  );
}
