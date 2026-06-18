# IOC L9 Protocol - Published Artifacts

This directory contains published artifacts and release management scripts for the IOC L9 Protocol.

## Published Artifacts

- Docs
- Language Bindings
- Skills  

## Language Bindings

### Python Package

#### Installation
```bash
# Install latest version
pip install ioc-l9

# Install specific version
pip install ioc-l9==1.0.0

# With poetry
poetry add ioc-l9@1.0.0
```

#### Usage Examples
See the comprehensive test suite for working examples:
- **Model validation tests**: `tests/language_bindings/python/test_model_validation.py`
- **JSON schema validation**: `tests/language_bindings/python/test_model_validation.py`
- **Complete L9 message examples**: Shows actor creation, semantic context, header/payload construction, and JSON serialization/validation

### Go Module

#### Installation
```bash
# Add to your project (specific version)
go get github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang@v1.0.0

# Get latest version
go get github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang@latest

# Update go.mod
go mod tidy
```

#### Usage Examples
See the comprehensive test suite for working examples:
- **Model validation tests**: `tests/language_bindings/golang/model_validation_test.go`
- **JSON serialization tests**: `tests/language_bindings/golang/model_validation_test.go`
- **Complete L9 message examples**: Shows struct initialization, JSON marshaling/unmarshaling, and validation patterns

## Version Management

### Checking Available Versions

#### Python
```bash
# List all versions
pip index versions ioc-l9

# Check current version
pip show ioc-l9
```

#### Go
```bash
# List available versions
go list -m -versions github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang

# Check current version in project
go list -m github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang

# List all published Go module tags
git ls-remote --tags origin | grep "ioc_l9/language_bindings/golang"

# Verify specific version availability
go list -m github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang@v1.0.0
```

### Dependency Management

#### Python Requirements
```txt
# requirements.txt
ioc-l9==1.0.0
requests>=2.28.0
pydantic>=2.0.0
```

```toml
# pyproject.toml
[tool.poetry.dependencies]
python = "^3.9"
ioc-l9 = "1.0.0"
requests = "^2.28.0"
```

#### Go Dependencies
```go
// go.mod
module your-service

go 1.21

require (
    github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang v1.0.0
    github.com/gorilla/mux v1.8.0
)
```

## Troubleshooting

### Common Issues

#### Python Package Not Found
```bash
# Update pip
pip install --upgrade pip

# Clear cache
pip cache purge

# Install with verbose output
pip install -v ioc-l9
```

#### Go Module Access Issues
```bash
# Clear module cache
go clean -modcache

# Verify network access
go env GOPROXY

# Use direct access if needed
GOPROXY=direct go get github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang
```

#### Version Conflicts
```bash
# Python - check for conflicts
pip check

# Go - update dependencies
go mod tidy
go mod verify
```

### Authentication for Private Repositories

#### Git Credentials
```bash
# Using personal access token
git config --global url."https://username:token@github.com/".insteadOf "https://github.com/"

# Using SSH (recommended)
git config --global url."git@github.com:".insteadOf "https://github.com/"
```

#### Go Private Module Configuration
```bash
# Set private module patterns
go env -w GOPRIVATE=github.com/cisco-eti/*

# Configure Git for Go modules
git config --global url."git@github.com:".insteadOf "https://github.com/"
```

## Support and Maintenance

### Getting Help
- **Issues**: Report problems at https://github.com/cisco-eti/ioc-protocols-models/issues
- **Documentation**: Latest docs available in repository releases
- **Schema Reference**: Generated HTML documentation included with releases

### Contributing
- **Bug Reports**: Include version information and minimal reproduction case
- **Feature Requests**: Describe use case and proposed API changes
- **Pull Requests**: Follow the contribution guidelines in the main repository

### Release Notes
Check the repository releases page for:
- **Breaking Changes**: API modifications requiring code updates
- **New Features**: Additional protocol capabilities
- **Bug Fixes**: Resolved issues and improvements
- **Migration Guides**: Instructions for upgrading between major versions

---

**Repository**: https://github.com/cisco-eti/ioc-protocols-models/  
**Python Package**: https://pypi.org/project/ioc-l9/  
**Go Module**: github.com/cisco-eti/ioc-protocols-models/ioc_l9/language_bindings/golang
