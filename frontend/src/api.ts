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
  role: string;
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

export const register = async (email: string, password: string) => {
  return api.post('/auth/register', { email, password });
};

export const getMe = async () => {
  return api.get<AuthUser>('/auth/me');
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
