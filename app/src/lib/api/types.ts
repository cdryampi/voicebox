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
  origin?: 'all' | 'orphan' | 'linked';
  story_id?: string;
  limit?: number;
  offset?: number;
}

export interface HistoryStoryLink {
  story_id: string;
  story_name: string;
  item_count: number;
}

export interface HistoryResponse extends GenerationResponse {
  profile_name: string;
  is_orphan: boolean;
  linked_story_count: number;
  linked_item_count: number;
  story_links: HistoryStoryLink[];
}

export interface HistoryListResponse {
  items: HistoryResponse[];
  total: number;
}

export interface HistoryBulkDeleteRequest {
  scope: 'all' | 'orphans' | 'story';
  story_id?: string;
  detach_story_items?: boolean;
  dry_run?: boolean;
}

export interface HistoryBulkDeleteResponse {
  scope: 'all' | 'orphans' | 'story';
  story_id?: string;
  dry_run: boolean;
  requested_generations: number;
  deleted_generations: number;
  deleted_audio_files: number;
  protected_generations: number;
  deleted_story_items: number;
  retained_shared_generations: number;
  errors: string[];
}

export interface TranscriptionRequest {
  language?: LanguageCode;
  model_size?: 'base' | 'small' | 'medium' | 'large';
}

export interface TranscriptionResponse {
  text: string;
  duration: number;
  provider: 'groq' | 'whisper_local';
  provider_model?: string;
}

export interface HealthResponse {
  status: string;
  model_loaded: boolean;
  model_downloaded?: boolean;
  model_size?: string;
  gpu_available: boolean;
  gpu_type?: string;
  vram_used_mb?: number;
  backend_type?: string;
}

export interface RuntimeInfoResponse {
  backend_type: string;
  host: string;
  port: number;
  colab_profile: boolean;
  stt_provider: 'groq' | 'whisper_local';
  stt_remote_enabled: boolean;
  stt_fallback_local_enabled: boolean;
  default_model_size: '1.7B' | '0.6B';
  default_whisper_model_size: 'base' | 'small' | 'medium' | 'large';
  torch_cuda_available: boolean;
  torch_cuda_device?: string | null;
  torch_mps_available: boolean;
  tts_loaded: boolean;
  tts_model_size?: '1.7B' | '0.6B' | null;
  tts_device?: string | null;
  tts_torch_dtype?: string | null;
  data_dir: string;
  vram_allocated_mb?: number;
}

export type ServerLogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';

export interface ServerLogEntry {
  id: number;
  ts: string;
  level: ServerLogLevel;
  logger: string;
  message: string;
  tags: string[];
}

export interface ServerLogsResponse {
  items: ServerLogEntry[];
  total_buffered: number;
  dropped_count: number;
}

export interface ServerLogsQuery {
  limit?: number;
  level?: ServerLogLevel;
  contains?: string;
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
  disabled?: boolean;
  disabled_reason?: string;
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

export interface ActiveTasksSummaryResponse {
  downloads_active: number;
  generations_active: number;
  story_renders_active: number;
  has_active_tasks: boolean;
  downloading_models: string[];
  model_ops_busy: boolean;
  model_op_kind?: 'download' | 'activate' | 'delete';
  model_op_model_name?: string;
  model_op_started_at?: string;
  last_terminal_event?: TaskTerminalEvent;
}

export interface TaskTerminalEvent {
  id: number;
  kind: 'generation' | 'download' | 'story_render' | 'model_op';
  state: 'completed' | 'failed';
  entity_id: string;
  message: string;
  error_code?: string;
  created_at: string;
}

export interface TaskEventsResponse {
  events: TaskTerminalEvent[];
  last_id: number;
}

export interface TaskCancelStoryRendersResponse {
  cancelled_job_ids: string[];
  active_before: number;
  message: string;
}

export interface RuntimeResetResponse {
  message: string;
  cancelled_story_render_ids: string[];
  cleared_generation_ids: string[];
  tts_was_loaded: boolean;
  whisper_was_loaded: boolean;
}

export interface CapabilitiesResponse {
  studio_batch_delete: boolean;
  model_progress_snapshot: boolean;
  query_token_get_auth: boolean;
  runtime_defaults: boolean;
}

export interface ModelDefaultsResponse {
  default_tts_model_size: '1.7B' | '0.6B';
  default_whisper_model_size: 'base' | 'small' | 'medium' | 'large';
}

export interface ModelDefaultsUpdateRequest {
  default_tts_model_size: '1.7B' | '0.6B';
  default_whisper_model_size: 'base' | 'small' | 'medium' | 'large';
}

export interface RuntimeModelsResponse {
  tts_loaded_model_size?: '1.7B' | '0.6B';
  whisper_loaded_model_size?: 'base' | 'small' | 'medium' | 'large';
  defaults: ModelDefaultsResponse;
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
  emotion_palette?: EmotionType[];
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

export interface StoryRenderLineStatus {
  id: string;
  order_index: number;
  source_generation_id: string;
  generated_generation_id?: string;
  character_name: string;
  profile_id: string;
  text: string;
  emotion: EmotionType;
  emotion_intensity: number;
  resolved_instruct?: string;
  track: number;
  start_time_ms: number;
  status: string;
  error_message?: string;
}

export interface StoryRenderStatusResponse {
  job_id: string;
  story_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'partial_failed';
  total_lines: number;
  processed_lines: number;
  completed_lines: number;
  failed_lines: number;
  error_summary?: string;
  failure_phase?: 'preflight' | 'line_generation' | 'mix_export';
  failure_code?: string;
  output_audio_path?: string;
  created_at: string;
  updated_at: string;
  completed_at?: string;
  lines: StoryRenderLineStatus[];
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

export interface StudioDirectorSuggestionsRequest {
  character_description: string;
  story_name_hint?: string;
  mode: 'novela' | 'roleplay';
  language: LanguageCode;
  llm_model?: string;
  model_size?: '1.7B' | '0.6B';
  target_cards?: number;
}

export interface StudioDirectorSuggestion {
  title: string;
  description?: string;
  prompt: string;
  mode: 'novela' | 'roleplay';
  language: LanguageCode;
  model_size?: '1.7B' | '0.6B';
  limits: StudioLimits;
  character_mappings: StoryCharacterMapping[];
  preview_outline: string[];
}

export interface StudioDirectorSuggestionsResponse {
  suggestions: StudioDirectorSuggestion[];
}
