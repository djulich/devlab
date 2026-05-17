# Enforce workflow rules in code rather than packaged prompts

DevLab keeps packaged role prompts focused on the instructions each spawned role needs to act correctly, while workflow selection, status transitions, and validation rules are enforced in code where practical. The trade-off is that workflow behavior takes more implementation effort than prose instructions, but it reduces prompt drift, avoids duplicating policy across Markdown files, and keeps DevLab reusable across target workspaces.
