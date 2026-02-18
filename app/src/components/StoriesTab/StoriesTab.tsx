import { Link } from '@tanstack/react-router';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { StoryComposerPanel } from './StoryComposerPanel';

export function StoriesTab() {
  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      <div className="w-full max-w-[1400px] mx-auto py-2 overflow-y-auto">
        <div className="mb-4 rounded-lg border p-3 flex items-center justify-between gap-3">
          <div className="text-sm text-muted-foreground flex items-center gap-2">
            <Badge variant="outline">Legacy</Badge>
            <span>Legacy quick composer. For full draft/audit flow, use Studio.</span>
          </div>
          <div className="flex items-center gap-2">
            <Button asChild size="sm" variant="outline">
              <Link to="/studio">Open Studio</Link>
            </Button>
            <Button asChild size="sm" variant="outline">
              <Link to="/">Dashboard</Link>
            </Button>
          </div>
        </div>
        <StoryComposerPanel />
      </div>
    </div>
  );
}
