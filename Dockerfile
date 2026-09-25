FROM ubuntu:24.04 AS rtklib-builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN git clone --depth 1 https://github.com/tomojitakasu/RTKLIB.git
RUN make -C RTKLIB/app/convbin/gcc \
    && make -C RTKLIB/app/rnx2rtkp/gcc
FROM python:3.11-slim AS app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=rtklib-builder /build/RTKLIB/app/convbin/gcc/convbin /usr/local/bin/convbin
COPY --from=rtklib-builder /build/RTKLIB/app/rnx2rtkp/gcc/rnx2rtkp /usr/local/bin/rnx2rtkp
RUN chmod +x /usr/local/bin/convbin /usr/local/bin/rnx2rtkp
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/ apps/
COPY common/ common/
COPY services/ services/
COPY ml/ ml/
COPY scripts/ scripts/
COPY pyproject.toml .
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
