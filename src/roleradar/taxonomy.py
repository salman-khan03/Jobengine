"""Skill taxonomy: canonical names, surface aliases, and an implication graph.

Why this exists at all: JobEngine's `match.py` scores raw keyword overlap,
which has two failure modes that matter for a *decision* system.

1. **Alias blindness.** A posting asking for "Postgres" and a resume saying
   "PostgreSQL" score zero overlap. The candidate is told they are missing a
   skill they have. For ranking that is noise; for "should I apply?" it is a
   wrong answer.
2. **No notion of subsumption.** Shipping a Next.js app is direct evidence of
   React, which is direct evidence of JavaScript. Treating those as three
   unrelated tokens both under-credits real experience and makes the
   explanation unconvincing.

IMPLIES encodes only relationships that are true by construction -- you
cannot have used Next.js without using React -- never "these tend to co-occur"
(Docker does not imply Kubernetes; plenty of people ship containers with
neither). Implied skills are tracked as *derived*, and the matcher discounts
them relative to a skill named outright, because "I used Next.js" is weaker
evidence for a React role than "I used React".

The table is hand-curated and intentionally small. A 10,000-skill ontology
scraped from job boards would look more impressive and be less defensible;
this one covers the roles the pipeline actually ingests (SWE intern/new-grad)
and every entry can be justified out loud in an interview.
"""
from __future__ import annotations

import re
from functools import lru_cache

# canonical -> surface forms seen in postings and resumes. The canonical name
# itself is always matchable and does not need repeating in its alias list.
ALIASES: dict[str, tuple[str, ...]] = {
    # languages
    "python": ("py", "python3"),
    "java": (),
    "javascript": ("js", "ecmascript", "es6"),
    "typescript": ("ts",),
    "c++": ("cpp", "cplusplus"),
    "c": (),
    "c#": ("csharp", "c sharp", ".net c#"),
    "go": ("golang",),
    "rust": (),
    "kotlin": (),
    "swift": (),
    "ruby": (),
    "php": (),
    "scala": (),
    "r": (),
    "sql": (),
    "bash": ("shell", "shell scripting", "zsh"),
    "html": ("html5",),
    "css": ("css3",),
    # frontend
    "react": ("react.js", "reactjs"),
    "next.js": ("nextjs", "next js"),
    "vue": ("vue.js", "vuejs"),
    "angular": ("angularjs",),
    "svelte": ("sveltekit",),
    "tailwind": ("tailwindcss", "tailwind css"),
    "redux": (),
    "three.js": ("threejs", "webgl", "react three fiber", "r3f"),
    # backend / frameworks
    "node.js": ("node", "nodejs"),
    "express": ("express.js", "expressjs"),
    "fastapi": (),
    "flask": (),
    "django": (),
    "spring boot": ("springboot", "spring", "spring framework"),
    "rails": ("ruby on rails",),
    "graphql": (),
    "rest api": ("rest", "restful", "restful api", "rest apis"),
    "grpc": ("protobuf", "protocol buffers"),
    "websockets": ("websocket", "socket.io"),
    "microservices": ("microservice", "service oriented architecture", "soa"),
    # data stores
    "postgresql": ("postgres", "psql", "postgresql database"),
    "mysql": ("mariadb",),
    "sqlite": (),
    "mongodb": ("mongo",),
    "redis": (),
    "dynamodb": (),
    "elasticsearch": ("opensearch", "elastic search"),
    "pgvector": ("vector database", "vector db", "vector store", "pinecone", "weaviate"),
    "sqlalchemy": (),
    "orm": ("object relational mapping", "hibernate", "jpa"),
    # infra / platform
    "docker": ("containers", "containerization"),
    "kubernetes": ("k8s", "eks", "gke"),
    "aws": ("amazon web services", "ec2", "s3", "lambda", "cloudwatch", "sqs"),
    "gcp": ("google cloud", "google cloud platform"),
    "azure": ("microsoft azure",),
    "terraform": ("infrastructure as code", "iac"),
    "ci/cd": ("ci cd", "cicd", "continuous integration", "continuous delivery",
              "github actions", "jenkins", "gitlab ci"),
    "linux": ("unix",),
    "git": ("github", "gitlab", "version control"),
    "kafka": ("apache kafka", "event streaming"),
    "rabbitmq": ("message queue", "message broker"),
    "nginx": ("reverse proxy", "load balancer", "load balancing"),
    "observability": ("monitoring", "prometheus", "grafana", "opentelemetry",
                      "datadog", "logging", "tracing"),
    "serverless": ("aws lambda", "cloud functions"),
    # ai / data
    "machine learning": ("ml", "supervised learning", "model training"),
    "deep learning": ("neural networks", "neural network"),
    "nlp": ("natural language processing", "text processing"),
    "computer vision": ("cv", "image processing"),
    "pytorch": ("torch",),
    "tensorflow": ("keras", "tf"),
    "scikit-learn": ("sklearn", "scikit learn"),
    "pandas": (),
    "numpy": (),
    "llm": ("large language model", "large language models", "gpt", "openai",
            "gemini", "claude", "prompt engineering", "generative ai", "genai"),
    "rag": ("retrieval augmented generation", "retrieval-augmented generation",
            "semantic search"),
    "embeddings": ("vector embeddings", "sentence embeddings", "text embeddings"),
    "information retrieval": ("tf-idf", "tfidf", "bm25", "ranking", "search relevance"),
    "etl": ("data pipeline", "data pipelines", "data engineering", "airflow", "dbt"),
    "spark": ("apache spark", "pyspark"),
    # practice
    "testing": ("unit testing", "unit tests", "integration testing", "pytest",
                "junit", "jest", "test automation", "tdd"),
    "distributed systems": ("distributed system", "distributed computing"),
    "system design": ("systems design", "architecture", "software architecture"),
    "algorithms": ("data structures", "algorithm design", "dsa"),
    "agile": ("scrum", "kanban"),
    "code review": ("peer review", "pull requests"),
    "caching": ("cache", "memcached"),
    "api design": ("api development", "openapi", "swagger"),
    "security": ("authentication", "authorization", "oauth", "jwt", "appsec"),
    "performance": ("optimization", "profiling", "latency", "load testing",
                    "benchmarking", "scalability"),
}

# Subsumption edges: using the key is *by construction* evidence of the value.
# Read as "implies", and keep it to things that cannot be false.
IMPLIES: dict[str, tuple[str, ...]] = {
    "next.js": ("react", "javascript", "node.js"),
    "react": ("javascript",),
    "vue": ("javascript",),
    "angular": ("typescript", "javascript"),
    "svelte": ("javascript",),
    "redux": ("react", "javascript"),
    "typescript": ("javascript",),
    "three.js": ("javascript",),
    "tailwind": ("css",),
    "express": ("node.js", "javascript"),
    "node.js": ("javascript",),
    "fastapi": ("python", "rest api"),
    "flask": ("python",),
    "django": ("python",),
    "pandas": ("python",),
    "numpy": ("python",),
    "pytorch": ("python", "deep learning", "machine learning"),
    "tensorflow": ("python", "deep learning", "machine learning"),
    "scikit-learn": ("python", "machine learning"),
    "deep learning": ("machine learning",),
    "nlp": ("machine learning",),
    "computer vision": ("machine learning",),
    "rag": ("llm", "embeddings", "information retrieval"),
    "embeddings": ("information retrieval",),
    "pgvector": ("postgresql", "embeddings"),
    "spring boot": ("java",),
    "rails": ("ruby",),
    "sqlalchemy": ("python", "orm", "sql"),
    "postgresql": ("sql",),
    "mysql": ("sql",),
    "sqlite": ("sql",),
    "kubernetes": ("docker",),
    "graphql": ("api design",),
    "rest api": ("api design",),
    "grpc": ("api design",),
    "microservices": ("distributed systems", "system design"),
    "kafka": ("distributed systems",),
    "spark": ("distributed systems", "etl"),
    "ci/cd": ("testing", "git"),
    "serverless": ("aws",),
}

# Built once: every surface form (canonical + aliases) -> canonical name.
_SURFACE: dict[str, str] = {}
for _canon, _alts in ALIASES.items():
    _SURFACE[_canon] = _canon
    for _alt in _alts:
        # First writer wins, so a canonical name is never shadowed by another
        # skill's alias (e.g. "aws lambda" must not steal "aws").
        _SURFACE.setdefault(_alt, _canon)

# Longest-first so "machine learning" is consumed before "learning" could be,
# and "next.js" before "next". Regex-escaped because "c++" and "c#" are real
# skill names full of metacharacters.
_SURFACE_PATTERN = re.compile(
    "|".join(
        r"(?<![A-Za-z0-9+#.])" + re.escape(s) + r"(?![A-Za-z0-9+#])"
        for s in sorted(_SURFACE, key=len, reverse=True)
    )
)

CANONICAL_SKILLS: frozenset[str] = frozenset(ALIASES)


def canonical(term: str) -> str | None:
    """Map one surface form to its canonical skill, or None if unknown."""
    return _SURFACE.get(term.strip().lower().rstrip("."))


def extract_skills(text: str) -> tuple[str, ...]:
    """Every canonical skill named in `text`, in first-appearance order.

    Order is stable and deduplicated so callers can use the result as a
    deterministic key (tests, cache keys, DB rows) rather than a set whose
    iteration order shifts between runs.
    """
    seen: dict[str, None] = {}
    for m in _SURFACE_PATTERN.finditer((text or "").lower()):
        seen.setdefault(_SURFACE[m.group(0)], None)
    return tuple(seen)


@lru_cache(maxsize=512)
def closure(skill: str) -> frozenset[str]:
    """`skill` plus everything it implies, transitively.

    Cycles are impossible in a correct IMPLIES table, but the visited-set walk
    tolerates one rather than recursing forever if somebody adds a bad edge.
    """
    out: set[str] = set()
    stack = [skill]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(IMPLIES.get(cur, ()))
    return frozenset(out)


def expand(skills: tuple[str, ...] | list[str] | set[str]) -> dict[str, str]:
    """Expand a skill set to {skill: "direct" | "implied"}.

    Direct always wins: if a resume says both "react" and "next.js", react is
    direct evidence, not something merely inferred from Next.js.
    """
    direct = {s for s in skills if s}
    out: dict[str, str] = {s: "direct" for s in direct}
    for s in direct:
        for implied in closure(s) - {s}:
            out.setdefault(implied, "implied")
    return out
