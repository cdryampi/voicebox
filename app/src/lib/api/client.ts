import { useServerStore } from '@/stores/serverStore';
import type { LanguageCode } from '@/lib/constants/languages';
import type {
  VoiceProfileCreate,
  VoiceProfileResponse,
  ProfileSampleResponse,
  GenerationRequest,
  GenerationResponse,
  HistoryQuery,
  HistoryListResponse,
  HistoryResponse,
  TranscriptionResponse,
  HealthResponse,
  ModelStatusListResponse,
  ModelDownloadRequest,
  ActiveTasksResponse,
  StoryCreate,
  StoryResponse,
  StoryDetailResponse,
  StoryItemCreate,
  StoryItemDetail,
  StoryItemBatchUpdate,
  StoryItemReorder,
  StoryItemMove,
  StoryItemTrim,
  StoryItemSplit,
  StoryComposeWithGroqRequest,
  StoryRenderJobResponse,
  GroqModelsResponse,
  StudioDraftCreateRequest,
  StudioDraftResponse,
  StudioDraftListItem,
  StudioDraftDetailResponse,
  StudioDraftLinesUpdateRequest,
  StudioPreviewResponse,
  StudioRenderFinalResponse,
} from './types';

class ApiClient {
  private static readonly NGROK_BYPASS_HEADER = 'ngrok-skip-browser-warning';

  private getBaseUrl(): string {
    const serverUrl = useServerStore.getState().serverUrl;
    return serverUrl;
  }

  private getApiKey(): string {
    return useServerStore.getState().apiKey?.trim() || '';
  }

  private getAuthHeaders(): Record<string, string> {
    const token = this.getApiKey();
    if (!token) return {};
    return {
      Authorization: `Bearer ${token}`,
    };
  }

  private getNgrokBypassHeaders(): Record<string, string> {
    return {
      [ApiClient.NGROK_BYPASS_HEADER]: '1',
    };
  }

  private getRequestHeaders(extraHeaders?: Record<string, string>): Record<string, string> {
    return {
      ...this.getNgrokBypassHeaders(),
      ...this.getAuthHeaders(),
      ...extraHeaders,
    };
  }

  private isNgrokWarningHtml(payload: string): boolean {
    return payload.includes('ERR_NGROK_6024') || payload.includes('id="ngrok"');
  }

  private getNgrokWarningError(): Error {
    return new Error(
      'Ngrok returned a browser warning page (ERR_NGROK_6024). Verify the ngrok URL and keep the ngrok bypass header enabled.',
    );
  }

  private buildAuthedUrl(endpoint: string): string {
    const url = new URL(`${this.getBaseUrl()}${endpoint}`);
    const token = this.getApiKey();
    if (token) {
      url.searchParams.set('access_token', token);
    }
    // Fallback for browser primitives (<img>, <audio>, EventSource) where custom headers may not be set.
    url.searchParams.set(ApiClient.NGROK_BYPASS_HEADER, '1');
    return url.toString();
  }

  private async fetchWithAuth(url: string, options?: RequestInit): Promise<Response> {
    return fetch(url, {
      ...options,
      headers: {
        ...this.getRequestHeaders(),
        ...options?.headers,
      },
    });
  }

  private async request<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const url = `${this.getBaseUrl()}${endpoint}`;
    const response = await fetch(url, {
      ...options,
      headers: {
        ...this.getRequestHeaders({
          'Content-Type': 'application/json',
        }),
        ...options?.headers,
      },
    });
    const payload = await response.text();

    if (this.isNgrokWarningHtml(payload)) {
      throw this.getNgrokWarningError();
    }

    if (!response.ok) {
      let detail = response.statusText || `HTTP error! status: ${response.status}`;
      try {
        const parsed = JSON.parse(payload) as { detail?: string };
        if (parsed?.detail) detail = parsed.detail;
      } catch {
        if (payload.trim()) detail = payload;
      }
      throw new Error(detail);
    }

    if (!payload.trim()) {
      return {} as T;
    }

    try {
      return JSON.parse(payload) as T;
    } catch {
      throw new Error(`Expected JSON response from ${endpoint}, but received non-JSON content.`);
    }
  }

  // Health
  async getHealth(): Promise<HealthResponse> {
    return this.request<HealthResponse>('/health');
  }

  // Profiles
  async createProfile(data: VoiceProfileCreate): Promise<VoiceProfileResponse> {
    return this.request<VoiceProfileResponse>('/profiles', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async listProfiles(): Promise<VoiceProfileResponse[]> {
    return this.request<VoiceProfileResponse[]>('/profiles');
  }

  async getProfile(profileId: string): Promise<VoiceProfileResponse> {
    return this.request<VoiceProfileResponse>(`/profiles/${profileId}`);
  }

  async updateProfile(profileId: string, data: VoiceProfileCreate): Promise<VoiceProfileResponse> {
    return this.request<VoiceProfileResponse>(`/profiles/${profileId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deleteProfile(profileId: string): Promise<void> {
    await this.request<void>(`/profiles/${profileId}`, {
      method: 'DELETE',
    });
  }

  async addProfileSample(
    profileId: string,
    file: File,
  referenceText: string,
  ): Promise<ProfileSampleResponse> {
    const url = `${this.getBaseUrl()}/profiles/${profileId}/samples`;
    const formData = new FormData();
    formData.append('file', file);
    formData.append('reference_text', referenceText);

    const response = await this.fetchWithAuth(url, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        detail: response.statusText,
      }));
      throw new Error(error.detail || `HTTP error! status: ${response.status}`);
    }

    return response.json();
  }

  async listProfileSamples(profileId: string): Promise<ProfileSampleResponse[]> {
    return this.request<ProfileSampleResponse[]>(`/profiles/${profileId}/samples`);
  }

  async deleteProfileSample(sampleId: string): Promise<void> {
    await this.request<void>(`/profiles/samples/${sampleId}`, {
      method: 'DELETE',
    });
  }

  async updateProfileSample(
    sampleId: string,
    referenceText: string,
  ): Promise<ProfileSampleResponse> {
    return this.request<ProfileSampleResponse>(`/profiles/samples/${sampleId}`, {
      method: 'PUT',
      body: JSON.stringify({ reference_text: referenceText }),
    });
  }

  async exportProfile(profileId: string): Promise<Blob> {
    const url = `${this.getBaseUrl()}/profiles/${profileId}/export`;
    const response = await this.fetchWithAuth(url);

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        detail: response.statusText,
      }));
      throw new Error(error.detail || `HTTP error! status: ${response.status}`);
    }

    return response.blob();
  }

  async importProfile(file: File): Promise<VoiceProfileResponse> {
    const url = `${this.getBaseUrl()}/profiles/import`;
    const formData = new FormData();
    formData.append('file', file);

    const response = await this.fetchWithAuth(url, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        detail: response.statusText,
      }));
      throw new Error(error.detail || `HTTP error! status: ${response.status}`);
    }

    return response.json();
  }

  async uploadAvatar(profileId: string, file: File): Promise<VoiceProfileResponse> {
    const url = `${this.getBaseUrl()}/profiles/${profileId}/avatar`;
    const formData = new FormData();
    formData.append('file', file);

    const response = await this.fetchWithAuth(url, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        detail: response.statusText,
      }));
      throw new Error(error.detail || `HTTP error! status: ${response.status}`);
    }

    return response.json();
  }

  async deleteAvatar(profileId: string): Promise<void> {
    await this.request<void>(`/profiles/${profileId}/avatar`, {
      method: 'DELETE',
    });
  }

  // Generation
  async generateSpeech(data: GenerationRequest): Promise<GenerationResponse> {
    return this.request<GenerationResponse>('/generate', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // History
  async listHistory(query?: HistoryQuery): Promise<HistoryListResponse> {
    const params = new URLSearchParams();
    if (query?.profile_id) params.append('profile_id', query.profile_id);
    if (query?.search) params.append('search', query.search);
    if (query?.limit) params.append('limit', query.limit.toString());
    if (query?.offset) params.append('offset', query.offset.toString());

    const queryString = params.toString();
    const endpoint = queryString ? `/history?${queryString}` : '/history';

    return this.request<HistoryListResponse>(endpoint);
  }

  async getGeneration(generationId: string): Promise<HistoryResponse> {
    return this.request<HistoryResponse>(`/history/${generationId}`);
  }

  async deleteGeneration(generationId: string): Promise<void> {
    await this.request<void>(`/history/${generationId}`, {
      method: 'DELETE',
    });
  }

  async exportGeneration(generationId: string): Promise<Blob> {
    const url = `${this.getBaseUrl()}/history/${generationId}/export`;
    const response = await this.fetchWithAuth(url);

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        detail: response.statusText,
      }));
      throw new Error(error.detail || `HTTP error! status: ${response.status}`);
    }

    return response.blob();
  }

  async exportGenerationAudio(generationId: string): Promise<Blob> {
    const url = `${this.getBaseUrl()}/history/${generationId}/export-audio`;
    const response = await this.fetchWithAuth(url);

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        detail: response.statusText,
      }));
      throw new Error(error.detail || `HTTP error! status: ${response.status}`);
    }

    return response.blob();
  }

  async importGeneration(file: File): Promise<{ id: string; profile_id: string; profile_name: string; text: string; message: string }> {
    const url = `${this.getBaseUrl()}/history/import`;
    const formData = new FormData();
    formData.append('file', file);

    const response = await this.fetchWithAuth(url, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        detail: response.statusText,
      }));
      throw new Error(error.detail || `HTTP error! status: ${response.status}`);
    }

    return response.json();
  }

  // Audio
  getAudioUrl(audioId: string): string {
    return this.buildAuthedUrl(`/audio/${audioId}`);
  }

  getSampleUrl(sampleId: string): string {
    return this.buildAuthedUrl(`/samples/${sampleId}`);
  }

  getProfileAvatarUrl(profileId: string): string {
    return this.buildAuthedUrl(`/profiles/${profileId}/avatar`);
  }

  getModelProgressSseUrl(modelName: string): string {
    return this.buildAuthedUrl(`/models/progress/${modelName}`);
  }

  // Transcription
  async transcribeAudio(file: File, language?: LanguageCode): Promise<TranscriptionResponse> {
    const formData = new FormData();
    formData.append('file', file);
    if (language) {
      formData.append('language', language);
    }

    const url = `${this.getBaseUrl()}/transcribe`;
    const response = await this.fetchWithAuth(url, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        detail: response.statusText,
      }));
      throw new Error(error.detail || `HTTP error! status: ${response.status}`);
    }

    return response.json();
  }

  // Model Management
  async getModelStatus(): Promise<ModelStatusListResponse> {
    return this.request<ModelStatusListResponse>('/models/status');
  }

  async triggerModelDownload(modelName: string): Promise<{ message: string }> {
    console.log('[API] triggerModelDownload called for:', modelName, 'at', new Date().toISOString());
    const result = await this.request<{ message: string }>('/models/download', {
      method: 'POST',
      body: JSON.stringify({ model_name: modelName } as ModelDownloadRequest),
    });
    console.log('[API] triggerModelDownload response:', result);
    return result;
  }

  async deleteModel(modelName: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/models/${modelName}`, {
      method: 'DELETE',
    });
  }

  // Task Management
  async getActiveTasks(): Promise<ActiveTasksResponse> {
    return this.request<ActiveTasksResponse>('/tasks/active');
  }

  // Audio Channels
  async listChannels(): Promise<
    Array<{
      id: string;
      name: string;
      is_default: boolean;
      device_ids: string[];
      created_at: string;
    }>
  > {
    return this.request('/channels');
  }

  async createChannel(data: {
    name: string;
    device_ids: string[];
  }): Promise<{
    id: string;
    name: string;
    is_default: boolean;
    device_ids: string[];
    created_at: string;
  }> {
    return this.request('/channels', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateChannel(
    channelId: string,
    data: {
      name?: string;
      device_ids?: string[];
    },
  ): Promise<{
    id: string;
    name: string;
    is_default: boolean;
    device_ids: string[];
    created_at: string;
  }> {
    return this.request(`/channels/${channelId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deleteChannel(channelId: string): Promise<{ message: string }> {
    return this.request(`/channels/${channelId}`, {
      method: 'DELETE',
    });
  }

  async getChannelVoices(channelId: string): Promise<{ profile_ids: string[] }> {
    return this.request(`/channels/${channelId}/voices`);
  }

  async setChannelVoices(
    channelId: string,
    profileIds: string[],
  ): Promise<{ message: string }> {
    return this.request(`/channels/${channelId}/voices`, {
      method: 'PUT',
      body: JSON.stringify({ profile_ids: profileIds }),
    });
  }

  async getProfileChannels(profileId: string): Promise<{ channel_ids: string[] }> {
    return this.request(`/profiles/${profileId}/channels`);
  }

  async setProfileChannels(
    profileId: string,
    channelIds: string[],
  ): Promise<{ message: string }> {
    return this.request(`/profiles/${profileId}/channels`, {
      method: 'PUT',
      body: JSON.stringify({ channel_ids: channelIds }),
    });
  }

  // Stories
  async listStories(): Promise<StoryResponse[]> {
    return this.request<StoryResponse[]>('/stories');
  }

  async createStory(data: StoryCreate): Promise<StoryResponse> {
    return this.request<StoryResponse>('/stories', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getStory(storyId: string): Promise<StoryDetailResponse> {
    return this.request<StoryDetailResponse>(`/stories/${storyId}`);
  }

  async updateStory(storyId: string, data: StoryCreate): Promise<StoryResponse> {
    return this.request<StoryResponse>(`/stories/${storyId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deleteStory(storyId: string): Promise<void> {
    await this.request<void>(`/stories/${storyId}`, {
      method: 'DELETE',
    });
  }

  async addStoryItem(storyId: string, data: StoryItemCreate): Promise<StoryItemDetail> {
    return this.request<StoryItemDetail>(`/stories/${storyId}/items`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async removeStoryItem(storyId: string, itemId: string): Promise<void> {
    await this.request<void>(`/stories/${storyId}/items/${itemId}`, {
      method: 'DELETE',
    });
  }

  async updateStoryItemTimes(storyId: string, data: StoryItemBatchUpdate): Promise<void> {
    await this.request<void>(`/stories/${storyId}/items/times`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async reorderStoryItems(storyId: string, data: StoryItemReorder): Promise<StoryItemDetail[]> {
    return this.request<StoryItemDetail[]>(`/stories/${storyId}/items/reorder`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async moveStoryItem(storyId: string, itemId: string, data: StoryItemMove): Promise<StoryItemDetail> {
    return this.request<StoryItemDetail>(`/stories/${storyId}/items/${itemId}/move`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async trimStoryItem(storyId: string, itemId: string, data: StoryItemTrim): Promise<StoryItemDetail> {
    return this.request<StoryItemDetail>(`/stories/${storyId}/items/${itemId}/trim`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async splitStoryItem(storyId: string, itemId: string, data: StoryItemSplit): Promise<StoryItemDetail[]> {
    return this.request<StoryItemDetail[]>(`/stories/${storyId}/items/${itemId}/split`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async duplicateStoryItem(storyId: string, itemId: string): Promise<StoryItemDetail> {
    return this.request<StoryItemDetail>(`/stories/${storyId}/items/${itemId}/duplicate`, {
      method: 'POST',
    });
  }

  async exportStoryAudio(storyId: string): Promise<Blob> {
    const url = `${this.getBaseUrl()}/stories/${storyId}/export-audio`;
    const response = await this.fetchWithAuth(url);

    if (!response.ok) {
      const error = await response.json().catch(() => ({
        detail: response.statusText,
      }));
      throw new Error(error.detail || `HTTP error! status: ${response.status}`);
    }

    return response.blob();
  }

  async listGroqModels(): Promise<GroqModelsResponse> {
    return this.request<GroqModelsResponse>('/llm/groq/models');
  }

  async composeStoryRoleplay(data: StoryComposeWithGroqRequest): Promise<StoryRenderJobResponse> {
    return this.request<StoryRenderJobResponse>('/stories/compose-roleplay', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async createStudioDraft(data: StudioDraftCreateRequest): Promise<StudioDraftResponse> {
    return this.request<StudioDraftResponse>('/studio/drafts', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async listStudioDrafts(storyId?: string): Promise<StudioDraftListItem[]> {
    const query = storyId ? `?story_id=${encodeURIComponent(storyId)}` : '';
    return this.request<StudioDraftListItem[]>(`/studio/drafts${query}`);
  }

  async getStudioDraft(draftId: string): Promise<StudioDraftDetailResponse> {
    return this.request<StudioDraftDetailResponse>(`/studio/drafts/${draftId}`);
  }

  async updateStudioDraftLines(
    draftId: string,
    data: StudioDraftLinesUpdateRequest,
  ): Promise<StudioDraftDetailResponse> {
    return this.request<StudioDraftDetailResponse>(`/studio/drafts/${draftId}/lines`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async generateStudioLinePreview(
    draftId: string,
    lineId: string,
  ): Promise<StudioPreviewResponse> {
    return this.request<StudioPreviewResponse>(`/studio/drafts/${draftId}/lines/${lineId}/preview`, {
      method: 'POST',
    });
  }

  getStudioLinePreviewUrl(draftId: string, lineId: string): string {
    return this.buildAuthedUrl(`/studio/drafts/${draftId}/lines/${lineId}/preview/audio`);
  }

  async renderStudioDraftFinal(draftId: string): Promise<StudioRenderFinalResponse> {
    return this.request<StudioRenderFinalResponse>(`/studio/drafts/${draftId}/render-final`, {
      method: 'POST',
    });
  }
}

export const apiClient = new ApiClient();
