import { useState } from 'react';
import { apiSections, type ApiEndpoint, type HttpMethod } from '../data/apiDocs';
import { PublicRepoDisclaimerBanner } from '../components/PublicRepoDisclaimerBanner';
import { WorkInProgressBanner } from '../components/WorkInProgressBanner';

const methodClass: Record<HttpMethod, string> = {
  GET: 'api-method--get',
  POST: 'api-method--post',
  PUT: 'api-method--put',
  PATCH: 'api-method--patch',
  DELETE: 'api-method--delete',
};

function EndpointCard({ endpoint }: { endpoint: ApiEndpoint }) {
  return (
    <article className="api-endpoint card">
      <div className="api-endpoint__header">
        <span className={`api-method ${methodClass[endpoint.method]}`}>{endpoint.method}</span>
        <code className="api-endpoint__path">{endpoint.path}</code>
      </div>
      <h4 className="api-endpoint__summary">{endpoint.summary}</h4>
      {endpoint.description && <p className="api-endpoint__desc">{endpoint.description}</p>}
      {endpoint.queryParams && (
        <div className="api-block">
          <span className="api-block__label">Query parameters</span>
          <pre className="api-block__code">{endpoint.queryParams}</pre>
        </div>
      )}
      {endpoint.requestBody && (
        <div className="api-block">
          <span className="api-block__label">Request body</span>
          <pre className="api-block__code">{endpoint.requestBody}</pre>
        </div>
      )}
      {endpoint.responseBody && (
        <div className="api-block">
          <span className="api-block__label">Response</span>
          <pre className="api-block__code">{endpoint.responseBody}</pre>
        </div>
      )}
      <div className="api-block">
        <span className="api-block__label">Status codes</span>
        <p className="api-endpoint__status">{endpoint.statusCodes}</p>
      </div>
      {endpoint.notes && <p className="api-endpoint__notes">{endpoint.notes}</p>}
    </article>
  );
}

export default function ApiDocs() {
  const [activeSection, setActiveSection] = useState(apiSections[0].id);
  const section = apiSections.find((s) => s.id === activeSection) ?? apiSections[0];

  return (
    <div className="page docs-page">
      <div className="page-header">
        <h2>API Docs</h2>
      </div>

      <PublicRepoDisclaimerBanner />

      <div className="docs-intro card">
        <p>
          REST API for SimCrew. All <code>/api</code> endpoints accept and return{' '}
          <code>application/json</code>.
        </p>
        <dl className="docs-meta">
          <div>
            <dt>Base URL</dt>
            <dd><code>{window.location.origin}</code></dd>
          </div>
          <div>
            <dt>Authentication</dt>
            <dd>None (single-tenant deployments). Treat network access as the security boundary.</dd>
          </div>
          <div>
            <dt>Interactive reference</dt>
            <dd>
              <a href="/docs" target="_blank" rel="noreferrer">OpenAPI (Swagger)</a>
              {' · '}
              <a href="/redoc" target="_blank" rel="noreferrer">ReDoc</a>
            </dd>
          </div>
          <div>
            <dt>Errors</dt>
            <dd>
              <code>404</code> resource not found · <code>400</code> validation error ·{' '}
              <code>422</code> malformed request body
            </dd>
          </div>
        </dl>
      </div>

      <div className="docs-layout">
        <nav className="docs-toc card" aria-label="API sections">
          {apiSections.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`docs-toc__item${s.id === activeSection ? ' docs-toc__item--active' : ''}`}
              onClick={() => setActiveSection(s.id)}
            >
              {s.title}
            </button>
          ))}
        </nav>

        <div className="docs-content">
          <section>
            <h3>{section.title}</h3>
            <p className="docs-section-desc">{section.description}</p>
            {section.workInProgress && (
              <WorkInProgressBanner />
            )}
            {section.basePath && (
              <p className="docs-base-path">
                Base path: <code>{section.basePath}</code>
              </p>
            )}
            <div className="api-endpoints">
              {section.endpoints.map((ep) => (
                <EndpointCard key={`${ep.method}-${ep.path}`} endpoint={ep} />
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
