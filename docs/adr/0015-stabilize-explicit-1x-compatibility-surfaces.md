# Stabilize explicit 1.x compatibility surfaces

DevLab 1.x guarantees the documented CLI, structured JSON output, executable
configuration semantics, and durable workspace representations beginning with
the 1.0 compatibility baseline. It does not promise compatibility with every
historical 0.x workspace or expose the importable `devlab.*` modules as a public
Python API.

Durable formats declare whether they are extensible or closed. Extensible
formats may gain optional fields without advancing their version and must retain
the meaning of existing fields. Identity-bearing session protocols and local
safety records reject unknown structure. Unsupported authoritative versions
fail without mutation and require explicit migration or recovery guidance.

This boundary lets minor releases add evidence and capabilities without freezing
incidental prose or implementation structure. The cost is maintaining readers
and fixtures for every promised 1.x representation, sequencing readers before
writers, and deferring incompatible cleanup until a major release. Restricting
the baseline to 1.0 and explicitly named 0.x fixtures avoids an unbounded promise
to support undocumented development formats.
