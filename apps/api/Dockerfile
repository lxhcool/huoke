FROM python:3.12-slim

WORKDIR /app

# 系统依赖（含 Playwright Chromium 所需的系统库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Playwright Chromium 浏览器及系统依赖
RUN playwright install --with-deps chromium

# 应用代码
COPY . .

# 数据目录
RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
