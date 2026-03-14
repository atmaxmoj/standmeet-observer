.PHONY: setup start stop status logs

setup:
	bash scripts/setup.sh

start:
	@pgrep -x screenpipe >/dev/null 2>&1 || { screenpipe > /tmp/screenpipe.log 2>&1 & echo "screenpipe started"; }
	docker compose up -d

stop:
	docker compose down
	@pkill screenpipe 2>/dev/null && echo "screenpipe stopped" || true

status:
	@echo "--- screenpipe ---"
	@pgrep -x screenpipe >/dev/null 2>&1 && echo "running (pid $$(pgrep -x screenpipe))" || echo "not running"
	@echo ""
	@echo "--- bisimulator ---"
	@docker compose ps 2>/dev/null
	@echo ""
	@curl -s http://localhost:5001/engine/status 2>/dev/null || echo "API not reachable"

logs:
	docker compose logs -f
