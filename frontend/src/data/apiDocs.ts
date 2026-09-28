export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface ApiEndpoint {
  method: HttpMethod;
  path: string;
  summary: string;
  description?: string;
  requestBody?: string;
  queryParams?: string;
  responseBody?: string;
  statusCodes: string;
  notes?: string;
}

export interface ApiSection {
  id: string;
  title: string;
  description: string;
  basePath?: string;
  workInProgress?: boolean;
  endpoints: ApiEndpoint[];
}

export const API_VERSION = '0.1.0';

export const apiSections: ApiSection[] = [
  {
    id: 'overview',
    title: 'Overview',
    description:
      'SimCrew exposes a REST API under /api. All request and response bodies use JSON unless noted otherwise.',
    endpoints: [
      {
        method: 'GET',
        path: '/health',
        summary: 'Health check',
        description: 'Returns service health. Does not require authentication.',
        responseBody: '{ "status": "ok" }',
        statusCodes: '200 — service is healthy',
      },
    ],
  },
  {
    id: 'personas',
    title: 'Personas',
    description:
      'Synthetic users are defined by structured fields (identity, perspective, constraints, role_label). A system prompt is generated from those fields. Prompts must be approved before use in runs.',
    basePath: '/api/personas',
    endpoints: [
      {
        method: 'GET',
        path: '/api/personas',
        summary: 'List personas',
        description: 'Returns all personas, newest first.',
        responseBody: 'PersonaResponse[]',
        statusCodes: '200',
      },
      {
        method: 'POST',
        path: '/api/personas',
        summary: 'Create persona',
        requestBody: `{
  "name": "string (required, 1–255 chars)",
  "identity": "string (required)",
  "perspective": "string (required)",
  "constraints": "string (required)",
  "role_label": "string (required) — short role shown on persona cards, e.g. Junior dev"
}`,
        responseBody: 'PersonaResponse',
        statusCodes: '201 — created',
        notes: 'A system prompt is auto-generated. prompt_approved is false until explicitly approved.',
      },
      {
        method: 'GET',
        path: '/api/personas/{persona_id}',
        summary: 'Get persona',
        responseBody: 'PersonaResponse',
        statusCodes: '200 — found · 404 — not found',
      },
      {
        method: 'PUT',
        path: '/api/personas/{persona_id}',
        summary: 'Update persona',
        requestBody: 'Partial PersonaUpdate (name, role_label, identity, perspective, constraints, system_prompt)',
        responseBody: 'PersonaResponse',
        statusCodes: '200 — updated · 404 — not found',
        notes: 'Updating identity, perspective, constraints, or name resets prompt_approved to false.',
      },
      {
        method: 'DELETE',
        path: '/api/personas/{persona_id}',
        summary: 'Delete persona',
        statusCodes: '204 — deleted · 404 — not found',
      },
      {
        method: 'POST',
        path: '/api/personas/{persona_id}/generate-prompt',
        summary: 'Regenerate system prompt',
        description: 'Rebuilds the system prompt from the persona structured fields.',
        responseBody: 'PersonaResponse',
        statusCodes: '200 — regenerated · 404 — not found',
        notes: 'Sets prompt_approved to false.',
      },
      {
        method: 'POST',
        path: '/api/personas/{persona_id}/approve-prompt',
        summary: 'Approve system prompt',
        description: 'Marks the current system prompt as approved for use in runs.',
        responseBody: 'PersonaResponse',
        statusCodes: '200 — approved · 400 — no prompt to approve · 404 — not found',
      },
    ],
  },
  {
    id: 'journeys',
    title: 'Journeys',
    description:
      'Journeys are ordered sequences of phases. Each phase has a name and instructions the persona follows independently during a run.',
    basePath: '/api/journeys',
    endpoints: [
      {
        method: 'GET',
        path: '/api/journeys',
        summary: 'List journeys',
        responseBody: 'JourneyResponse[] (includes phases)',
        statusCodes: '200',
      },
      {
        method: 'POST',
        path: '/api/journeys',
        summary: 'Create journey',
        requestBody: '{ "name": "string (required)", "description": "string | null" }',
        responseBody: 'JourneyResponse',
        statusCodes: '201 — created',
      },
      {
        method: 'GET',
        path: '/api/journeys/{journey_id}',
        summary: 'Get journey',
        responseBody: 'JourneyResponse (includes phases)',
        statusCodes: '200 · 404',
      },
      {
        method: 'PUT',
        path: '/api/journeys/{journey_id}',
        summary: 'Update journey',
        requestBody: 'Partial JourneyUpdate (name, description)',
        responseBody: 'JourneyResponse',
        statusCodes: '200 · 404',
      },
      {
        method: 'DELETE',
        path: '/api/journeys/{journey_id}',
        summary: 'Delete journey',
        statusCodes: '204 · 404',
      },
      {
        method: 'POST',
        path: '/api/journeys/{journey_id}/phases',
        summary: 'Add phase',
        requestBody: '{ "name": "string (required)", "instructions": "string (required)" }',
        responseBody: 'JourneyPhaseResponse',
        statusCodes: '201 · 404 — journey not found',
        notes: 'Order is auto-assigned as max(existing orders) + 1.',
      },
      {
        method: 'PUT',
        path: '/api/journeys/{journey_id}/phases/{phase_id}',
        summary: 'Update phase',
        requestBody: 'Partial JourneyPhaseUpdate (name, instructions, order)',
        responseBody: 'JourneyPhaseResponse',
        statusCodes: '200 · 404',
        notes: 'Changing order shifts other phases to maintain a contiguous sequence.',
      },
      {
        method: 'DELETE',
        path: '/api/journeys/{journey_id}/phases/{phase_id}',
        summary: 'Delete phase',
        statusCodes: '204 · 404',
        notes: 'Remaining phases are renumbered to close the gap.',
      },
    ],
  },
  {
    id: 'environments',
    title: 'Environments',
    description:
      'Work in progress. List and read endpoints work today. Create, update, and delete return 503. Runs cannot assign a non-default environment yet.',
    basePath: '/api/environments',
    workInProgress: true,
    endpoints: [
      {
        method: 'GET',
        path: '/api/environments',
        summary: 'List environments',
        responseBody: 'EnvironmentResponse[]',
        statusCodes: '200',
      },
      {
        method: 'POST',
        path: '/api/environments',
        summary: 'Create environment (disabled — work in progress)',
        requestBody: '{ "name": "string (required)", "image": "string (required)", "description": "string | null" }',
        responseBody: 'Error detail',
        statusCodes: '503 — work in progress',
      },
      {
        method: 'GET',
        path: '/api/environments/{env_id}',
        summary: 'Get environment',
        responseBody: 'EnvironmentResponse',
        statusCodes: '200 · 404',
      },
      {
        method: 'PUT',
        path: '/api/environments/{env_id}',
        summary: 'Update environment (disabled — work in progress)',
        requestBody: 'Partial EnvironmentUpdate',
        responseBody: 'Error detail',
        statusCodes: '503 — work in progress',
      },
      {
        method: 'DELETE',
        path: '/api/environments/{env_id}',
        summary: 'Delete environment (disabled — work in progress)',
        statusCodes: '503 — work in progress',
      },
    ],
  },
  {
    id: 'runs',
    title: 'Runs',
    description:
      'Runs define and execute an evaluation. Creating a run starts orchestration in the background — one agent container per persona.',
    basePath: '/api/runs',
    endpoints: [
      {
        method: 'GET',
        path: '/api/runs',
        summary: 'List runs',
        responseBody: 'RunResponse[]',
        statusCodes: '200',
        notes: 'Run status values: pending, running, completed, failed, cancelled.',
      },
      {
        method: 'POST',
        path: '/api/runs',
        summary: 'Create run',
        description: 'Creates a run and begins orchestrated execution asynchronously.',
        requestBody: `{
  "name": "string (required, 1–255 chars)",
  "repo_url": "string (required) — git repository URL to evaluate",
  "journey_id": "uuid (required)",
  "persona_environments": [
    { "persona_id": "uuid", "environment_id": "uuid | null" }
  ],
  "model": "string (default: nvidia/nemotron-3-ultra-550b-a55b)",
  "config": "object (optional) — LLM provider overrides, timeouts, etc."
}`,
        responseBody: 'RunResponse',
        statusCodes: '201 — run created and started in background',
        notes: 'Set environment_id to null (or omit) to use the default agent image. One environment per persona per run.',
      },
      {
        method: 'GET',
        path: '/api/runs/{run_id}',
        summary: 'Get run detail',
        description: 'Full run state including per-persona progress, phase times, activity, and findings.',
        responseBody: 'RunDetailResponse (personas[], journey_phases[], score, status, …)',
        statusCodes: '200 · 404',
        notes: 'Score values: GREEN, YELLOW, RED. Reconciles stuck runs on read.',
      },
      {
        method: 'GET',
        path: '/api/runs/{run_id}/findings',
        summary: 'List run findings',
        description: 'All findings across every persona in the run.',
        responseBody: 'FindingResponse[]',
        statusCodes: '200 · 404',
        notes: 'Severity values: critical, high, medium, low, info.',
      },
      {
        method: 'DELETE',
        path: '/api/runs/{run_id}',
        summary: 'Delete run',
        description: 'Permanently deletes a run and its per-persona findings.',
        statusCodes: '204 — deleted · 404 — not found',
      },
    ],
  },
  {
    id: 'prompts',
    title: 'Prompts',
    description: 'Utility endpoint for previewing system prompts without persisting a persona.',
    basePath: '/api/prompts',
    endpoints: [
      {
        method: 'POST',
        path: '/api/prompts/generate',
        summary: 'Generate system prompt',
        requestBody: `{
  "name": "string",
  "identity": "string",
  "perspective": "string",
  "constraints": "string"
}`,
        responseBody: '{ "system_prompt": "string" }',
        statusCodes: '200',
      },
    ],
  },
  {
    id: 'agent',
    title: 'Agent API (internal)',
    description:
      'Each agent runs a separate FastAPI app on port 8080 inside its container. These endpoints are called by the orchestrator and agents — not intended for direct client use.',
    endpoints: [
      {
        method: 'GET',
        path: '/health',
        summary: 'Agent health check',
        responseBody: '{ "status": "ok" }',
        statusCodes: '200',
        notes: 'Orchestrator polls this before dispatching work.',
      },
      {
        method: 'POST',
        path: '/run',
        summary: 'Start agent evaluation',
        description: 'Accepts work asynchronously (202). Clones the repo and runs all journey phases.',
        requestBody: `{
  "persona": "object — persona fields including persona_id",
  "phases": "array — journey phase definitions",
  "repo_url": "string",
  "orchestrator_url": "string — base URL for callbacks",
  "model": "string",
  "config": "object",
  "git_credentials": "string | null — for private repos"
}`,
        responseBody: '{ "status": "accepted" }',
        statusCodes: '202 — work accepted',
      },
    ],
  },
  {
    id: 'agent-callbacks',
    title: 'Agent Callbacks (internal)',
    description:
      'Agents report progress back to the orchestrator during a run. Called on the orchestrator API.',
    basePath: '/api/runs/{run_id}',
    endpoints: [
      {
        method: 'POST',
        path: '/api/runs/{run_id}/status',
        summary: 'Report current phase',
        requestBody: '{ "persona_id": "string", "current_phase": "string" }',
        responseBody: '{ "status": "ok" }',
        statusCodes: '200 · 404',
        notes: 'Sets persona status to running and records phase transition timestamps.',
      },
      {
        method: 'POST',
        path: '/api/runs/{run_id}/progress',
        summary: 'Report incremental progress',
        requestBody: `{
  "persona_id": "string",
  "event_type": "phase_completed | finding | tool",
  "message": "string",
  "data": "object — event-specific payload"
}`,
        responseBody: '{ "status": "ok" }',
        statusCodes: '200 · 404',
        notes: 'phase_completed saves phase summary. finding persists deduplicated findings.',
      },
      {
        method: 'POST',
        path: '/api/runs/{run_id}/done',
        summary: 'Report persona finished',
        requestBody: `{
  "persona_id": "string",
  "status": "completed | blocked",
  "phase_summaries": "object",
  "findings": "array",
  "blocked_phase": "string | null",
  "blocked_reason": "string | null"
}`,
        responseBody: '{ "status": "ok" }',
        statusCodes: '200 · 404',
        notes: 'Finalizes run scoring when all personas reach a terminal state.',
      },
    ],
  },
];
