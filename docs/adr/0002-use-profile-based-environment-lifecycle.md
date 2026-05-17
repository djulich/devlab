# Use profile-based environment lifecycle

DevLab uses task profiles to define reusable tooling summaries, default validation commands, and optional setup/cleanup lifecycle commands instead of a single global environment configuration. Profiles make environment behavior explicit per task type, support reusable validation defaults, and let the planner evolve tooling through normal tasks while preserving compatibility for already-planned work.
