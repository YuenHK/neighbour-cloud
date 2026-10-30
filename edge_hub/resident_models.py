"""The only approved free cloud dialogue choices; never accept arbitrary model IDs."""
FAST_MODEL = 'gemini-3.5-flash-lite'
GEMMA_MODEL = 'gemma-4-26b-a4b-it'
FREE_MODELS = (FAST_MODEL, GEMMA_MODEL)
LABELS = {FAST_MODEL: 'Gemini 3.5 Flash-Lite', GEMMA_MODEL: 'Gemma 4 26B A4B'}
