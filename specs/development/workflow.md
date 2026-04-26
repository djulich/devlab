# Development Workflow

## Overview

This project uses an orchestrated agentic development workflow to build and enhance the project.

This roughly means that AI agents are called repeatedly in a coordinated way to work through various tasks until a project milestone has been reached.

In this project, AI agents representing different roles (developer, architect, manager) are called repeatedly and sequentially by a scripted orchestrator to work through a `session`. This stops until a pre-defined project milestone is reached, or a fail condition emerges which cannot be handled by the workflow itself. Agents pass context to the next agent with the same role via repository artifacts.

##

System Specification --[Architect]--> Design Plan --[Planner]--> Project Plan --[Manager]--> Backlog Tasks --[Developer]--> Implementation





### System Specification

The system specification defines the capabilites of the end product.

### Project Plan

The project plan defines the features and interfaces which need to be implemented to materialize a product which satisfies the system specification.

### Backlog Tasks

A backlog task defines the work needed to progress the project to the completion of the next feature or milestone. A backlog tasks is implemented within a development `session`. The scope of a backlog task is narrow, as the development workflow can define as much tasks as needed, but one development session has only a limited context window available (which is the fundamental aspect of the workflow design, otherwise an AI agent could finalize any project on the basis of just one very large prompt).
