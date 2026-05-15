.SILENT:
.DEFAULT_GOAL: help

COMPOSE_BASE = docker-compose -f docker-compose.yml -f docker-compose.dev.yml
COMPOSE_MIG  = $(COMPOSE_BASE) -f docker-compose.with-migrations.yaml

help:
	echo "Please use \`make \033[36m<target>\033[0m\`"
	echo "\t where \033[36m<target>\033[0m is one of"
	grep -E '^\.PHONY: [a-zA-Z_-]+ .*?## .*$$' $(MAKEFILE_LIST) \
		| sort | awk 'BEGIN {FS = "(: |##)"}; {printf "• \033[36m%-30s\033[0m %s\n", $$2, $$3}'

.PHONY: up ## 🚀 Start stack with migrations
up:
	$(COMPOSE_MIG) up --build --force-recreate -d orchestrator postgres migration

.PHONY: up-no-mig ## 🚀 Start stack without running migrations
up-no-mig:
	$(COMPOSE_BASE) up --build --force-recreate -d orchestrator postgres

.PHONY: up-debug ## 🐛 Start stack with migrations (foreground, streaming logs)
up-debug:
	$(COMPOSE_MIG) up --build --force-recreate orchestrator postgres migration

.PHONY: down ## 📉 Stop and remove containers
down:
	$(COMPOSE_BASE) down

.PHONY: down-volumes ## 💣 Stop and remove containers + volumes (wipes DB)
down-volumes:
	$(COMPOSE_BASE) down -v

.PHONY: logs ## 📋 Follow orchestrator logs
logs:
	$(COMPOSE_BASE) logs -f orchestrator

.PHONY: logs-all ## 📋 Follow all service logs
logs-all:
	$(COMPOSE_BASE) logs -f

.PHONY: vm-logs ## 🔍 Tail journalctl runner sur la VM d'un run (RUN_ID=<uuid>)
vm-logs:
	@test -n "$(RUN_ID)" || { echo "usage: make vm-logs RUN_ID=<uuid>"; exit 1; }
	@IP=$$(curl -sf http://localhost:8000/runs/$(RUN_ID) | jq -r '.node_ip // empty'); \
	 test -n "$$IP" || { echo "no node ip for run $(RUN_ID)"; exit 1; }; \
	 echo "→ ssh root@$$IP"; \
	 ssh -o StrictHostKeyChecking=accept-new root@$$IP "journalctl -u llmgrill-runner -f"

.PHONY: vm-cloud-init ## 🔍 Tail cloud-init logs sur la VM d'un run (RUN_ID=<uuid>)
vm-cloud-init:
	@test -n "$(RUN_ID)" || { echo "usage: make vm-cloud-init RUN_ID=<uuid>"; exit 1; }
	@IP=$$(curl -sf http://localhost:8000/runs/$(RUN_ID) | jq -r '.node_ip // empty'); \
	 test -n "$$IP" || { echo "no node ip for run $(RUN_ID)"; exit 1; }; \
	 echo "→ ssh root@$$IP"; \
	 ssh -o StrictHostKeyChecking=accept-new root@$$IP "tail -f /var/log/cloud-init-output.log"

.PHONY: vm-shell ## 🖥  SSH dans la VM d'un run (RUN_ID=<uuid>)
vm-shell:
	@test -n "$(RUN_ID)" || { echo "usage: make vm-shell RUN_ID=<uuid>"; exit 1; }
	@IP=$$(curl -sf http://localhost:8000/runs/$(RUN_ID) | jq -r '.node_ip // empty'); \
	 test -n "$$IP" || { echo "no node ip for run $(RUN_ID)"; exit 1; }; \
	 echo "→ ssh root@$$IP"; \
	 ssh -o StrictHostKeyChecking=accept-new root@$$IP

.PHONY: run-logs ## 📜 Affiche les logs S3 d'un run (RUN_ID=<uuid>)
run-logs:
	@test -n "$(RUN_ID)" || { echo "usage: make run-logs RUN_ID=<uuid>"; exit 1; }
	@curl -sf http://localhost:8000/runs/$(RUN_ID)/logs || echo "no logs uploaded yet"
