import axios from 'axios';

const API_BASE_URL = '';

export const api = axios.create({
  baseURL: API_BASE_URL,
});

export const login = async (data: any) => {
    return api.post('/auth/login', { username: data.username, password: data.password });
}

export const register = async (data: any) => {
    return api.post('/auth/register', data);
}

export const getSessions = async (userId: string) => {
  const response = await api.get(`/chat/sessions/${userId}`);
  return response.data as string[];
};

export const deleteSession = async (userId: string, sessionId: string) => {
  return api.delete(`/chat/sessions/${userId}/${sessionId}`);
};

export const getHistory = async (userId: string, sessionId: string, includeReasoning: boolean) => {
  const response = await api.get(`/chat/history/${userId}/${sessionId}`, {
    params: { include_reasoning: includeReasoning }
  });
  return response.data;
};
