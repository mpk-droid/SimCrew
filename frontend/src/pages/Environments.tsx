import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createEnvironment,
  deleteEnvironment,
  getEnvironments,
  updateEnvironment,
} from '../api/client';
import type { EnvironmentCreate, EnvironmentResponse } from '../types';

const EXAMPLE_DOCKERFILE =
  'https://github.com/mpk-droid/SimCrew/blob/main/examples/environment/Dockerfile';

const EMPTY: EnvironmentCreate = { name: '', image: '', description: '' };

export default function Environments() {
  const queryClient = useQueryClient();
  const { data: environments, isLoading } = useQuery({
    queryKey: ['environments'],
    queryFn: getEnvironments,
  });

  // null: form closed, 'new': creating, otherwise the id being edited.
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<EnvironmentCreate>(EMPTY);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['environments'] });

  const save = useMutation({
    mutationFn: () => {
      const data = { ...form, description: form.description?.trim() || null };
      return editing === 'new'
        ? createEnvironment(data)
        : updateEnvironment(editing as string, data);
    },
    onSuccess: () => {
      setEditing(null);
      refresh();
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteEnvironment(id),
    onSuccess: refresh,
  });

  const open = (env?: EnvironmentResponse) => {
    save.reset();
    setEditing(env ? env.id : 'new');
    setForm(
      env
        ? { name: env.name, image: env.image, description: env.description ?? '' }
        : EMPTY,
    );
  };

  const onDelete = (env: EnvironmentResponse) => {
    if (window.confirm(`Delete environment "${env.name}"?`)) remove.mutate(env.id);
  };

  if (isLoading) return <p className="loading">Loading environments...</p>;

  return (
    <div className="page">
      <div className="page-header">
        <h2>Environments</h2>
        {editing === null && (
          <button className="btn btn--primary" onClick={() => open()}>
            New Environment
          </button>
        )}
      </div>

      <p className="form-hint">
        An environment is the container image a persona's agent runs in, for example a
        machine with Go or Java installed. Build it <code>FROM ghcr.io/mpk-droid/simcrew</code>{' '}
        so it still runs the SimCrew agent (
        <a href={EXAMPLE_DOCKERFILE} target="_blank" rel="noreferrer">
          example Dockerfile
        </a>
        ), push it somewhere SimCrew can pull from, then pick it per persona on New Run.
        Personas without one use the default agent image.
      </p>

      {editing !== null && (
        <form
          className="form card"
          style={{ padding: '20px', marginTop: '16px' }}
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="form-group">
            <label htmlFor="env-name">Name</label>
            <input
              id="env-name"
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g., Fedora + Go"
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="env-image">Container image</label>
            <input
              id="env-image"
              type="text"
              value={form.image}
              onChange={(e) => setForm({ ...form, image: e.target.value })}
              placeholder="e.g., quay.io/your-org/simcrew-fedora-go:latest"
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="env-description">Description</label>
            <input
              id="env-description"
              type="text"
              value={form.description ?? ''}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="e.g., Fedora 40 with Go 1.23 installed"
            />
            <p className="form-hint">
              Optional. Personas see it as &ldquo;Your machine: &hellip;&rdquo; in their prompt.
            </p>
          </div>
          <div className="form-actions">
            <button type="submit" className="btn btn--primary" disabled={save.isPending}>
              {save.isPending ? 'Saving...' : editing === 'new' ? 'Create' : 'Save'}
            </button>
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => setEditing(null)}
            >
              Cancel
            </button>
          </div>
          {save.isError && <p className="error">{(save.error as Error).message}</p>}
        </form>
      )}

      {remove.isError && <p className="error">{(remove.error as Error).message}</p>}

      {environments && environments.length > 0 ? (
        <div className="card-grid" style={{ marginTop: '16px' }}>
          {environments.map((env) => (
            <div key={env.id} className="card" style={{ padding: '20px' }}>
              <h3>{env.name}</h3>
              <code style={{ fontSize: '13px', wordBreak: 'break-all' }}>{env.image}</code>
              {env.description && (
                <p className="form-hint" style={{ marginTop: '8px' }}>
                  {env.description}
                </p>
              )}
              {env.is_builtin ? (
                <p className="form-hint" style={{ marginTop: '8px' }}>
                  Built-in
                </p>
              ) : (
                <div className="form-actions" style={{ marginTop: '12px' }}>
                  <button className="btn btn--secondary" onClick={() => open(env)}>
                    Edit
                  </button>
                  <button
                    className="btn btn--danger-text"
                    onClick={() => onDelete(env)}
                    disabled={remove.isPending}
                  >
                    Delete
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        editing === null && (
          <p className="empty-state">
            No environments yet. Every persona uses the default agent image.
          </p>
        )
      )}
    </div>
  );
}
