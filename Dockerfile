# The API image, with the database baked in read-only.
#
# DESIGN.md section 7 turns that into a feature rather than a limitation: the base data is
# immutable historical fact, so a read-only file is exactly right, and per-caller scenarios are
# overlays in process memory. Nothing the container serves can write to it, which is what makes
# an unauthenticated public URL a reasonable thing to deploy.
#
# The database is built at image build time from the committed CSV, not downloaded and not
# copied from a developer's machine. The image is therefore reproducible from the repository
# alone, and a container that starts is a container whose data loaded.

FROM python:3.11-slim AS build
WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
COPY data/sample/bts_wn_2026_01_w1.csv.gz ./data/sample/
RUN pip install --no-cache-dir . \
 && python -m flightops.ingest.sample /build/data/sample/sample.duckdb \
                                                     /build/data/sample/bts_wn_2026_01_w1.csv.gz

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLIGHTOPS_DB=/app/data/sample.duckdb \
    FLIGHTOPS_TRANSCRIPTS=/app/data/transcripts \
    PORT=8000

COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=build /usr/local/bin /usr/local/bin
COPY --from=build /build/data/sample/sample.duckdb /app/data/sample.duckdb
COPY data/transcripts /app/data/transcripts

# Non-root, because there is no reason for this process to be able to write anything.
RUN useradd --create-home --uid 10001 flightops && chown -R flightops /app
USER flightops

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",8000)}/api/health').read()"

CMD ["sh", "-c", "uvicorn flightops.api.app:app --host 0.0.0.0 --port ${PORT}"]
