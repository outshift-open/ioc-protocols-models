# IOC L9 Makefile
# Automation for schema generation and language bindings

# Get the directory containing this Makefile and the project root
MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
PROJECT_ROOT := $(abspath $(MAKEFILE_DIR)/..)

# Configurable artifact publishing folder
ARTIFACT_PUBLISH_FOLDER ?= $(PROJECT_ROOT)/ioc_l9_artifacts

.PHONY: help all generate_spec generate_bindings generate_skills generate_docs publish_docs print-artifact-folder test_bindings test_skills publish_bindings clean_spec clean_bindings clean_skills clean_docs clean clean_pycache

# Default target
help:
	@echo "Available targets:"
	@echo "  all                       - Run all generation and testing (schema, bindings, skills, tests)"
	@echo "  generate_spec             - Generate JSON schema from Pydantic models"
	@echo "  generate_bindings [LANGUAGE=<language>] - Generate language bindings (python|golang|all)"
	@echo "  generate_skills [PLATFORM=<type>]        - Generate skills (claude|all)"
	@echo "  generate_docs             - Generate HTML documentation from JSON schema"
	@echo "  publish_docs              - Invoke docs/publish_docs.sh to generate and publish documentation artifacts"
	@echo "  test_bindings [LANGUAGE=<language>]     - Test language bindings (python|golang|all)"
	@echo "  test_skills [PLATFORM=<type>]           - Test skills generation (claude|all)"
	@echo "  publish_bindings [LANGUAGE=<language>]  - Publish language bindings (python|golang|all)"
	@echo "  publish_skills [PLATFORM=<platform>]    - Publish skills (claude|all)"
	@echo "  clean_spec                - Clean generated JSON schema file"
	@echo "  clean_bindings [LANGUAGE=<language>]    - Clean language bindings (python|golang|all)"
	@echo "  clean_skills [PLATFORM=<type>]          - Clean generated skills files (claude|all)"
	@echo "  clean_docs                - Clean generated documentation files"
	@echo "  clean_pycache             - Clean all __pycache__ directories and .pyc files"
	@echo "  clean_artifacts           - Clean published artifacts folder"
	@echo "  clean                     - Clean all generated files"
	@echo "  help                      - Show this help message"
	@echo ""
	@echo "Configuration:"
	@echo "  ARTIFACT_PUBLISH_FOLDER   - Directory for published artifacts (default: $(ARTIFACT_PUBLISH_FOLDER))"
	@echo ""
	@echo "Examples:"
	@echo "  make generate_spec"
	@echo "  make generate_bindings LANGUAGE=python"
	@echo "  make generate_bindings LANGUAGE=golang"
	@echo "  make generate_bindings              # generates all languages"
	@echo "  make test_bindings LANGUAGE=python"
	@echo "  make test_bindings                  # tests all languages"
	@echo "  make generate_skills PLATFORM=claude"
	@echo "  make generate_skills                # generates all skill types"
	@echo "  make test_skills PLATFORM=claude"
	@echo "  make test_skills                    # tests all skill types"
	@echo "  make clean_skills PLATFORM=claude"
	@echo "  make clean_bindings LANGUAGE=python"
	@echo "  make clean_bindings                 # cleans all language bindings"
	@echo "  make publish_skills PLATFORM=claude"
	@echo "  make publish_skills                 # publishes all platforms"

# Run complete pipeline to generate and validate artifacts
all:
	@echo "Running IOC L9 Protocol Pipeline to generate and validate artifacts..."
	@cd "$(PROJECT_ROOT)" && ./ioc_l9/scripts/generate_artifacts.sh

# Generate JSON schema spec
generate_spec:
	@echo "Generating JSON schema spec..."
	# todo add spec generation script and copy to spec/json_schema/l9.json (if generated at different path)
	@echo "JSON schema spec generated successfully!"

# Generate language bindings with parameter (defaults to all languages)
generate_bindings:
	@LANG_TO_USE="$(LANGUAGE)"; \
	if [ -z "$$LANG_TO_USE" ]; then \
		LANG_TO_USE="all"; \
	fi; \
	if [ "$$LANG_TO_USE" = "all" ]; then \
		echo "Generating bindings for all languages..."; \
		echo "Generating Python language bindings..."; \
		cd "$(PROJECT_ROOT)" && ./ioc_l9/language_bindings/python/generate.sh; \
		echo "Python bindings generated successfully!"; \
		echo "Generating Golang language bindings..."; \
		cd "$(PROJECT_ROOT)" && ./ioc_l9/language_bindings/golang/generate.sh; \
		echo "Golang bindings generated successfully!"; \
		echo "All language bindings generation completed!"; \
	elif [ "$$LANG_TO_USE" = "python" ]; then \
		echo "Generating Python language bindings..."; \
		cd "$(PROJECT_ROOT)" && ./ioc_l9/language_bindings/python/generate.sh; \
		echo "Python bindings generated successfully!"; \
	elif [ "$$LANG_TO_USE" = "golang" ]; then \
		echo "Generating Golang language bindings..."; \
		cd "$(PROJECT_ROOT)" && ./ioc_l9/language_bindings/golang/generate.sh; \
		echo "Golang bindings generated successfully!"; \
	else \
		echo "Error: Unsupported language '$$LANG_TO_USE'. Supported: python, golang, all"; \
		exit 1; \
	fi

# Generate skills with parameter (defaults to all skill types)
generate_skills:
	@PLATFORM_TO_USE="$(PLATFORM)"; \
	if [ -z "$$PLATFORM_TO_USE" ]; then \
		PLATFORM_TO_USE="all"; \
	fi; \
	if [ "$$PLATFORM_TO_USE" = "all" ]; then \
		echo "Generating skills for all types..."; \
		echo "Generating Claude skills..."; \
		cd "$(PROJECT_ROOT)" && poetry run python ./ioc_l9/skills/claude/generate.sh; \
		echo "Claude skills generated successfully!"; \
		echo "All skills generation completed!"; \
	elif [ "$$PLATFORM_TO_USE" = "claude" ]; then \
		echo "Generating Claude skills..."; \
		cd "$(PROJECT_ROOT)" && poetry run python ./ioc_l9/skills/claude/generate.sh; \
		echo "Claude skills generated successfully!"; \
	else \
		echo "Error: Unsupported skill type '$$PLATFORM_TO_USE'. Supported: claude, all"; \
		exit 1; \
	fi

# Test language bindings with parameter (defaults to all languages)
test_bindings:
	@LANG_TO_USE="$(LANGUAGE)"; \
	if [ -z "$$LANG_TO_USE" ]; then \
		LANG_TO_USE="all"; \
	fi; \
	if [ "$$LANG_TO_USE" = "all" ]; then \
		echo "Testing bindings for all languages..."; \
		cd "$(PROJECT_ROOT)" && ./ioc_l9/tests/run_tests.sh; \
	elif [ "$$LANG_TO_USE" = "python" ]; then \
		echo "Testing Python language bindings..."; \
		cd "$(PROJECT_ROOT)" && ./ioc_l9/tests/language_bindings/python/run_tests.sh; \
		if [ $$? -ne 0 ]; then exit 1; fi; \
	elif [ "$$LANG_TO_USE" = "golang" ]; then \
		echo "Testing Golang language bindings..."; \
		cd "$(PROJECT_ROOT)" && ./ioc_l9/tests/language_bindings/golang/run_tests.sh; \
		if [ $$? -ne 0 ]; then exit 1; fi; \
	else \
		echo "Error: Unsupported language '$$LANG_TO_USE'. Supported: python, golang, all"; \
		exit 1; \
	fi

# Test skills generation with parameter (defaults to all skill types)
test_skills:
	@SKILL_TO_USE="$(PLATFORM)"; \
	if [ -z "$$SKILL_TO_USE" ]; then \
		SKILL_TO_USE="all"; \
	fi; \
	if [ "$$SKILL_TO_USE" = "all" ]; then \
		echo "Testing skills for all types..."; \
		echo "Testing Claude skills..."; \
		if [ ! -d "skills/claude" ]; then \
			echo "❌ Claude skills directory not found: skills/claude"; \
			exit 1; \
		fi; \
		generated_count=$$(find skills/claude -mindepth 2 -name "SKILL_generated.md" -type f | wc -l); \
		if [ "$$generated_count" -eq 0 ]; then \
			echo "❌ No SKILL_generated.md files found in skills/claude subfolders"; \
			echo "Run 'make generate_skills PLATFORM=claude' first"; \
			exit 1; \
		else \
			echo "✅ Found $$generated_count Claude skill files in subfolders"; \
		fi; \
		echo "All skills tests passed!"; \
	elif [ "$$SKILL_TO_USE" = "claude" ]; then \
		echo "Testing Claude skills..."; \
		if [ ! -d "skills/claude" ]; then \
			echo "❌ Claude skills directory not found: skills/claude"; \
			exit 1; \
		fi; \
		generated_count=$$(find skills/claude -mindepth 2 -name "SKILL_generated.md" -type f | wc -l); \
		if [ "$$generated_count" -eq 0 ]; then \
			echo "❌ No SKILL_generated.md files found in skills/claude subfolders"; \
			echo "Run 'make generate_skills PLATFORM=claude' first"; \
			exit 1; \
		else \
			echo "✅ Found $$generated_count Claude skill files in subfolders"; \
		fi; \
		echo "Claude skills test passed!"; \
	else \
		echo "Error: Unsupported skill type '$$SKILL_TO_USE'. Supported: claude, all"; \
		exit 1; \
	fi

# Clean generated JSON schema file
clean_spec:
	@echo "Cleaning generated JSON schema file..."
	@rm -f spec/json_schema/l9.json
	@echo "JSON schema file cleaned!"

# Clean language bindings with parameter (defaults to all languages)
clean_bindings:
	@LANG_TO_USE="$(LANGUAGE)"; \
	if [ -z "$$LANG_TO_USE" ]; then \
		LANG_TO_USE="all"; \
	fi; \
	if [ "$$LANG_TO_USE" = "all" ]; then \
		echo "Cleaning bindings for all languages..."; \
		echo "Cleaning Python language bindings..."; \
		rm -f language_bindings/python/generated_models.py; \
		echo "Cleaning Golang language bindings..."; \
		rm -f language_bindings/golang/generated_models.go; \
		echo "All language bindings cleaned!"; \
	elif [ "$$LANG_TO_USE" = "python" ]; then \
		echo "Cleaning Python language bindings..."; \
		rm -f language_bindings/python/generated_models.py; \
		echo "Python bindings cleaned!"; \
	elif [ "$$LANG_TO_USE" = "golang" ]; then \
		echo "Cleaning Golang language bindings..."; \
		rm -f language_bindings/golang/generated_models.go; \
		echo "Golang bindings cleaned!"; \
	else \
		echo "Error: Unsupported language '$$LANG_TO_USE'. Supported: python, golang, all"; \
		exit 1; \
	fi

# Clean generated skills files with parameter (defaults to all skill types)
clean_skills:
	@SKILL_TO_USE="$(PLATFORM)"; \
	if [ -z "$$SKILL_TO_USE" ]; then \
		SKILL_TO_USE="all"; \
	fi; \
	if [ "$$SKILL_TO_USE" = "all" ]; then \
		echo "Cleaning skills for all types..."; \
		echo "Cleaning Claude skills..."; \
		find skills/claude -name "SKILL_generated.md" -type f -delete 2>/dev/null || true; \
		echo "All skills cleaned!"; \
	elif [ "$$SKILL_TO_USE" = "claude" ]; then \
		echo "Cleaning Claude skills..."; \
		find skills/claude -name "SKILL_generated.md" -type f -delete 2>/dev/null || true; \
		echo "Claude skills cleaned!"; \
	else \
		echo "Error: Unsupported skill type '$$SKILL_TO_USE'. Supported: claude, all"; \
		exit 1; \
	fi

# Generate HTML documentation from JSON schema
generate_docs:
	@echo "Generating documentation from JSON schema..."
	@echo "Installing dependencies..."
	@cd "$(PROJECT_ROOT)" && poetry install --with dev
	@mkdir -p docs/generated
	@cd "$(PROJECT_ROOT)" && poetry run python -m json_schema_for_humans.cli \
		--config-file ioc_l9/docs/config.json \
		ioc_l9/spec/json_schema/l9.json \
		ioc_l9/docs/generated/protocol_reference.html
	@echo "Documentation generated successfully!"
	@echo "Output: docs/generated/protocol_reference.html"

# Generate and publish documentation artifacts to configurable folder
publish_docs:
	@echo "Invoking documentation publishing script..."
	@./docs/publish_docs.sh

# Helper target to print the artifact folder path (used by scripts)
print-artifact-folder:
	@echo "$(ARTIFACT_PUBLISH_FOLDER)"

# Helper target to print the current version from schema (used by scripts)
print-version:
	@python3 -c "import json, os; schema_path=os.path.join('$(PROJECT_ROOT)', 'ioc_l9', 'spec', 'json_schema', 'l9.json'); f=open(schema_path); print(json.load(f)['version']); f.close()"

# Clean generated documentation files
clean_docs:
	@echo "Cleaning generated documentation files..."
	@rm -rf "$(PROJECT_ROOT)/ioc_l9/docs/generated/"
	@echo "Documentation files cleaned!"

# Clean all __pycache__ directories and .pyc files
clean_pycache:
	@echo "Cleaning Python cache files..."
	@find "$(PROJECT_ROOT)" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find "$(PROJECT_ROOT)" -type f -name "*.pyc" -delete 2>/dev/null || true
	@find "$(PROJECT_ROOT)" -type f -name "*.pyo" -delete 2>/dev/null || true
	@echo "Python cache files cleaned!"

# Clean published artifacts folder
clean_artifacts:
	@echo "Cleaning published artifacts..."
	@ARTIFACT_FOLDER=$$(make -s print-artifact-folder 2>/dev/null || echo "$(PROJECT_ROOT)/ioc_l9_artifacts"); \
	if [ -d "$$ARTIFACT_FOLDER" ]; then \
		echo "Removing contents of: $$ARTIFACT_FOLDER"; \
		rm -rf "$$ARTIFACT_FOLDER"/*; \
		echo "Artifacts folder contents cleaned!"; \
	else \
		echo "Artifacts folder does not exist: $$ARTIFACT_FOLDER"; \
	fi

# Clean all generated files (use with caution)
# WARNING: This will remove all generated files including schemas, language bindings and skills
clean:
	@echo "Cleaning generated files..."
	# @rm -f spec/json_schema/l9.json # todo commented out to preserve the schema
	@rm -f language_bindings/python/generated_models.py
	@rm -f language_bindings/golang/generated_models.go
	@find skills/claude -name "SKILL_generated.md" -type f -delete 2>/dev/null || true
	@rm -rf "$(PROJECT_ROOT)/ioc_l9/docs/generated/"
	@echo "Clean complete!"

# Publish language bindings with parameter (defaults to all languages)
publish_bindings:
	@LANG_TO_USE="$(LANGUAGE)"; \
	if [ -z "$$LANG_TO_USE" ]; then \
		LANG_TO_USE="all"; \
	fi; \
	echo "Publishing language bindings for: $$LANG_TO_USE"; \
	./language_bindings/publish_bindings.sh "$$LANG_TO_USE"

# Publish skills with parameter (defaults to all platforms)
publish_skills:
	@PLATFORM_TO_USE="$(PLATFORM)"; \
	if [ -z "$$PLATFORM_TO_USE" ]; then \
		PLATFORM_TO_USE="all"; \
	fi; \
	echo "Publishing skills for platform: $$PLATFORM_TO_USE"; \
	./skills/publish_skills.sh "$$PLATFORM_TO_USE"
