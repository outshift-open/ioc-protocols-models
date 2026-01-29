# Building the Package

## Prerequisites
- Python 3.8 or higher
- Poetry (will be installed automatically by build script if not present)

## Building the Wheel

### Using the build script (recommended):
```bash
./build_wheel.sh
```

### Manual build with Poetry:
```bash
# Install Poetry if not already installed
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Build the package
poetry build
```

This will create:
- `dist/ioc_cfn_protocols_models-0.1.0-py3-none-any.whl` (wheel distribution)
- `dist/ioc-cfn-protocols-models-0.1.0.tar.gz` (source distribution)

## Installing the Package

### With Poetry (recommended):
```bash
poetry install
```

### From wheel file:
```bash
pip install dist/ioc_cfn_protocols_models-0.1.0-py3-none-any.whl
```

### With optional dev dependencies:
```bash
poetry install --with dev
```

## Development Workflow

1. Make your changes to the code
2. Install dependencies: `poetry install`
3. Run tests (if available): `poetry run pytest`
4. Format code: `poetry run black .`
5. Build the wheel: `poetry build`
6. Install and test the wheel in a clean environment

## Publishing (if needed)

To publish to a package repository:

```bash
# Configure your repository (if using private repo)
poetry config repositories.myrepo https://myrepo.example.com

# Publish to PyPI (or your private repository)
poetry publish
```

## Clean Build Artifacts

```bash
rm -rf build/ dist/ *.egg-info
poetry cache clear . --all
```
