UV ?= $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)
NPM ?= $(shell command -v npm 2>/dev/null || echo $(HOME)/.local/bin/npm)
export PATH := $(HOME)/.local/bin:$(PATH)

# ML=1 installs/keeps the optional real-model deps (torch, mlx-whisper, speechbrain, ...).
# NOTE: a plain `uv sync` (e.g. `make setup` without ML=1) REMOVES them again (uv syncs exactly),
# so pass ML=1 to every target once you use real models, e.g. `make dev-backend ML=1`.
ML ?=
EXTRA := $(if $(ML),--extra ml,)

.PHONY: setup dev-backend dev-live dev-frontend test eval clips build enroll-demo

setup:            ## install backend + frontend deps (ML=1 for real models)
	cd backend && $(UV) sync $(EXTRA)
	cd frontend && $(NPM) install

dev-backend:      ## FastAPI on :8000 with reload
	cd backend && $(UV) run $(EXTRA) uvicorn app:app --reload --port 8000

# Fraud LLM defaults to auto (Nebius/NVIDIA if a key is set, else keywords): pointing it at the same local
# Ollama as the persona (LLM_PROVIDER=ollama) serializes both on one model and adds ~3 s per AI reply.
dev-live:         ## live "try it" backend on :8000: real models, Ollama persona LLM, say/ElevenLabs TTS
	@test -f data/enroll/CUST-004217.npy || $(MAKE) enroll-demo
	cd backend && STT_PROVIDER=mlx VAD_PROVIDER=silero SPEAKER_PROVIDER=ecapa SPOOF_PROVIDER=pretrained \
	  LLM_PROVIDER=$${LLM_PROVIDER:-auto} LLM_TIMEOUT_S=$${LLM_TIMEOUT_S:-3} CALLER_LLM_PROVIDER=$${CALLER_LLM_PROVIDER:-ollama} \
	  HF_HUB_OFFLINE=1 $(UV) run --extra ml uvicorn app:app --host $${HOST:-127.0.0.1} --port $${PORT:-8000}

dev-frontend:     ## Vite dashboard on :5173
	cd frontend && $(NPM) run dev

test:             ## backend unit + integration tests (ML tests skip unless ML=1)
	cd backend && $(UV) run $(EXTRA) pytest -q

eval:             ## offline eval over data/eval/labels.csv; NOTE="..." to annotate the history row
	$(UV) run --project backend $(EXTRA) python scripts/eval.py --note "$(NOTE)"

clips:            ## regenerate demo clips with macOS `say` + ffmpeg
	$(UV) run --project backend $(EXTRA) python scripts/make_clips.py

enroll-demo:      ## demo voiceprint for CUST-004217 from a macOS `say -v Samantha` enrollment clip
	$(UV) run --project backend --extra ml python scripts/enroll.py CUST-004217 --say Samantha --name "Margaret Chen"

build:            ## production build of the dashboard
	cd frontend && $(NPM) run build
