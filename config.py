"""Central configuration for the ad-simulator project.

All tunable constants, file paths, and model identifiers live here so the
individual modules stay free of hard-coded values. Import what you need:

    from config import PERSONA_FILE, DEFAULT_PERSONA_COUNT
"""
from pathlib import Path

# --- Paths -----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"          # downloaded public CTR datasets
PERSONA_DIR = DATA_DIR / "personas"      # generated synthetic persona CSVs
BENCHMARK_DIR = DATA_DIR / "benchmarks"  # calibrated weights + benchmark JSON

# Create data directories on import so no module has to worry about it.
for _d in (RAW_DATA_DIR, PERSONA_DIR, BENCHMARK_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Persona generation ----------------------------------------------------
DEFAULT_PERSONA_COUNT = 1000             # within the 500-2000 supported range
RANDOM_SEED = 42                         # one seed drives the whole pipeline
PERSONA_FILE = PERSONA_DIR / "personas.csv"

# --- Multimodal visual analysis -------------------------------------------
CLAUDE_MODEL = "claude-opus-4-7"
OPENAI_MODEL = "gpt-4o"

# Gemini's 2026 free tier is 20 requests/day PER MODEL. We rotate across
# multiple models so when one is exhausted the next picks up. Each model
# has its own daily quota, multiplying the effective free budget by len(chain).
# The lite/preview variants tend to recover quota faster.
GEMINI_TEXT_CHAIN = (
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-flash-latest",
)
GEMINI_VISION_CHAIN = (
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-flash-latest",
)
GEMINI_GROUNDED_CHAIN = (
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.0-flash",
)
# Back-compat single names — first model in each chain.
GEMINI_MODEL = GEMINI_TEXT_CHAIN[0]
GEMINI_VISION_MODEL = GEMINI_VISION_CHAIN[0]
GEMINI_GROUNDED_MODEL = GEMINI_GROUNDED_CHAIN[0]

# Groq is the free-tier alternative to Gemini -- fast, generous limits,
# Llama 4 Scout has vision. Used in the auto-fallback chain when Gemini's
# daily quota is exhausted.
GROQ_TEXT_MODEL = "llama-3.3-70b-versatile"
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Mistral La Plateforme -- has Pixtral for vision, free tier.
MISTRAL_TEXT_MODEL = "mistral-small-latest"
MISTRAL_VISION_MODEL = "pixtral-12b-2409"
MISTRAL_BASE_URL = "https://api.mistral.ai/v1"

# OpenRouter -- gateway with ~50 models, has free tier with $0-cost models.
OPENROUTER_TEXT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
OPENROUTER_VISION_MODEL = "meta-llama/llama-3.2-11b-vision-instruct:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# xAI Grok -- has Grok vision via grok-2-vision endpoint.
# grok-2-1212 was retired (xAI lineup is now grok-3 / grok-4); grok-2-vision-1212
# is still listed, so only the text model needed updating (verified Jun 2026).
XAI_TEXT_MODEL = "grok-3"
XAI_VISION_MODEL = "grok-2-vision-1212"
XAI_BASE_URL = "https://api.x.ai/v1"

# Together AI -- $1 free credit, many open models incl. vision.
TOGETHER_TEXT_MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"
TOGETHER_VISION_MODEL = "meta-llama/Llama-Vision-Free"
TOGETHER_BASE_URL = "https://api.together.xyz/v1"
# The four ad-image scores produced by the vision module (all on a 0-1 scale).
VISUAL_SCORE_KEYS = (
    "emotional_arousal",
    "visual_clarity",
    "attention_capture",
    "relevance_potential",
)

# --- Background training (public CTR datasets & calibration) --------------
# The four psychology rules whose weights are calibrated from CTR patterns.
# Shared by data_loader, calibration, and the agent so the names never drift.
PSYCHOLOGY_FEATURES = (
    "emotional_appeal",
    "scarcity",
    "social_proof",
    "relevance",
)
# Clearly-labelled synthetic fallback dataset, written only when no real
# public dataset has been downloaded (see src/data_loader.py).
SYNTHETIC_CTR_FILE = RAW_DATA_DIR / "synthetic_ctr.csv"
# Calibrated psychology-rule weights, written by src/calibration.py.
CALIBRATION_FILE = BENCHMARK_DIR / "calibration.json"

# --- Simulation defaults ---------------------------------------------------
DEFAULT_MONTE_CARLO_RUNS = 20            # within the 10-30 supported range
DEFAULT_SIM_DAYS = 14
