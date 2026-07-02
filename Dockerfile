FROM python:3.11-slim

WORKDIR /app

# PyMuPDF 需要的系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 项目代码
COPY . .

# 数据目录
RUN mkdir -p /app/data/parsed /app/data/chroma_db /app/data/raw /app/data/processed /app/logs

EXPOSE 8000 8501

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
