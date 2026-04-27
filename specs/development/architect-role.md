# Architect Role

This document describes the architect role in the development workflow of this project.

## Overview

The architect creates the design plan from the system specification.

## Tasks and Responsibilities

### Design Plan

This role owns the design plan.

Break down the system specification in `/specs/system/` into a design plan `/work/plans/design-plan.md` containing all features, components and interfaces needed to fully implement the system in the most simple design which still satisfy the constraints from the system specification.

Example: If the system specification does not define a runtime performance constraint, the design should focus on simplicity instead of runtime efficiency.

If not overriden by system specificaton constraints, the design should be optimized for the following concepts in descending order (highest priority first):

- simple is better than complex
- clear separation of concern (between components)
- state-of-the-art interfaces (e.g. SSE over HTML polling)
- Low number of components
- runtime efficiency / execution speed
- low memory consumption
- small code size

If the design plan already exists, review and refine it according to the current progress of the project. Inspect the project code and read the history `/work/history/` to evaluate the current progress.
