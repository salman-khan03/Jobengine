"""RoleRadar — evidence-grounded job decision engine.

JobEngine (the sibling package) answers "what roles exist and which sponsor?".
RoleRadar answers a harder question: **should this specific candidate apply to
this specific role, and why?** — with every claim traceable to a line of the
candidate's own resume or a line of the job posting.

The pipeline is deliberately staged so that each stage is independently
inspectable and testable, and so the expensive/nondeterministic stage (the
LLM) runs *last*, over an already-computed structured result:

    evidence extraction  +  requirement extraction
                        |
               hard-constraint gate            (cheap, deterministic, can veto)
                        |
               skill coverage matching         (deterministic, cites evidence)
                        |
               semantic ranking                (embeddings, bounded influence)
                        |
               grounded explanation            (LLM, must cite; validated)
                        |
                  Decision  ->  outcome funnel  ->  ranking evaluation

Design rule that everything else follows from: **the LLM never invents the
verdict.** The score and the gate are computed by code; the model only writes
prose about an already-final structured result, and `explain.validate_grounding`
deletes any sentence whose claims aren't backed by a cited id. That is what
makes this "evidence-grounded" rather than "chat with your resume".
"""
from __future__ import annotations

__version__ = "2.0.0"

from .models import (  # noqa: F401
    CandidateProfile,
    ConstraintVerdict,
    Decision,
    EvidenceUnit,
    Gate,
    HardConstraint,
    JobRequirements,
    Requirement,
    SkillCoverage,
)
