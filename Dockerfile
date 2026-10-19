# MyFitnessPal MCP Server
# 
# Legacy image definition, unsupported by the restricted macOS edition.
# Authentication requires the native macOS Keychain; Linux containers cannot
# run this edition. Do not mount browser profiles into this container.
#
# Build: docker build -t mfp-mcp .
# For supported deployment, follow the native macOS instructions in README.md.

FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the package
RUN pip install --no-cache-dir -e .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash mcp
USER mcp

# Expose default port (for HTTP transport if needed)
EXPOSE 8000

# Default command runs the MCP server with stdio transport
ENTRYPOINT ["python", "-m", "mfp_mcp.server"]
