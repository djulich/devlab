# Orchestrator Role

This document describes the orchestrator role in the development workflow of this project.

## Overview

The orchestrator controls the development workflow.

- It initiates sessions in which AI agents perform tasks to build the project.
- It selects the agent role for the next session.
- It creates a session history.
- It cleans up session artifacts.

## Tasks and Responsibilities

- Repeatedly invoke development sessions until the configured end criterion is fulfilled (e.g. a project milestone is reached), or an unrecoverable error has occurred.
- Select the required role for the next session and invoke an AI agentic with the selected role and context.
- Before the next session is started, do the following:
    - Delete the session artifact folder `/.session-artifacts/<role>/` for the role which was selected for the next session.
- After a session is finished, do the following:
    - Copy the session-handoff artifact to the history folder `/work/history/`. Adjust the file according to the `README.md` in that folder if needed.
    - If the session completed a task from the backlog, copy the task definition file from the backlog to the closed-tasks folder `/work/closed/`. Adjust the file according to the `README.md` in that folder if needed.
