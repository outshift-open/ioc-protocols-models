# Python Language Bindings Tests

This directory contains test suites for validating the Python language bindings generated from the IOC L9 JSON Schema.

## Test Structure

```
python/
├── README.md                    # This file
├── test_model_validation.py     # Basic validation tests for generated models
└── run_tests.sh                # Test runner script
```

## Test Categories

### Model Validation Tests (`test_model_validation.py`)

Tests validation features of generated Pydantic models.


## Prerequisites

1. **Python Installation**: Python 3.8 or later
2. **Poetry**: For dependency management
3. **Generated Models**: The Python bindings must be generated first:
   ```bash
   make generate_bindings LANGUAGE=python
   ```

## Running Tests

### From Project Root
```bash
# Run Python tests specifically
make test_bindings LANGUAGE=python

# Run all language binding tests
make test_bindings
```

### From This Directory
```bash
# Run the test script directly
./run_tests.sh

# Run the test file
poetry run pytest test_model_validation.py -v

# Run specific tests
poetry run pytest -k "test_l9_header_validation" -v
```

## Test Features

### Automatic Generation
If generated models are missing, the test runner will automatically:
1. Run the generation script
2. Create the `data_model.py` file
3. Proceed with testing

### Model Validation
Tests validate that:
- Required fields are properly enforced using Pydantic validation
- Type validation works correctly (string, int, etc.)
- Nested model validation functions properly
- JSON serialization/deserialization works correctly
- ValidationError is raised for invalid data
- Generated models have proper structure and field mappings

### CI/CD Integration
Tests are designed to:
- Return proper exit codes (0 for success, 1 for failure)
- Provide clear pass/fail indicators
- Work in automated environments
- Generate detailed pytest output with `-v` flag

## Integration with CI/CD

These tests are designed to run in continuous integration pipelines to ensure:
- Generated bindings stay in sync with the JSON schema
- Breaking changes are detected early
- Pydantic validation works as expected
- Generated models maintain proper structure and functionality

## Troubleshooting

### Poetry Not Found
If you get "poetry: command not found", install Poetry:
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

### Generated Models Missing
Run the generation command:
```bash
make generate_bindings LANGUAGE=python
```

### Import Errors
Ensure dependencies are installed:
```bash
poetry install --with dev
```

### Test Failures
Check that:
1. The JSON schema file exists at `SSTP/spec/l9_schema.json`
2. The schema contains valid JSON
3. The generated Python file has proper syntax
4. All required dependencies are installed

## Adding New Tests

To add new test cases:
1. Add test functions to `test_model_validation.py`
2. Follow pytest conventions (functions starting with `test_`)
3. Use Pydantic ValidationError for validation testing
4. Mirror test structure with Golang tests when possible
5. Update this README to document new tests

## Dependencies

The tests use the following key dependencies:
- **pytest**: Testing framework
- **pydantic**: Data validation (used by generated models)
- **datamodel-code-generator**: Code generation tool
- **poetry**: Dependency management

All dependencies are managed through `pyproject.toml` in the project root.
