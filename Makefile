UV ?= $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)
NPM ?= $(shell command -v npm 2>/dev/null || echo $(HOME)/.local/bin/npm)
export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: setup dev-backend dev-frontend test eval clips build

setup:            ## install backend + frontend deps
	cd backend && $(UV) sync
	cd frontend && $(NPM) install

dev-backend:      ## FastAPI on :8000 with reload
	cd backend && $(UV) run uvicorn app:app --reload --port 8000

dev-frontend:     ## Vite dashboard on :5173
	cd frontend && $(NPM) run dev

test:             ## backend unit + integration tests
	cd backend && $(UV) run pytest -q

eval:             ## offline eval over data/eval/labels.csv; NOTE="..." to annotate the history row
	$(UV) run --project backend python scripts/eval.py --note "$(NOTE)"

clips:            ## regenerate demo clips with macOS `say` + ffmpeg
	$(UV) run --project backend python scripts/make_clips.py

build:            ## production build of the dashboard
	cd frontend && $(NPM) run build
