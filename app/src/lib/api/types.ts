// API Types matching backend Pydantic models
import type { LanguageCode } from '@/lib/constants/languages';

export interface VoiceProfileCreate {
  name: string;
  description?: string;
  language: LanguageCode;
}

export interface VoiceProfileResponse {
  id: string;
  name: string;
  description?: string;
  language: string;
  avatar_path?: string;
  created_at: string;
  updated_at: string;
}

export interface ProfileSampleCreate {
  reference_text: string;
}

export interface ProfileSampleResponse {
  id: string;
  profile_id: string;
  audio_path: string;
  reference_text: string;
}

export interface GenerationRequest {
  profile_id: string;
  text: string;
  language: LanguageCode;
  seed?: number;
  model_size?: '1.7B' | '0.6B';
  instruct?: string;
}

export interface GenerationResponse {
  id: string;
  profile_id: string;
  text: string;
  language: string;
  audio_path: string;
  duration: number;
  seed?: number;
  created_at: string;
}

export interface HistoryQuery {
  profile_id?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

export interface HistoryResponse extends GenerationResponse {
  profile_name: string;
}

export interface HistoryListResponse {
  items: HistoryResponse[];
  total: number;
}

export interface TranscriptionRequest {
  language?: LanguageCode;
  model_size?: 'base' | 'small' | 'medium' | 'large';
}

export interface TranscriptionResponse {
  text: string;
  duration: number;
}

export interface HealthResponse {
  status: string;
  model_loaded: boolean;
  model_downloaded?: boolean;
  model_size?: string;
  gpu_available: boolean;
  vram_used_mb?: number;
}

export interface ModelProgress {
  model_name: string;
  current: number;
  total: number;
  progress: number;
  filename?: string;
  status: 'downloading' | 'extracting' | 'complete' | 'error';
  timestamp: string;
  error?: string;
}

export interface ModelStatus {
  model_name: string;
  display_name: string;
  downloaded: boolean;
  downloading: boolean; // True if download is in progress
  size_mb?: number;
  loaded: boolean;
}

export interface ModelStatusListResponse {
  models: ModelStatus[];
}

export interface ModelDownloadRequest {
  model_name: string;
}

export interface ActiveDownloadTask {
  model_name: string;
  status: string;
  started_at: string;
}

export interface ActiveGenerationTask {
  task_id: string;
  profile_id: string;
  text_preview: string;
  started_at: string;
}

export interface ActiveTasksResponse {
  downloads: ActiveDownloadTask[];
  generations: ActiveGenerationTask[];
  story_renders?: ActiveStoryRenderTask[];
}

export interface StoryCreate {
  name: string;
  description?: string;
}

export interface StoryResponse {
  id: string;
  name: string;
  description?: string;
  created_at: string;
  updated_at: string;
  item_count: number;
}

export interface StoryItemDetail {
  id: string;
  story_id: string;
  generation_id: string;
  start_time_ms: number;
  track: number;
  trim_start_ms: number;
  trim_end_ms: number;
  created_at: string;
  profile_id: string;
  profile_name: string;
  text: string;
  language: string;
  audio_path: string;
  duration: number;
  seed?: number;
  instruct?: string;
  generation_created_at: string;
}

export interface StoryDetailResponse {
  id: string;
  name: string;
  description?: string;
  created_at: string;
  updated_at: string;
  items: StoryItemDetail[];
}

export interface StoryItemCreate {
  generation_id: string;
  start_time_ms?: number;
  track?: number;
}

export interface StoryItemUpdateTime {
  generation_id: string;
  start_time_ms: number;
}

export interface StoryItemBatchUpdate {
  updates: StoryItemUpdateTime[];
}

export interface StoryItemReorder {
  generation_ids: string[];
}

export interface StoryItemMove {
  start_time_ms: number;
  track: number;
}

export interface StoryItemTrim {
  trim_start_ms: number;
  trim_end_ms: number;
}

export interface StoryItemSplit {
  split_time_ms: number;
}

export interface ActiveStoryRenderTask {
  job_id: string;
  story_id: string;
  status: string;
  total_lines: number;
  processed_lines: number;
  started_at: string;
}

export type EmotionType = 'neutral' | 'happy' | 'sad' | 'angry' | 'fearful' | 'surprised' | 'calm';

export interface StoryCharacterMapping {
  character_name: string;
  profile_id: string;
  description?: string;
  default_emotion?: EmotionType;
  default_emotion_intensity?: number;
  default_track?: number;
}

export interface StoryComposeWithGroqRequest {
  name: string;
  description?: string;
  prompt: string;
  mode: 'novela' | 'roleplay';
  language: LanguageCode;
  target_lines: number;
  llm_model?: string;
  model_size?: '1.7B' | '0.6B';
  gap_ms?: number;
  continue_on_error?: boolean;
  character_mappings: StoryCharacterMapping[];
}

export interface StoryRenderJobResponse {
  job_id: string;
  story_id: string;
  status: string;
  total_lines: number;
}

export interface GroqModelsResponse {
  enabled: boolean;
  default_model: string;
  models: string[];
}

export interface StudioLimits {
  max_lines: number;
  max_chars_per_line: number;
  preview_seconds: number;
}

export interface StudioDraftCreateRequest {
  story_id?: string;
  name: string;
  description?: string;
  prompt: string;
  mode: 'novela' | 'roleplay';
  language: LanguageCode;
  llm_model?: string;
  model_size?: '1.7B' | '0.6B';
  gap_ms?: number;
  continue_on_error?: boolean;
  character_mappings: StoryCharacterMapping[];
  limits?: StudioLimits;
}

export interface StudioDraftResponse {
  draft_id: string;
  story_id: string;
  line_count: number;
  status: string;
  limits_applied: StudioLimits;
}

export interface StudioDraftListItem {
  draft_id: string;
  story_id: string;
  name: string;
  status: string;
  line_count: number;
  created_at: string;
  updated_at: string;
}

export interface StudioDraftLineResponse {
  id: string;
  order_index: number;
  character_name: string;
  profile_id: string;
  text: string;
  emotion: EmotionType;
  emotion_intensity: number;
  truncated: boolean;
  preview_status: string;
  preview_audio_url?: string;
  preview_duration?: number;
  preview_error?: string;
}

export interface StudioDraftDetailResponse {
  draft_id: string;
  story_id: string;
  name: string;
  description?: string;
  prompt: string;
  mode: 'novela' | 'roleplay';
  language: LanguageCode;
  llm_model: string;
  model_size?: '1.7B' | '0.6B';
  gap_ms: number;
  continue_on_error: boolean;
  status: string;
  limits_applied: StudioLimits;
  character_mappings: StoryCharacterMapping[];
  created_at: string;
  updated_at: string;
  lines: StudioDraftLineResponse[];
}

export interface StudioDraftLineUpdate {
  line_id: string;
  character_name?: string;
  text?: string;
  emotion?: EmotionType;
  emotion_intensity?: number;
  order_index?: number;
}

export interface StudioDraftLinesUpdateRequest {
  lines: StudioDraftLineUpdate[];
}

export interface StudioDraftLinesDeleteRequest {
  line_ids: string[];
}

export interface StudioPreviewResponse {
  line_id: string;
  status: string;
  preview_audio_url?: string;
  duration?: number;
  error?: string;
}

export interface StudioRenderFinalResponse {
  draft_id: string;
  job_id: string;
  story_id: string;
  status: string;
  total_lines: number;
}
