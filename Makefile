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
	$(COMPOSE_MIG) up --build --force-recreate -d

.PHONY: up-no-mig ## 🚀 Start stack without running migrations
up-no-mig:
	$(COMPOSE_BASE) up --build --force-recreate -d

.PHONY: up-debug ## 🐛 Start stack with migrations (foreground, streaming logs)
up-debug:
	$(COMPOSE_MIG) up --build --force-recreate

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
