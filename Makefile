UV ?= $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)
NPM ?= $(shell command -v npm 2>/dev/null || echo $(HOME)/.local/bin/npm)
export PATH := $(HOME)/.local/bin:$(PATH)

# ML=1 installs/keeps the optional real-model deps (torch, mlx-whisper, speechbrain, ...).
# NOTE: a plain `uv run`/`uv sync` without `--extra ml` REMOVES them again (uv syncs exactly),
# so pass ML=1 to every target once you use real models, e.g. `make dev-backend ML=1`.
ML ?=
EXTRA := $(if $(ML),--extra ml,)

.PHONY: setup dev-backend dev-frontend test eval clips build enroll-demo

setup:            ## install backend + frontend deps (ML=1 for real models)
	cd backend && $(UV) sync $(EXTRA)
	cd frontend && $(NPM) install

dev-backend:      ## FastAPI on :8000 with reload
	cd backend && $(UV) run $(EXTRA) uvicorn app:app --reload --port 8000

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
