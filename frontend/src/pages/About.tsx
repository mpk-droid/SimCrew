import { PublicRepoDisclaimerBanner } from '../components/PublicRepoDisclaimerBanner';

export default function About() {
  return (
    <div className="page about-page">
      <div className="page-header">
        <h2>About</h2>
      </div>
      <PublicRepoDisclaimerBanner />

      <section className="about-section card">
        <h3>What is SimCrew?</h3>
        <p>
          SimCrew runs AI-powered developer personas against your software — typically a
          git repository — and reports developer experience (DX) findings the way a real team
          member would.
        </p>
        <p>
          You define <strong>personas</strong> (who is evaluating), a <strong>journey</strong>{' '}
          (what steps they follow), and a <strong>repository URL</strong>. The platform spins up
          one isolated agent per persona. Each agent clones the repo, works through every journey
          phase independently, and reports findings back to the orchestrator.
        </p>
      </section>

      <section className="about-section card">
        <h3>Why use it?</h3>
        <ul className="about-list">
          <li>
            <strong>Catch DX issues early</strong> — broken READMEs, missing files, confusing setup,
            security smells — before real users hit them.
          </li>
          <li>
            <strong>Multiple perspectives</strong> — different personas (novice vs expert, ops vs
            app dev) surface different classes of problems in the same run.
          </li>
          <li>
            <strong>Repeatable evaluations</strong> — the same journey against a new commit gives
            comparable results run over run.
          </li>
          <li>
            <strong>Actionable output</strong> — findings include severity, evidence, file
            references, and suggestions; runs receive an overall GREEN / YELLOW / RED score.
          </li>
        </ul>
      </section>

      <section className="about-section card">
        <h3>How a run works</h3>
        <ol className="about-steps">
          <li>
            <strong>Configure</strong> — Create or select personas and a journey. Per-persona
            environments are planned but not available yet (work in progress).
          </li>
          <li>
            <strong>Start a run</strong> — Provide a repository URL, choose personas, and start orchestration.
          </li>
          <li>
            <strong>Agents execute</strong> — Each persona runs in its own container: clone repo →
            LLM tool-use loop per phase → report progress and findings.
          </li>
          <li>
            <strong>Aggregate</strong> — The orchestrator deduplicates findings across personas,
            scores the run.
          </li>
          <li>
            <strong>Review</strong> — Use the run detail view for per-persona timelines, phase
            summaries, and findings on each run detail page.
          </li>
        </ol>
      </section>

      <section className="about-section card">
        <h3>Core concepts</h3>
        <dl className="about-glossary">
          <div>
            <dt>Persona</dt>
            <dd>
              A synthetic developer defined by identity, perspective, constraints, and role label
              level. A system prompt is generated and must be approved before runs.
            </dd>
          </div>
          <div>
            <dt>Journey</dt>
            <dd>
              An ordered list of phases (e.g. README check, local setup, deployment). Each phase
              has instructions the persona follows independently.
            </dd>
          </div>
          <div>
            <dt>Run</dt>
            <dd>
              A run is an evaluation against a repository: chosen personas, journey, repo URL,
              and model. Starting a run launches one agent container per persona.
            </dd>
          </div>
          <div>
            <dt>Environment</dt>
            <dd>
              <span className="badge badge--wip">Work in progress</span>
              Planned: per-persona container images (e.g. Mac-like vs Linux-like developer
              laptops). Not available in the UI yet — runs use the default agent image.
            </dd>
          </div>
          <div>
            <dt>Finding</dt>
            <dd>
              A single issue reported by a persona: severity, category, title, description,
              evidence, and optional file location. Verified findings require supporting evidence
              from the repo.
            </dd>
          </div>
        </dl>
      </section>

      <section className="about-section card">
        <h3>Architecture (simplified)</h3>
        <pre className="about-diagram">{`┌─────────────────────────────────────────────┐
│  Orchestrator (this UI + API)               │
│  · manages runs, personas, journeys         │
│  · spawns agent containers                  │
│  · collects findings, scores runs           │
└──────────────┬──────────────────────────────┘
               │ one container per persona
       ┌───────┴───────┐
       ▼               ▼
  ┌─────────┐    ┌─────────┐
  │ Agent   │    │ Agent   │   clone repo → LLM + tools → callbacks
  │ (Priya) │    │ (Sam)   │
  └─────────┘    └─────────┘`}</pre>
        <p>
          Agents run sandboxed with an allowlisted tool set (read files, run commands, etc.).
          Evidence verification prevents findings that are not backed by repository content.
        </p>
      </section>

      <section className="about-section card">
        <h3>Built-in fixtures</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>Fixture</th>
              <th>Use when</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Smoke Test</td>
              <td>
                Fast validation — Alex (Test), Blake (Test), Casey (Test) with the 4-phase
                Smoke Test Journey and demo-service repo. Use for CI, UI, and integration testing.
              </td>
            </tr>
            <tr>
              <td>DX Evaluation</td>
              <td>
                Full developer-experience evaluation — Priya, Sam, Dana, Kai with the 5-phase DX
                Evaluation Journey covering setup through deployment.
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  );
}
