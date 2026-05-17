# Use profile-based environment lifecycle

DevLab uses task profiles for reusable tooling, validation defaults, and setup/cleanup commands instead of a single global environment config. This makes environment behavior explicit per task type and lets tooling evolve through planned tasks, at the cost of managing profile compatibility.
