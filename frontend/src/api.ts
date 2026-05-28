import axios from 'axios';

export const api = axios.create({
  baseURL: '',
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: string;
  created_at?: string;
  updated_at?: string;
}

export interface ArtifactItem {
  id: string;
  chat_id: string;
  filename: string;
  content_type: string;
  file_size: number;
  source: string;
  created_at: string;
  preview_url?: string | null;
}

export const login = async (email: string, password: string) => {
  const params = new URLSearchParams();
  params.append('username', email);
  params.append('password', password);
  return api.post('/auth/login', params, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
};

export const register = async (email: string, name: string, password: string) => {
  return api.post('/auth/register', { email, name, password });
};

export const getMe = async () => {
  return api.get<AuthUser>('/auth/me');
};

export const updateProfile = async (name: string) => {
  return api.patch<AuthUser>('/auth/me/profile', { name });
};

export const changePassword = async (
  currentPassword: string,
  newPassword: string
) => {
  return api.post('/auth/me/password', {
    current_password: currentPassword,
    new_password: newPassword,
  });
};

export const getSessions = async (userId: string) => {
  const response = await api.get(`/chat/sessions/${userId}`);
  return response.data as string[];
};

export const deleteSession = async (userId: string, sessionId: string) => {
  return api.delete(`/chat/sessions/${userId}/${sessionId}`);
};

export const getHistory = async (
  userId: string,
  sessionId: string,
  includeReasoning: boolean
) => {
  const response = await api.get(`/chat/history/${userId}/${sessionId}`, {
    params: { include_reasoning: includeReasoning },
  });
  return response.data;
};

export const listArtifacts = async (sessionId: string) => {
  const response = await api.get<ArtifactItem[]>(`/artifacts/${sessionId}`);
  return response.data;
};

export const uploadArtifact = async (sessionId: string, file: File) => {
  const form = new FormData();
  form.append('file', file);
  const response = await api.post<ArtifactItem>(`/artifacts/${sessionId}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

export const deleteArtifact = async (sessionId: string, artifactId: string) => {
  return api.delete(`/artifacts/${sessionId}/${artifactId}`);
};

export const getArtifactDownloadUrl = (sessionId: string, artifactId: string) => {
  return `/artifacts/${sessionId}/${artifactId}/download`;
};

export interface ChatRequestPayload {
  query: string;
  user_id: string;
  session_id: string | null;
  include_reasoning: boolean;
  images: string[] | null;
  csv_data: string | null;
  artifact_ids: string[] | null;
}

export interface ChatResponsePayload {
  response: string;
  session_id: string;
  message_id: string;
}

export const sendChatMessage = async (payload: ChatRequestPayload) => {
  const response = await api.post<ChatResponsePayload>('/chat/', payload);
  return response.data;
};

export async function downloadArtifact(
  sessionId: string,
  artifactId: string,
  filename: string
): Promise<void> {
  const response = await api.get(
    `/artifacts/${sessionId}/${artifactId}/download`,
    { responseType: 'blob' }
  );
  const url = URL.createObjectURL(response.data);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function getChatWebSocketUrl(): string {
  const apiTarget = import.meta.env.VITE_DEV_API_TARGET as string | undefined
  if (apiTarget) {
    const wsBase = apiTarget.replace(/^http/, 'ws')
    return `${wsBase}/chat/ws`
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/chat/ws`
}
