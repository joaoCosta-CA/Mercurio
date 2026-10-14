FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir '.[server]'
RUN useradd --create-home --uid 10001 mercurio
USER 10001
ENV MERCURIO_SERVER_DB=/data/mercurio-server.db
EXPOSE 8080
CMD ["uvicorn", "mercurio_server.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]

