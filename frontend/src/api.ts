import axios, { isAxiosError } from 'axios'

type UnauthorizedHandler = () => void

let unauthorizedHandler: UnauthorizedHandler | null = null

export const api = axios.create({ baseURL: '' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (
      error &&
      typeof error === 'object' &&
      'response' in error &&
      (error as { response?: { status?: number } }).response?.status === 401
    ) {
      unauthorizedHandler?.()
    }
    return Promise.reject(error)
  }
)

/** Register auth expiry handling only after the initial auth check has completed. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler
}

export interface AuthUser {
  id: string
  email: string
  name: string
  role: string
  created_at?: string
  updated_at?: string
}

export type ArtifactSource = 'upload' | 'generated'
export type ArtifactOutputKind = 'png' | 'csv' | 'xlsx'

export interface ArtifactItem {
  id: string
  chat_id?: string
  filename: string
  content_type: string
  file_size: number
  source: ArtifactSource
  output_kind: ArtifactOutputKind | null
  sha256: string
  content_url: string
  download_url: string
  preview_url?: string | null
  dimensions?: { width: number; height: number } | null
  width?: number | null
  height?: number | null
  created_at?: string
}

export const login = async (email: string, password: string) => {
  const params = new URLSearchParams()
  params.append('username', email)
  params.append('password', password)
  return api.post('/auth/login', params, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
}

export const register = async (email: string, name: string, password: string) =>
  api.post('/auth/register', { email, name, password })

export const getMe = async () => api.get<AuthUser>('/auth/me')
export const updateProfile = async (name: string) =>
  api.patch<AuthUser>('/auth/me/profile', { name })
export const changePassword = async (currentPassword: string, newPassword: string) =>
  api.post('/auth/me/password', {
    current_password: currentPassword,
    new_password: newPassword,
  })

export interface SessionSummary {
  session_id: string
  deletion_pending: boolean
}

export const getSessions = async (signal?: AbortSignal) => {
  const response = await api.get<SessionSummary[]>('/chat/sessions', { signal })
  return response.data
}

export const createSession = async () => {
  const response = await api.post<SessionSummary>('/chat/sessions')
  return response.data
}

export const deleteSession = async (sessionId: string) => {
  const response = await api.delete<{ status: 'deleted' | 'pending' }>(
    `/chat/sessions/${sessionId}`
  )
  return response.data
}

export const getHistory = async (
  sessionId: string,
  signal?: AbortSignal
) => {
  const response = await api.get(`/chat/history/${sessionId}`, {
    signal,
  })
  return response.data
}

export const listArtifacts = async (sessionId: string, signal?: AbortSignal) => {
  const response = await api.get<ArtifactItem[]>(`/artifacts/${sessionId}`, { signal })
  return response.data
}

export const uploadArtifact = async (sessionId: string, file: File) => {
  const form = new FormData()
  form.append('file', file)
  const response = await api.post<ArtifactItem>(`/artifacts/${sessionId}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return response.data
}

export const deleteArtifact = async (sessionId: string, artifactId: string) =>
  api.delete(`/artifacts/${sessionId}/${artifactId}`)

export interface ChatRequestPayload {
  request_id: string
  query: string
  session_id: string | null
}

export interface ChatResponsePayload {
  run_id: string
  request_id: string
  session_id: string
  final_answer?: string | null
  response?: string | null
  message_id?: string | null
  generated_artifact_ids: string[]
  artifacts?: ArtifactItem[]
  status: 'running' | 'in_progress' | 'completed' | 'failed'
}

export const sendChatMessage = async (payload: ChatRequestPayload) => {
  const response = await api.post<ChatResponsePayload>('/chat/', payload)
  return response.data
}

export const getChatRun = async (requestId: string) => {
  const response = await api.get<ChatResponsePayload>(`/chat/runs/${requestId}`)
  return response.data
}

export const createWebSocketTicket = async (): Promise<string> => {
  const response = await api.post<{ ticket: string }>('/auth/ws-ticket')
  return response.data.ticket
}

/** Only server-issued, same-origin artifact routes may be fetched with credentials. */
export function safeArtifactEndpoint(value: string): string {
  const parsed = new URL(value, window.location.origin)
  if (parsed.origin !== window.location.origin || !parsed.pathname.startsWith('/artifacts/')) {
    throw new Error('Unsafe artifact URL')
  }
  return `${parsed.pathname}${parsed.search}`
}

export async function fetchArtifactBlob(
  contentUrl: string,
  signal?: AbortSignal
): Promise<Blob> {
  const response = await api.get<Blob>(safeArtifactEndpoint(contentUrl), {
    responseType: 'blob',
    signal,
  })
  return response.data
}

export interface TableArtifactPreview {
  kind: 'table'
  columns: string[]
  rows: unknown[][]
  sheet_names: string[] | null
  selected_sheet: string | null
  truncated: boolean
}

export interface TextArtifactPreview {
  kind: 'text'
  text: string
  truncated: boolean
  metadata: Record<string, unknown>
}

export type StructuredArtifactPreview = TableArtifactPreview | TextArtifactPreview

export async function fetchArtifactPreview(
  artifact: ArtifactItem,
  signal?: AbortSignal
): Promise<Blob | StructuredArtifactPreview> {
  if (!artifact.preview_url) throw new Error('Preview is unavailable')
  if (artifact.content_type.startsWith('image/')) {
    return fetchArtifactBlob(artifact.preview_url, signal)
  }
  const response = await api.get<StructuredArtifactPreview>(
    safeArtifactEndpoint(artifact.preview_url),
    { signal }
  )
  return response.data
}

export async function downloadArtifact(artifact: ArtifactItem): Promise<void> {
  const response = await api.get<Blob>(safeArtifactEndpoint(artifact.download_url), {
    responseType: 'blob',
  })
  const url = URL.createObjectURL(response.data)
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = artifact.filename
    anchor.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}

export type ClientErrorCode = 'upload_too_large' | 'unsupported_file_type' | 'request_failed'

export function getClientError(error: unknown): { code: ClientErrorCode; message: string } {
  if (isAxiosError(error)) {
    const body = error.response?.data
    const detail = body && typeof body === 'object' ? body.detail : undefined
    const code: unknown = body?.code ?? (detail && typeof detail === 'object' ? detail.code : undefined)
    if (error.response?.status === 413 || code === 'upload_too_large') {
      return { code: 'upload_too_large', message: 'The file exceeds the 50 MiB upload limit.' }
    }
    if (error.response?.status === 415 || code === 'unsupported_file_type') {
      return { code: 'unsupported_file_type', message: 'Only CSV and XLSX files are supported.' }
    }
    const message: unknown = body?.message ??
      (detail && typeof detail === 'object' ? detail.message : detail)
    if (typeof message === 'string' && message.trim()) {
      return { code: 'request_failed', message }
    }
  }
  return { code: 'request_failed', message: 'The operation failed. Please try again.' }
}

export function isNotFound(error: unknown): boolean {
  return isAxiosError(error) && error.response?.status === 404
}

export function getChatWebSocketUrl(ticket: string): string {
  const apiTarget = import.meta.env.VITE_DEV_API_TARGET as string | undefined
  let base: string
  if (apiTarget) {
    base = `${apiTarget.replace(/^http/, 'ws')}/chat/ws`
  } else {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    base = `${protocol}//${window.location.host}/chat/ws`
  }
  const url = new URL(base)
  url.searchParams.set('ticket', ticket)
  return url.toString()
}
