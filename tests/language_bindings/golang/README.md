# Golang Language Bindings Tests

This directory contains test suites for validating the Golang language bindings generated from the IOC L9 JSON Schema.

## Test Structure

```
golang/
├── README.md                    # This file
├── go.mod                       # Go module definition
├── model_validation_test.go     # Model validation tests (mirrors Python tests)
└── run_tests.sh                # Test runner script
```

## Test Categories

### Model Validation Tests (`model_validation_test.go`)

Tests validation features of generated models.

## Prerequisites

1. **Go Installation**: Go 1.21 or later must be installed
2. **Generated Models**: The Golang bindings must be generated first:
   ```bash
   make generate_bindings LANGUAGE=golang
   ```

## Running Tests

### From Project Root
```bash
# Run Golang tests specifically
make test_bindings LANGUAGE=golang

# Run all language binding tests
make test_bindings
```

### From This Directory
```bash
# Run the test script directly
./run_tests.sh

# Run specific tests
go test -v -run "TestL9HeaderValidation"
```

## Test Features

### Automatic Generation
If generated models are missing, the test runner will automatically:
1. Run the generation script
2. Create the `data_model.go` file
3. Proceed with testing

### Model Validation
Tests validate that:
- Required fields are properly enforced
- JSON serialization/deserialization works correctly
- Generated Go structs have proper structure
- Field names and types are correctly mapped
- JSON tags are properly generated

### CI/CD Integration
Tests are designed to:
- Return proper exit codes (0 for success, 1 for failure)
- Provide clear pass/fail indicators
- Work in automated environments
- Generate detailed test output

## Integration with CI/CD

These tests are designed to run in continuous integration pipelines to ensure:
- Generated bindings stay in sync with the JSON schema
- Breaking changes are detected early
- Code quality standards are maintained

## Troubleshooting

### Go Not Found
If you get "Go is not installed", install Go from https://golang.org/dl/

### Generated Models Missing
Run the generation command:
```bash
make generate_bindings LANGUAGE=golang
```

### Test Failures
Check that:
1. The JSON schema file exists at `SSTP/spec/l9_schema.json`
2. The schema contains valid JSON
3. The generated Go file has proper syntax

## Adding New Tests

To add new test cases:
1. Add test functions to `model_validation_test.go` (functions starting with `Test`)
2. Follow Go testing conventions and mirror Python test structure
3. Update the test runner script if needed
4. Document new tests in this README
