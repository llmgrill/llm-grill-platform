.SILENT:
.DEFAULT_GOAL: help

help:
	echo "Please use \`make \033[36m<target>\033[0m\`"
	echo "\t where \033[36m<target>\033[0m is one of"
	grep -E '^\.PHONY: [a-zA-Z_-]+ .*?## .*$$' $(MAKEFILE_LIST) \
		| sort | awk 'BEGIN {FS = "(: |##)"}; {printf "• \033[36m%-30s\033[0m %s\n", $$2, $$3}'

.PHONY: lint ## 🕵 run lint
lint: setup-dev
	uv run ruff check . --fix
	uv run ruff format .
	make check

.PHONY: check ## 🕵 run check
check: setup-dev
	uv run ruff check .
	uv run ty check

.PHONY: setup ## 🔧 setup
setup:
	uv sync --frozen --all-groups

.PHONY: setup-dev ## 🔧 setup-dev
setup-dev:
	uv sync --frozen --group dev

.PHONY: test ## 🧪 test
test: setup-dev
	uv run pytest -v --cov=src --cov-report=html --cov-report=term
