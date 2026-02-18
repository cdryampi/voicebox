import type { Platform } from '@/platform/types';
import { webFilesystem } from './filesystem';
import { webUpdater } from './updater';
import { webAudio } from './audio';
import { webLifecycle } from './lifecycle';
import { webMetadata } from './metadata';
import { webNotifications } from './notifications';

export const webPlatform: Platform = {
  filesystem: webFilesystem,
  updater: webUpdater,
  audio: webAudio,
  lifecycle: webLifecycle,
  metadata: webMetadata,
  notifications: webNotifications,
};
