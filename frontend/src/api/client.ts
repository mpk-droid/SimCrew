import type {
  PersonaResponse,
  PersonaCreate,
  PersonaUpdate,
  EnvironmentResponse,
  EnvironmentCreate,
  JourneyResponse,
  JourneyCreate,
  JourneyUpdate,
  JourneyPhaseResponse,
  JourneyPhaseCreate,
  JourneyPhaseUpdate,
  RunCreate,
  RunResponse,
  RunDetailResponse,
} from '../types';

function errorDetail(text: string): string | null {
  try {
    const { detail } = JSON.parse(text);
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((d) => d.msg).join('; ');
  } catch {
    // not JSON
  }
  return null;
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(errorDetail(text) || `${res.status} ${res.statusText}: ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// --- Personas ---

export function getPersonas(): Promise<PersonaResponse[]> {
  return request('/api/personas');
}

export function getPersona(id: string): Promise<PersonaResponse> {
  return request(`/api/personas/${id}`);
}

export function createPersona(data: PersonaCreate): Promise<PersonaResponse> {
  return request('/api/personas', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function updatePersona(id: string, data: PersonaUpdate): Promise<PersonaResponse> {
  return request(`/api/personas/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export function deletePersona(id: string): Promise<void> {
  return request(`/api/personas/${id}`, { method: 'DELETE' });
}

export function generatePersonaPrompt(id: string): Promise<PersonaResponse> {
  return request(`/api/personas/${id}/generate-prompt`, { method: 'POST' });
}

export function approvePersonaPrompt(id: string): Promise<PersonaResponse> {
  return request(`/api/personas/${id}/approve-prompt`, { method: 'POST' });
}

// --- Journeys ---

export function getJourneys(): Promise<JourneyResponse[]> {
  return request('/api/journeys');
}

export function getJourney(id: string): Promise<JourneyResponse> {
  return request(`/api/journeys/${id}`);
}

export function createJourney(data: JourneyCreate): Promise<JourneyResponse> {
  return request('/api/journeys', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function updateJourney(id: string, data: JourneyUpdate): Promise<JourneyResponse> {
  return request(`/api/journeys/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export function deleteJourney(id: string): Promise<void> {
  return request(`/api/journeys/${id}`, { method: 'DELETE' });
}

export function createJourneyPhase(journeyId: string, data: JourneyPhaseCreate): Promise<JourneyPhaseResponse> {
  return request(`/api/journeys/${journeyId}/phases`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function updateJourneyPhase(journeyId: string, phaseId: string, data: JourneyPhaseUpdate): Promise<JourneyPhaseResponse> {
  return request(`/api/journeys/${journeyId}/phases/${phaseId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export function deleteJourneyPhase(journeyId: string, phaseId: string): Promise<void> {
  return request(`/api/journeys/${journeyId}/phases/${phaseId}`, { method: 'DELETE' });
}

// --- Runs ---

export function getRuns(): Promise<RunResponse[]> {
  return request('/api/runs');
}

export function createRun(data: RunCreate): Promise<RunResponse> {
  return request('/api/runs', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function getRunDetail(runId: string): Promise<RunDetailResponse> {
  return request(`/api/runs/${runId}`);
}

export function cancelRun(runId: string): Promise<{ status: string }> {
  return request(`/api/runs/${runId}/cancel`, { method: 'POST' });
}

export function deleteRun(runId: string): Promise<void> {
  return request(`/api/runs/${runId}`, { method: 'DELETE' });
}

// --- Prompts ---

export function generatePrompt(data: {
  identity: string;
  perspective: string;
  constraints: string;
}): Promise<{ system_prompt: string }> {
  return request('/api/prompts/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

// --- Environments ---

export function getEnvironments(): Promise<EnvironmentResponse[]> {
  return request('/api/environments');
}

export function createEnvironment(data: EnvironmentCreate): Promise<EnvironmentResponse> {
  return request('/api/environments', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function deleteEnvironment(id: string): Promise<void> {
  return request(`/api/environments/${id}`, { method: 'DELETE' });
}
