.PHONY: generate install test lint clean

# Regenerate the sstp package from the canonical source in ioc-cfn-cognitive-agents.
# Requires COGNITIVE_AGENTS_ROOT to point at the checked-out repo.
COGNITIVE_AGENTS_ROOT ?= $(abspath ../../../../..)
SRC := $(COGNITIVE_AGENTS_ROOT)/protocol

generate:
	@echo "Syncing SSTP Python sources from $(SRC)"
	cp -v "$(SRC)/l9_base.py"         src/sstp/
	cp -v "$(SRC)/ie/__init__.py"      src/sstp/ie/
	cp -v "$(SRC)/ie/l9.py"           src/sstp/ie/
	cp -v "$(SRC)/ie/adapter.py"      src/sstp/ie/
	cp -v "$(SRC)/ie/tom.py"          src/sstp/ie/
	find "$(SRC)/snp" -maxdepth 1 -name '*.py' ! -name '__main__.py' \
		-exec cp -v {} src/sstp/snp/ \;
	cp -v "$(SRC)/snp/ontology/snp_ontology.ttl" src/sstp/snp/ontology/

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

lint:
	mypy src/sstp/

clean:
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; true
