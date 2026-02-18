const TAG_DEDUPE_MS = 30_000;
const GLOBAL_RATE_LIMIT_MS = 750;

const lastSentByTag = new Map<string, number>();
let lastGlobalSentAt = 0;

function cleanupExpiredTags(now: number) {
  for (const [tag, timestamp] of lastSentByTag.entries()) {
    if (now - timestamp > TAG_DEDUPE_MS) {
      lastSentByTag.delete(tag);
    }
  }
}

export function canEmitNotification(tag?: string): boolean {
  const now = Date.now();
  cleanupExpiredTags(now);

  if (now - lastGlobalSentAt < GLOBAL_RATE_LIMIT_MS) {
    return false;
  }

  if (tag) {
    const lastTagged = lastSentByTag.get(tag);
    if (lastTagged && now - lastTagged < TAG_DEDUPE_MS) {
      return false;
    }
    lastSentByTag.set(tag, now);
  }

  lastGlobalSentAt = now;
  return true;
}

export function buildNotificationTag(...parts: Array<string | number | undefined | null>): string {
  return parts
    .map((part) => (part === undefined || part === null ? '' : String(part).trim()))
    .filter(Boolean)
    .join(':');
}

