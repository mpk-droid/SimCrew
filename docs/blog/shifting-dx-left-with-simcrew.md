# Shifting developer experience left with SimCrew: Let synthetic developers find your onboarding bugs first

You cannot read your own README. You can look at the words, but you cannot experience them, because you already know what `MODEL_ID` means, which port the service listens on, and that `make dev` has to run before `make test`. Every repository you have ever written is easy to set up, and that tells you nothing.

The usual ways around this are all human and all expensive. You pair a new hire with an onboarding buddy and mine their confusion. You run a usability study. You ask a friendly team on another floor for "fresh eyes." Each of these works once. After someone has struggled through your setup, they can never be surprised by it again. Meanwhile the repository keeps changing, and the next commit that breaks onboarding lands without a single test going red.

Developer experience (DX) bugs behave exactly like any other bug: the later you find one, the more it costs. A confusing environment variable caught in review costs a sentence of documentation. The same variable caught after a dozen teams depend on your repository costs a migration and a support queue. We shift security left, we shift testing left, and we leave DX at the far right of the timeline, where it is discovered by the people we were trying to impress.

[SimCrew](https://github.com/mpk-droid/SimCrew) is an open source attempt to move it. It runs a crew of *synthetic developers* against any git repository: you give it a URL, and it starts one container per persona. Each persona is an LLM agent that clones the repository and evaluates it the way a developer would (reading docs, installing dependencies, starting the service, calling endpoints, inspecting the deployment files) while knowing nothing except what the repository tells it. Findings come back with verbatim evidence, deduplicated across personas, and scored GREEN, YELLOW, or RED. No model picks that color: a deliberately dull rule over the finding counts does, and triage grades the personas as well as the repository, so a misbehaving persona shows up as a broken instrument instead of a broken README.

That is the difference from the QA agents now showing up in CI pipelines. They test whether the features work. SimCrew tests whether *people* can work: a junior developer on day one, a staff engineer reviewing the deployment, a platform lead deciding whether to adopt it. Because every persona sits at a different experience level, a run tells you not only that onboarding breaks but who it breaks for. I have not found another tool that evaluates developer experience stratified by experience level.

The same run answers a second question that has quietly become just as important: *is this repository ready for AI coding agents?*

In this article, I will cover:

- Why a persona has to be specific to work, and how SimCrew encodes what a persona can and cannot do
- Why journeys and personas should be tailored to the repository under test
- Why the same run measures agent readiness
- Where this matters most: fluid teams, and repositories that *are* the product
- What a real run finds, what it costs, and how to keep that cost down
- Wiring a run into CI, and where that is a bad idea
- What keeps the findings honest, how this relates to other work, and where the approach falls down

## What SimCrew is

SimCrew is a small service with three moving parts:

- **Personas**: who is evaluating the repository
- **Journeys**: an ordered test plan every persona follows
- **An orchestrator**: starts one sandboxed container per persona, collects findings, then triages and scores them

Everything in the UI is also available through the API, and personas and journeys are rows in a database, so an evaluation is configuration rather than somebody's calendar.

## "Act like a junior developer" does not work

The obvious way to build a persona is a one-line prompt: *you are a junior developer*. It does not work, for a reason that is easy to see once you try it. A large language model has read every tutorial ever written. Tell it to act junior and it will adopt a junior *tone* while keeping all of its knowledge. It will cheerfully infer that `MODEL_ID` takes a Hugging Face identifier and sail past the exact gap in your documentation that a real junior developer would get stuck on.

Research on persona prompting points the same way. Hu and Collier found that persona variables explain little of the variation in many tasks, and that adding them to prompts yields only modest gains in simulation fidelity ([Quantifying the Persona Effect in LLM Simulations](https://arxiv.org/abs/2402.10811)). Lutz et al. showed that *how* a persona prompt is written changes how faithful and how stereotyped the simulation is ([The Prompt Makes the Person(a)](https://arxiv.org/abs/2507.16076), EMNLP Findings 2025). Both studies look at sociodemographic personas rather than developer skill levels, but the lesson carries over: a label is not a persona. The behavior you want has to be spelled out.

So in SimCrew a persona is not a free-text prompt. It is structured fields, and the service generates the prompt from them:

| Field | Purpose |
|-------|---------|
| `identity` | Who they are and how much experience they have |
| `perspective` | What they look at and what they tend to catch |
| `constraints` | What they know, and more importantly what they do not |
| `role_label` | Short label for the UI |

Structure also makes personas comparable: two free-text prompts written a month apart differ in a hundred uncontrolled ways, while two sets of fields differ only where you changed them.

Here is Sam, from the persona pack SimCrew ships for agentic AI repositories (`backend/app/seed/dx_pack.py`):

```python
{
    "name": "Sam — Junior Backend Dev",
    "role_label": "Junior dev",
    "identity": (
        "Junior backend developer whose company just decided to 'add AI.' "
        "2 years total experience, joined this company 2 months ago. "
        "Proficient in REST APIs and container deployment; has never worked "
        "with LLMs, agent frameworks, or the OpenAI API spec."
    ),
    "perspective": (
        "Follows instructions literally. Doesn't know what LangGraph, "
        "CrewAI, or 'tool calling' means. Catches AI-specific jargon "
        "without explanation, missing model configuration guidance, "
        "assumed AI ecosystem knowledge."
    ),
    "constraints": (
        "Does NOT know what MODEL_ID, BASE_URL, or API_KEY mean in the AI "
        "context. Does not know what an 'agent framework' is. Only knows "
        "backend development, REST APIs, and containers."
    ),
}
```

Notice how specific that is. Sam does not "lack AI experience." Sam does not know three named environment variables and two named frameworks. The `constraints` field lists what is off limits, and the generated prompt closes the door on outside knowledge explicitly:

```text
## Important
You ONLY know what the repository tells you. If the documentation doesn't
explain a step, you are stuck — report it as a finding. Do not use outside
knowledge to fill gaps.
```

That paragraph is the difference between a DX test and a code review. A code review rewards knowledge. This rewards the absence of it.

The generated prompt is not used until someone approves it. Personas are the measuring instrument, and an instrument nobody has looked at produces numbers nobody should trust.

## Tailor the journey and the crew to the repository

Personas need somewhere to go. A journey is an ordered list of phases, each with instructions that every persona follows independently. The built-in DX journey has five:

1. **First impressions**: read the README and top-level docs. Can you tell what this is and who it is for?
2. **Setup**: follow the install instructions exactly. Are prerequisites and environment variables documented with example values?
3. **Running locally**: start the application. If the docs do not explain how, that is itself a finding.
4. **Using the target**: discover the endpoints from docs and source, then actually call them. Report gaps between what is documented and what works.
5. **Deployment**: read the Dockerfile, chart, and CI config. Resource limits, health probes, secrets handling.

Each persona gets its own container and a small set of tools: `read_file`, `list_directory`, `run_command`, `http_request`, `report_finding`, and `complete_phase`. Commands are checked against a list of allowed command prefixes (`make`, `npm`, `pip`, `uv`, `docker compose`, `helm`, `oc get`, and so on) and a list of blocked patterns. Those lists are guardrails, not a security boundary. The container is the boundary.

Phase 3 makes "I could not figure out how to start this" a first-class result rather than a failed run. A persona that gets stuck is marked `blocked`, and a blocked persona forces the whole run to RED. That is the behavior you want: if a literal-minded reader with two years of experience cannot start your service, the score should not be yellow.

The generic journey and personas are a starting point, not the point. **The most useful runs come from personas and journeys written for the repository under test.** Sam is already an example: his constraints only make sense for a repository that configures LLMs. For a Kubernetes operator you would write an application developer who has never written a custom resource. For a Python SDK you might write a data scientist who knows pandas and not packaging. The journey should follow the path your real users take. "Deploy the operator and create your first custom resource" is a better phase than "use the target."

This creates a trade-off worth making on purpose:

- **A small generic baseline** (the same personas and journey for every repository) gives you scores you can compare across repositories and over time.
- **Repository-specific personas and journeys** give you depth. This is where most of the real findings come from.

Run both. The baseline tells you which repository needs attention; the tailored crew tells you why.

## The same run tells you whether your repo is agent-ready

Here is the part I did not plan for and now find the most useful.

A synthetic developer is an AI agent working from repository contents, a shell, and nothing else. That is exactly the situation Claude Code, Cursor, or Copilot is in the first time someone points it at your repository. The two questions turn out to be one question:

- Can a junior developer get this running from the README alone?
- Can a coding agent get this running from the README alone?

When Sam blocks in phase 2 because a required environment variable appears in a compose file but nowhere in the docs, you have found a human onboarding bug and an agent-readiness bug with the same evidence.

Agent readiness has quietly become a real deliverable. Repositories now ship `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`, and MCP server configs: a whole instruction layer written for non-human readers. Almost nobody tests that layer. You cannot grade your own `AGENTS.md` for the same reason you cannot read your own README: you know what it leaves out. And the failure is quiet. An agent with too little context does not error; it guesses, writes plausible code against a package you do not use, and burns an afternoon.

A DX run surfaces the concrete things that layer is supposed to provide:

- Do the documented commands exist and exit zero?
- Are the build, test, and lint commands discoverable without tribal knowledge?
- Is every required environment variable documented with an example value?
- Are there conventions (port choices, directory layout, style rules) that are enforced in review but written down nowhere?
- Does the repository explain its own architecture well enough to change one thing safely?

To test the instruction layer directly, define a persona shaped like an agent rather than a person. Again, the constraints are where you spell out what it can and cannot do:

```bash
curl -X POST http://localhost:8000/api/personas \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Agent Readiness Check",
    "role_label": "Coding agent",
    "identity": "An AI coding assistant opening this repository for the first time, with a non-interactive shell and no prior knowledge of the project.",
    "perspective": "Reads AGENTS.md, CLAUDE.md, and .cursor/rules first, then verifies every claim in them against the repository. Runs each documented command and reports any that is missing, wrong, or requires a step not written down.",
    "constraints": "Cannot open a browser, click a UI, or ask a teammate. Cannot answer interactive prompts. Has no access to internal wikis, Slack, or tribal knowledge. Only the repository contents and a shell."
  }'
```

Review the generated prompt, then approve it before using the persona in a run:

```bash
curl -X POST http://localhost:8000/api/personas/<persona-id>/approve-prompt
```

## Where this matters most

### Fluid teams

Many engineering organizations no longer staff a project with the same people for years. Engineers rotate between projects every few months, pick up a service from another team, or get pulled in for a two-week push. Every one of those moves is an onboarding, and it usually happens to an existing repository, not a new one.

The people who know a repository best are exactly the ones who cannot see its gaps, and in a fluid team they are also the ones most likely to have moved on. Nobody re-onboards on purpose, so the repository drifts until someone new arrives and loses their first week to it.

SimCrew turns that into something you can measure before the handoff. Write a persona for the person who will actually arrive:

- **identity**: a mid-level engineer rotating in from another team, fluent in the language and platform, has never seen this repository
- **perspective**: needs to make one small, safe change within the first week
- **constraints**: cannot ask the previous owners; does not know the project's internal service names, environments, or release process

Then add a journey phase that goes past "run it": *make a small change, run the tests, and explain how you would ship it.* A GREEN score means the repository is ready for the next person. A RED one tells you exactly what the departing team needs to write down before they go.

### When the repository is the product

For most services the repository is how the product gets built. For a growing class of projects, the repository *is* the product: SDKs, CLIs, Kubernetes operators, Helm charts, project templates, starter kits. Users never see a UI; their entire experience is the README, the install command, and the first ten minutes. For these projects, DX is the user experience, and a DX bug is a product bug.

Templates are the extreme case. A template is cloned and adapted into many repositories, so a gap in it is copied everywhere before anyone notices. Nobody re-onboards to a template, so a regression introduced in one sprint can be found by a user months later, repeated in every repository generated in between.

This is where SimCrew earns the most. Because the evaluation is configuration, you can keep the persona and journey definitions in version control next to the project, run the identical evaluation on every release, and, for a template, run it against every repository the template produces. A new repository gets the same scrutiny in hour one that your flagship project got last quarter.

## What a run actually finds

To show a run with nothing hidden, here is the first full run of the current build. The target is a popular open source FastAPI example application that I did not write. I pinned it to an older commit, just before the fix for a real onboarding bug that users had reported: a missing dependency that made the app fail at startup with `No module named dotenv`.

**Setup.** The run used the four-persona baseline crew: Sam (junior backend dev), Dana (staff engineer), Priya (engineering director), and Kai (platform lead). It followed the five-phase generic journey on NVIDIA Nemotron 3 models and took 24 minutes.

**Result.** The personas reported 114 raw findings, 27 of them critical. The score is computed as soon as the run ends, after a quick first merge of duplicates, and it came back RED with the rationale `24 critical finding(s) require immediate attention.` Triage then ran its stricter pass. It grouped the 114 findings into 110 clusters and marked 25 of them as contradicted, dropping them from the report. Most of those were mistakes by triage, not by the personas (see "Keeping the findings honest" below). Each rejection is recorded against the persona that reported it, which feeds the persona grading described below. That left 85 findings: 18 critical, 48 needing attention, and 19 nits. Triage verified 62 of the 85 against the repository. The other 23 stayed unverified, either because they could not be checked or because they rest only on several personas agreeing.

What it got right:

- **Two personas independently reported that the container runs as root**, and triage verified it against the `Dockerfile`. Several others flagged that the container `CMD` runs Alembic migrations on every start, which is unsafe with more than one replica. These are real deployment problems, and a README reviewer would not catch them.
- **Single-persona findings that were real:** the quickstart assumes PostgreSQL is already running, `.env.example` does not match the `docker-compose.yml` networking, and the Dockerfile uses a deprecated Poetry flag (`--no-dev`).

What it got wrong, which matters more:

- **It did not find the known bug.** The locked Poetry version would not install under the Poetry in the persona image, so three personas fell back to an unpinned `pip install`. That pulled in pydantic v2, and they all reported the same critical: `pydantic.errors.PydanticImportError: BaseSettings has been moved to the pydantic-settings package`. The project pins pydantic `^1.8`, so this is a problem with the agents' environment, not the project. Triage left it unverified, which is correct, but it still counts toward RED. This is exactly the gap that environments (see "Where this falls down") are meant to close.
- **One "verified" critical is false.** Dana reported that `.env` is tracked in git. The evidence is the `.env` line from `.gitignore`, and triage matched that snippet in the cited file and marked it verified. There is no `.env` in the repository. Evidence matching confirms that a quote exists, not that the conclusion drawn from it is right.
- **Three phases hit the 50-call cap for every persona**: Setup, Running Locally, and Using the Target. The personas spent those phases fighting their install rather than using the API.

The lesson is the one this post keeps coming back to. On a repository it was not tuned for, the generic crew finds real issues and also noise produced by its own sandbox. Read the verified findings first, and treat a RED score that rests on unverified environment failures with suspicion.

## What a run costs, and how to keep it down

A run is not free, and it is worth knowing where the money goes before you schedule one nightly.

Here is what the run above consumed. SimCrew records token usage per persona and per phase on every run, and it is returned under `usage` in `GET /api/runs/{id}`.

| | Model calls | Input tokens | Output tokens |
|---|---|---|---|
| Sam | 233 | 2,568,143 | 16,123 |
| Dana | 234 | 2,685,710 | 19,595 |
| Priya | 227 | 2,309,243 | 16,976 |
| Kai | 228 | 2,260,843 | 18,876 |
| Triage | 10 | 14,016 | 7,658 |
| **Total** | **932** | **9,837,955** | **79,228** |

By phase, across all four personas (triage excluded):

| Phase | Model calls | Input tokens |
|---|---|---|
| Running Locally | 200 (cap) | 2,611,974 |
| Setup | 200 (cap) | 2,330,113 |
| Using the Target | 200 (cap) | 2,311,125 |
| Deployment | 169 | 1,312,685 |
| First Impressions | 153 | 1,258,042 |

At estimated list prices for the Nemotron 3 Ultra model, that is roughly $5 to $6.50 for the run, or about $1.30 to $1.60 per persona. Some calls went to the cheaper Super model, which SimCrew does not yet split out, so treat this as an upper bound. Triage costs almost nothing.

The numbers make the case for everything below. Input outweighs output about 125 to 1, so nearly all of the cost comes from resending context, not from generating text. The three phases where personas were stuck at the call cap account for three quarters of the input tokens.

Cost is driven by a simple multiplication: personas × phases × model calls per phase. Three things make it grow faster than you would expect:

- **Every model call resends the conversation so far.** An agent that takes 30 steps in a phase pays for its early steps 30 times over. SimCrew starts each phase with a fresh conversation, so the history never carries across all five phases, but a long phase still gets expensive toward its end.
- **Tool output is input.** A persona that reads a 5,000-line file or dumps a long build log pays for all of it on every later call in that phase. SimCrew truncates file reads at 10,000 characters and command output at 5,000.
- **Stuck personas are the most expensive ones.** A persona that cannot start a service tends to try variations until it gives up. SimCrew caps each phase at 50 model calls, which bounds the worst case but does not make it cheap.

What reduces cost per run, roughly in order of impact:

1. **Run fewer personas more often.** A nightly run with one or two tailored personas is usually more useful than a weekly run of the full crew. Save the full crew for releases.
2. **Write tighter phases.** A phase with a clear goal ("start the service and call `/health`") ends sooner than an open-ended one ("explore the repository").
3. **Use a smaller model for personas.** Personas mostly read, run commands, and report. A smaller, cheaper model often finds the same blocking issues. Measure it on your repository before you switch.
4. **Cache the fixed parts of the prompt (coming soon).** The system prompt and tool definitions are identical on every call in a run, so provider-side prompt caching would cut input cost substantially once enabled. SimCrew does not enable it yet; it is on the roadmap.
5. **Only run when onboarding files change** (see the next section).

## Wiring a run into CI

Nothing special is needed to run SimCrew from a pipeline. It takes two API calls:

1. `POST /api/runs` with the repository URL, the personas, and the journey. You can optionally pick the model per run: SimCrew supports Claude through the Anthropic SDK or Vertex AI, and NVIDIA NIM models.
2. Poll `GET /api/runs/{id}` until the status is `completed` or `failed` and `triage.status` is `complete`, then fail the job if the score is RED. Triage reports `complete` even when it fails, with an `error` field, so a failed run cannot leave the poll waiting on it. Still, give the loop an overall timeout; the example script defaults to one hour.

`GET /api/runs/{id}` returns the score, the rationale, per-persona status including `blocked_phase` and `blocked_reason`, the triaged findings deduplicated across personas, and the token usage for the run. That is enough to write a useful pull request comment without scraping anything. A complete example is [`examples/ci/simcrew-dx-gate.sh`](https://github.com/mpk-droid/SimCrew/blob/main/examples/ci/simcrew-dx-gate.sh): it starts a run, waits for triage, prints the score and every finding above `nits`, and exits non-zero on RED.

**Do not put this on every pull request.** It is the wrong instrument for that job, for three reasons. A run takes minutes to tens of minutes, because the personas are genuinely installing dependencies and starting services. It costs money, multiplied by the number of personas. And it is non-deterministic: two runs of the same commit will not produce identical findings, which makes a per-PR gate a source of flaky failures and, eventually, of `[skip dx]` in commit messages.

Where it earns its place:

- **Nightly or weekly** against the main branch, with the score trend as the thing you actually watch
- **Path-filtered**, triggered only when `README.md`, `AGENTS.md`, `Dockerfile`, `chart/`, or `docker-compose.yml` change, since those are the files that break onboarding
- **Before a handoff**, when a project is about to change owners
- **As a release gate** for repositories that are the product, before you tag a version others will depend on
- **On repository creation**, as the last step of whatever automation generates a new repository from a template

That last one is the shift-left moment. The repository is evaluated before it has any users at all.

## Keeping the findings honest

The obvious objection to an LLM evaluator is that it will invent problems, confidently and in well-formatted prose. That is a real failure mode, and most of the engineering in SimCrew is aimed at it rather than at the agent loop.

**Evidence must be verbatim.** The generated prompt requires the `evidence` field on every finding to be exact text from a prior tool call, not a paraphrase. A finding without quotable output is a finding you can discard.

**The orchestrator re-checks the work.** After a run completes, triage clones the target repository independently and spot-checks finding clusters against the real files and commands. Findings whose evidence does not survive that check are marked as contradicted rather than silently kept. The check has limits, as the run above shows. "Verified" means the quoted evidence really is in the cited file, not that the conclusion drawn from it is right, which is how the `.env` finding got through. The check can also reject a correct finding: for a claim like "no `HEALTHCHECK` in the Dockerfile", it currently tests whether the Dockerfile exists rather than whether it contains a `HEALTHCHECK`. Tightening both is [open work](https://github.com/mpk-droid/SimCrew/issues/5).

**Agreement is a signal.** Findings are grouped by category and file path, then clustered by title similarity, keeping the highest severity in each cluster and recording which personas reported it. Three of four personas hitting the same wall is a much stronger result than one persona having an opinion, and the report shows you which it is.

**The score is arithmetic, not judgment.** No model assigns the traffic light. The rule, in `backend/app/engine/supervisor.py`, is deliberately dull:

```python
if any_blocked:
    return "RED"
if counts["critical"] > 0:
    return "RED"
if counts["needs_attention"] >= 3:
    return "RED"
if counts["needs_attention"] > 0:
    return "YELLOW"
return "GREEN"
```

Severities are `critical`, `needs_attention`, and `nits`. Three levels, because five-level severity scales collapse into three in practice anyway.

**The personas get graded too.** Triage also reports on the personas, not just the repository: it flags a persona whose findings were contradicted, one that keeps getting blocked, or one that produced almost no signal, and suggests how to tighten its fields. When a persona misbehaves, the bug is in your measuring instrument, and the report says so instead of letting you blame your README.

## How this relates to other work

Using LLM agents as stand-in users is not new, and SimCrew borrows from that work rather than competing with it.

- **AI personas for product research.** Commercial tools already put AI personas in front of products. [Synthetic Users](https://www.syntheticusers.com/) runs qualitative research, such as problem-exploration interviews and concept tests, with AI-simulated users. [Uxia](https://www.uxia.app/) sends AI testers through designs and prototypes to validate UX flows such as onboarding and checkout.
- **Agent-based usability testing.** [UXAgent](https://arxiv.org/abs/2502.12561) generates large numbers of simulated users to test web designs through a browser before running a study with real people.
- **Persona simulation research.** The papers cited above study how faithfully LLMs simulate the people they are told to be, and why the persona description matters. [PersonaGym](https://arxiv.org/abs/2407.18416) goes a step further and evaluates persona agents themselves, measuring how consistently they stay in character, which is the same instinct behind SimCrew grading its personas.
- **Static agent-readiness checks.** [Factory's Agent Readiness reports](https://factory.ai/agent-readiness) score a repository on whether it has the pieces an AI coding agent relies on, such as linters, type checking, tests, and CI. Linters for [AGENTS.md](https://agents.md/) files check that the paths and commands the file mentions actually exist. Both tell you whether the pieces are there. SimCrew tells you whether they work: its personas follow the documented steps, and a setup section that reads fine but fails on the third command shows up as a finding.

What SimCrew adds is a narrower target and a different kind of evidence. The target is a *repository*: its docs, commands, and deployment files, tested by personas who actually run things in a sandbox rather than click through a UI. The evidence is verbatim tool output, re-verified against a fresh clone and scored by a fixed rule. And the same run doubles as an agent-readiness check, which none of the product-research tools set out to measure.

## Where this falls down

Being honest about the limits is more useful than another feature list.

**Synthetic developers are not real developers.** They surface friction: missing steps, undocumented variables, commands that do not work, deployment files with no resource limits. They have no taste, no deadline, and no manager. They will not tell you that your API is technically usable and nevertheless unpleasant, and they cannot tell you whether anyone wants what you built.

**A crew is only as good as its personas.** Vague personas produce vague findings. Writing specific personas and journeys for a repository takes real effort, and it is the part you cannot automate away.

**Runs vary.** Treat the score as a trend and the findings as leads to verify, not as a test suite with a pass/fail bit you can trust unconditionally. This caveat applies to every LLM-based evaluation, and it is the reason for the deterministic scoring rule: at least the scoring step does not add variance of its own.

**The sandbox has real edges.** Some legitimate setups cannot complete inside it: interactive installers, private registries that need credentials the container does not have, anything requiring a GPU. You will see those as blocked personas, and you will have to tell the difference between "your docs are bad" and "the sandbox could not do this."

An upcoming feature, **environments**, narrows that gap. An environment is a container image you define to stand in for a developer's machine: which language runtimes, CLIs, and tools are installed, and which are not. You assign one to each persona, so a platform-engineer persona can work on a machine with `oc` and `helm` already set up while Sam starts on a bare laptop image. That removes most false blocks caused by the default sandbox missing a tool your real users would have. It also turns the machine itself into a test dimension. Run the same persona on an image without Docker, or without Python 3.12, and you learn whether your prerequisites section is honest. Environments do not fix everything: a persona still needs real credentials to reach a private registry, and a GPU only helps if the cluster running SimCrew has one to give.

**It costs time and money.** One container and one agent loop per persona, per run. That is why the scheduling advice above is not a footnote.

None of that changes the core claim. A README is a program written for humans, and it has bugs. Until recently the only way to find them was to watch a person hit one. Now you can run it.

## Get started

```bash
git clone https://github.com/mpk-droid/SimCrew.git
cd SimCrew

export NVIDIA_API_KEY=nvapi-...          # or ANTHROPIC_API_KEY=sk-...
docker compose up --build
```

Open <http://localhost:8000>. A starter crew of four personas and the five-phase DX journey are seeded on startup, so you can point a run at a repository immediately. Start with one you did not write, then run it against one you did. The second result is the interesting one. Then write one persona for the person who will actually use your repository next, and run it again.

A Helm chart for Red Hat OpenShift and Kubernetes is in `chart/`, for when you want SimCrew running somewhere your CI can reach it.

## Resources

- [SimCrew on GitHub](https://github.com/mpk-droid/SimCrew)
- [AGENTS.md](https://agents.md/): the emerging convention for agent instructions in a repository
- Hu and Collier, [Quantifying the Persona Effect in LLM Simulations](https://arxiv.org/abs/2402.10811)
- Lutz et al., [The Prompt Makes the Person(a): A Systematic Evaluation of Sociodemographic Persona Prompting for Large Language Models](https://arxiv.org/abs/2507.16076)
- [UXAgent: An LLM agent-based usability testing framework](https://arxiv.org/abs/2502.12561)
