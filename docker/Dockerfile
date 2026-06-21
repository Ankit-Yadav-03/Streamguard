FROM python:3.11-slim

WORKDIR /app

# Copy metadata
COPY pyproject.toml .
COPY README.md .

# Copy core library + examples
COPY stream_guard ./stream_guard
COPY example ./example

# Install package
RUN pip install --no-cache-dir -e .

EXPOSE 8000

# Run the example FastAPI app
CMD ["uvicorn", "example.app:app", "--host", "0.0.0.0", "--port", "8000"]
