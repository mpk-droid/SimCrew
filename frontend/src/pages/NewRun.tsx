import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import { getPersonas, getJourneys, getEnvironments, createRun } from '../api/client';
import type { PersonaEnvironmentSpec } from '../types';
import { PublicRepoDisclaimerBanner } from '../components/PublicRepoDisclaimerBanner';
import { personaShortName } from '../utils/personaDisplay';

export default function NewRun() {
  const navigate = useNavigate();

  const { data: personas } = useQuery({
    queryKey: ['personas'],
    queryFn: getPersonas,
  });

  const { data: journeys } = useQuery({
    queryKey: ['journeys'],
    queryFn: getJourneys,
  });

  const { data: environments } = useQuery({
    queryKey: ['environments'],
    queryFn: getEnvironments,
  });

  const [form, setForm] = useState({
    name: '',
    repo_url: '',
    journey_id: '',
    model: 'nvidia/nemotron-3-ultra-550b-a55b',
  });

  const [personaEnvs, setPersonaEnvs] = useState<Record<string, string>>({});

  const togglePersona = (personaId: string) => {
    setPersonaEnvs((prev) => {
      const next = { ...prev };
      if (personaId in next) {
        delete next[personaId];
      } else {
        next[personaId] = '';
      }
      return next;
    });
  };

  const buildPersonaEnvironments = (): PersonaEnvironmentSpec[] => {
    return Object.entries(personaEnvs).map(([persona_id, environment_id]) => ({
      persona_id,
      environment_id: environment_id || null,
    }));
  };

  const createMutation = useMutation({
    mutationFn: () =>
      createRun({
        name: form.name,
        repo_url: form.repo_url,
        persona_environments: buildPersonaEnvironments(),
        journey_id: form.journey_id,
        model: form.model,
      }),
    onSuccess: (run) => {
      navigate(`/runs/${run.id}`);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    createMutation.mutate();
  };

  const selectedPersonaCount = Object.keys(personaEnvs).length;
  const isValid = form.name && selectedPersonaCount > 0 && form.journey_id && form.repo_url;

  return (
    <div className="page">
      <div className="page-header">
        <h2>New Run</h2>
      </div>
      <PublicRepoDisclaimerBanner />

      <form className="form" onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="name">Run Name</label>
          <input
            id="name"
            type="text"
            value={form.name}
            onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
            placeholder="e.g., Eval run for my-app v2.1"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="repo_url">Repository URL</label>
          <input
            id="repo_url"
            type="text"
            value={form.repo_url}
            onChange={(e) => setForm((p) => ({ ...p, repo_url: e.target.value }))}
            placeholder="https://github.com/org/repo.git"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="journey">Journey</label>
          <select
            id="journey"
            value={form.journey_id}
            onChange={(e) => setForm((p) => ({ ...p, journey_id: e.target.value }))}
            required
          >
            <option value="">Select a journey...</option>
            {journeys?.map((j) => (
              <option key={j.id} value={j.id}>
                {j.name} ({j.phases.length} phases)
              </option>
            ))}
          </select>
        </div>

        <div className="form-group">
          <label htmlFor="model">Model</label>
          <input
            id="model"
            type="text"
            value={form.model}
            disabled
            readOnly
            className="input--disabled"
          />
        </div>

        <div className="form-group">
          <label>Personas</label>
          <p className="form-hint">
            Select personas for this run, and optionally an environment (the machine image
            each persona's agent runs in). Default is the standard agent image.
          </p>
          <div className="persona-checkbox-grid">
            {personas?.map((p) => {
              const isSelected = p.id in personaEnvs;
              return (
                <div
                  key={p.id}
                  className={`checkbox-card ${isSelected ? 'checkbox-card--selected' : ''}`}
                >
                  <label className="checkbox-card-label">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => togglePersona(p.id)}
                    />
                    <div className="checkbox-card-content">
                      <strong>{personaShortName(p.name)}</strong>
                      <span className="checkbox-card-meta">{p.role_label}</span>
                    </div>
                  </label>
                  <div className="persona-env-select">
                    <label htmlFor={`env-${p.id}`}>Environment</label>
                    <select
                      id={`env-${p.id}`}
                      value={personaEnvs[p.id] ?? ''}
                      disabled={!isSelected}
                      title={isSelected ? undefined : 'Select the persona first'}
                      onChange={(e) =>
                        setPersonaEnvs((prev) => ({ ...prev, [p.id]: e.target.value }))
                      }
                    >
                      <option value="">Default</option>
                      {environments?.map((env) => (
                        <option key={env.id} value={env.id}>
                          {env.name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              );
            })}
          </div>
          {personas?.length === 0 && (
            <p className="empty-state">No personas available. Create some first.</p>
          )}
        </div>

        <div className="form-actions">
          <button
            type="submit"
            className="btn btn--primary"
            disabled={createMutation.isPending || !isValid}
          >
            {createMutation.isPending ? 'Starting...' : 'Start Run'}
          </button>
        </div>
        {createMutation.isError && (
          <p className="error">Failed to create run: {(createMutation.error as Error).message}</p>
        )}
      </form>
    </div>
  );
}
