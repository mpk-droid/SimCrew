export function PublicRepoDisclaimerBanner() {
  return (
    <div className="disclaimer-banner" role="note">
      <span className="badge badge--disclaimer">Important</span>
      <p>
        Only run this for public or open-source repositories: their code and the findings are
        sent to the model provider this server is configured with.
        This site does not yet implement PII handling or related data protections.
      </p>
    </div>
  );
}
