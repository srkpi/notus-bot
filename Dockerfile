FROM python:3.8-slim

ARG BOT_TOKEN
ARG MONGO_URL

ENV BOT_TOKEN=${BOT_TOKEN}
ENV MONGO_URL=${MONGO_URL}

WORKDIR /app

COPY . /app

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

EXPOSE 8081

HEALTHCHECK --interval=60s --timeout=40s --start-period=10s --retries=7 CMD curl -f http://localhost:8081/health || pkill -f main.py && python ./main.py

CMD ["python", "./main.py"]
