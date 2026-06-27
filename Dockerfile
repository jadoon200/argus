FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for layer caching. (Switch to requirements.lock for
# reproducible builds once `make lock` has been run — see Makefile.)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install --no-cache-dir --no-deps .

CMD ["python", "-m", "argus.ingest.flows"]
