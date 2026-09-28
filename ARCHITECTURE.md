ARCHITECTURE.md 151L lines:1-55
   1| # Architecture
   2| 
   3| ## Overview
   4| 
   5| SimCrew is a microservice that runs AI personas against software targets to evaluate developer experience. Each persona is an LLM agent (Claude via Anthropic SDK) with sandboxed tools that walks a configurable journey and reports evidence-backed findings.
   6| 
   7| ```
   8| ┌─────────────────────────────────────────────────┐
   9| │              React SPA (port 8000)               │
  10| │  Dashboard, Persona config, Journey builder,     │
  11| │  Run status, Report viewer                       │
  12| └──────────────────────┬──────────────────────────┘
  13|                        │ /api/*
  14| ┌──────────────────────┴──────────────────────────┐
  15| │              FastAPI Backend                      │
  16| │                                                  │
  17| │  ┌────────────────────────────────────────┐      │
  18| │  │          REST API Layer                │      │
  19| │  │  /api/personas  /api/journeys          │      │
  20| │  │  /api/runs          │      │
  21| │  │  /api/prompts                          │      │
  22| │  └────────────────────────────────────────┘      │
  23| │                                                  │
  24| │  ┌────────────────────────────────────────┐      │
  25| │  │          Engine                        │      │
  26| │  │  runner.py    — LLM tool-use loop      │      │
  27| │  │  tools.py     — sandboxed tools        │      │
  28| │  │  supervisor.py — scoring               │      │
  29| │  │  prompt_generator.py — fields→prompt   │      │
  30| │  └────────────────────────────────────────┘      │
  31| └──────────────────────┬──────────────────────────┘
  32|                        │
  33|               ┌────────┴────────┐
  34|               │   PostgreSQL    │
  35|               └─────────────────┘
  36| ```
  37| 
  38| ## Data Model
  39| 
  40| ### Persona
  41| 
  42| A configurable AI synthetic user. Defined by structured fields, not raw prompts.
  43| 
  44| | Field | Purpose |
  45| |-------|---------|
  46| | name | Display name ("Sam", "Principal Engineer") |
  47| | identity | Who they are, their background |
  48| | perspective | What they focus on, what they evaluate |
  49| | constraints | What they know vs don't know |
  50| | role_label | Short role label shown on persona cards (e.g. Junior dev) |
  51| | system_prompt | Generated from fields above, reviewed by user |
  52| | prompt_approved | User has reviewed and approved the prompt |
  53| 
  54| ### Journey
  55| 
