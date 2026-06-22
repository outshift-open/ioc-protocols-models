# IOC Protocols Models - Root Makefile
# Automation for schema generation, language bindings, and documentation

PROJECT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
SCHEMA_FILE := $(PROJECT_ROOT)/SSTP/spec/l9_schema.json
ARTIFACT_PUBLISH_FOLDER := $(PROJECT_ROOT)/SSTP/documentation

.PHONY: help all generate_bindings generate_docs publish_docs publish_bindings test_bindings clean_bindings clean_docs clean clean_pycache print-version print-artifact-folder

help:
	@echo "Available targets:"
	@echo "  all                       - Run full generation pipeline (bindings + docs + tests)"
	@echo "  generate_bindings [LANGUAGE=<language>] - Generate language bindings (python|golang|all)"
	@echo "  generate_docs             - Generate HTML documentation from JSON schema"
	@echo "  publish_docs              - Publish documentation artifacts to SSTP/documentation/"
	@echo "  publish_bindings [LANGUAGE=<language>]  - Publish Go module with version tag (golang|all)"
	@echo "  test_bindings [LANGUAGE=<language>]     - Test language bindings (python|golang|all)"
	@echo "  clean_bindings [LANGUAGE=<language>]    - Clean language bindings (python|golang|all)"
	@echo "  clean_docs                - Clean generated documentation files"
	@echo "  clean_pycache             - Clean all __pycache__ directories and .pyc files"
	@echo "  clean                     - Clean all generated files"
	@echo "  print-version             - Print schema version"
	@echo "  print-artifact-folder     - Print artifact publish folder path"
	@echo "  help                      - Show this help message"
	@echo ""
	@echo "Configuration:"
	@echo "  SCHEMA_FILE               - JSON schema source ($(SCHEMA_FILE))"
	@echo "  ARTIFACT_PUBLISH_FOLDER   - Artifact output dir ($(ARTIFACT_PUBLISH_FOLDER))"
	@echo ""
	@echo "Examples:"
	@echo "  make generate_bindings LANGUAGE=python"
	@echo "  make generate_bindings LANGUAGE=golang"
	@echo "  make generate_bindings              # generates all languages"
	@echo "  make test_bindings LANGUAGE=python"
	@echo "  make test_bindings                  # tests all languages"
	@echo "  make clean_bindings LANGUAGE=python"
	@echo "  make clean_bindings                 # cleans all language bindings"

all:
	@echo "Running IOC L9 Protocol Pipeline..."
	@cd "$(PROJECT_ROOT)" && ./scripts/generate_artifacts.sh

generate_bindings:
	@LANG_TO_USE="$(LANGUAGE)"; \
	if [ -z "$$LANG_TO_USE" ]; then \
		LANG_TO_USE="all"; \
	fi; \
	if [ "$$LANG_TO_USE" = "all" ]; then \
		echo "Generating bindings for all languages..."; \
		echo "Generating Python language bindings..."; \
		cd "$(PROJECT_ROOT)" && ./SSTP/language_bindings/python/generate.sh; \
		echo "Python bindings generated successfully!"; \
		echo "Generating Golang language bindings..."; \
		cd "$(PROJECT_ROOT)" && ./SSTP/language_bindings/golang/generate.sh; \
		echo "Golang bindings generated successfully!"; \
		echo "All language bindings generation completed!"; \
	elif [ "$$LANG_TO_USE" = "python" ]; then \
		echo "Generating Python language bindings..."; \
		cd "$(PROJECT_ROOT)" && ./SSTP/language_bindings/python/generate.sh; \
		echo "Python bindings generated successfully!"; \
	elif [ "$$LANG_TO_USE" = "golang" ]; then \
		echo "Generating Golang language bindings..."; \
		cd "$(PROJECT_ROOT)" && ./SSTP/language_bindings/golang/generate.sh; \
		echo "Golang bindings generated successfully!"; \
	else \
		echo "Error: Unsupported language '$$LANG_TO_USE'. Supported: python, golang, all"; \
		exit 1; \
	fi

generate_docs:
	@echo "Generating documentation from JSON schema..."
	@echo "Installing dependencies..."
	@cd "$(PROJECT_ROOT)" && poetry install --with dev
	@cd "$(PROJECT_ROOT)" && poetry run python -m json_schema_for_humans.cli \
		--config-file SSTP/documentation/config.json \
		SSTP/spec/l9_schema.json \
		SSTP/documentation/protocol_reference.html
	@echo "Documentation generated successfully!"
	@echo "Output: SSTP/documentation/protocol_reference.html"

publish_docs:
	@echo "Publishing documentation artifacts..."
	@cd "$(PROJECT_ROOT)" && ./SSTP/documentation/publish_docs.sh

# TODO: Python PyPI publishing will be added via CI/CD pipeline later
publish_bindings:
	@LANG_TO_USE="$(LANGUAGE)"; \
	if [ -z "$$LANG_TO_USE" ]; then \
		LANG_TO_USE="all"; \
	fi; \
	cd "$(PROJECT_ROOT)" && ./SSTP/language_bindings/publish_bindings.sh "$$LANG_TO_USE"

test_bindings:
	@LANG_TO_USE="$(LANGUAGE)"; \
	if [ -z "$$LANG_TO_USE" ]; then \
		LANG_TO_USE="all"; \
	fi; \
	if [ "$$LANG_TO_USE" = "all" ]; then \
		echo "Testing bindings for all languages..."; \
		cd "$(PROJECT_ROOT)" && ./tests/run_tests.sh; \
	elif [ "$$LANG_TO_USE" = "python" ]; then \
		echo "Testing Python language bindings..."; \
		cd "$(PROJECT_ROOT)" && ./tests/language_bindings/python/run_tests.sh; \
		if [ $$? -ne 0 ]; then exit 1; fi; \
	elif [ "$$LANG_TO_USE" = "golang" ]; then \
		echo "Testing Golang language bindings..."; \
		cd "$(PROJECT_ROOT)" && ./tests/language_bindings/golang/run_tests.sh; \
		if [ $$? -ne 0 ]; then exit 1; fi; \
	else \
		echo "Error: Unsupported language '$$LANG_TO_USE'. Supported: python, golang, all"; \
		exit 1; \
	fi

clean_bindings:
	@LANG_TO_USE="$(LANGUAGE)"; \
	if [ -z "$$LANG_TO_USE" ]; then \
		LANG_TO_USE="all"; \
	fi; \
	if [ "$$LANG_TO_USE" = "all" ]; then \
		echo "Cleaning bindings for all languages..."; \
		echo "Cleaning Python language bindings..."; \
		rm -f "$(PROJECT_ROOT)/SSTP/language_bindings/python/generated_models.py"; \
		echo "Cleaning Golang language bindings..."; \
		rm -f "$(PROJECT_ROOT)/SSTP/language_bindings/golang/generated_models.go"; \
		echo "All language bindings cleaned!"; \
	elif [ "$$LANG_TO_USE" = "python" ]; then \
		echo "Cleaning Python language bindings..."; \
		rm -f "$(PROJECT_ROOT)/SSTP/language_bindings/python/generated_models.py"; \
		echo "Python bindings cleaned!"; \
	elif [ "$$LANG_TO_USE" = "golang" ]; then \
		echo "Cleaning Golang language bindings..."; \
		rm -f "$(PROJECT_ROOT)/SSTP/language_bindings/golang/generated_models.go"; \
		echo "Golang bindings cleaned!"; \
	else \
		echo "Error: Unsupported language '$$LANG_TO_USE'. Supported: python, golang, all"; \
		exit 1; \
	fi

clean_docs:
	@echo "Cleaning generated documentation files..."
	@rm -f "$(PROJECT_ROOT)/SSTP/documentation/protocol_reference.html"
	@rm -f "$(PROJECT_ROOT)/SSTP/documentation/schema_doc.css"
	@rm -f "$(PROJECT_ROOT)/SSTP/documentation/schema_doc.min.js"
	@echo "Documentation files cleaned!"

clean_pycache:
	@echo "Cleaning Python cache files..."
	@find "$(PROJECT_ROOT)" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find "$(PROJECT_ROOT)" -type f -name "*.pyc" -delete 2>/dev/null || true
	@find "$(PROJECT_ROOT)" -type f -name "*.pyo" -delete 2>/dev/null || true
	@echo "Python cache files cleaned!"

clean:
	@echo "Cleaning generated files..."
	@rm -f "$(PROJECT_ROOT)/SSTP/language_bindings/python/generated_models.py"
	@rm -f "$(PROJECT_ROOT)/SSTP/language_bindings/golang/generated_models.go"
	@rm -f "$(PROJECT_ROOT)/SSTP/documentation/protocol_reference.html"
	@rm -f "$(PROJECT_ROOT)/SSTP/documentation/schema_doc.css"
	@rm -f "$(PROJECT_ROOT)/SSTP/documentation/schema_doc.min.js"
	@echo "Clean complete!"

print-version:
	@python3 -c "import json; f=open('$(SCHEMA_FILE)'); print(json.load(f)['version']); f.close()"

print-artifact-folder:
	@echo "$(ARTIFACT_PUBLISH_FOLDER)"
