FROM python:3.12-slim

WORKDIR /app

# 使用国内 Debian 镜像源加速
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources

# 系统依赖 + Xvfb + noVNC（远程浏览器查看）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    xvfb \
    x11vnc \
    fluxbox \
    novnc \
    websockify \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖（使用国内镜像加速）
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt

# 安装 Playwright Chromium 系统依赖 + 浏览器
# 分两步：先用国内镜像装系统依赖，再下载浏览器
RUN playwright install-deps chromium \
    && playwright install chromium

# 应用代码
COPY . .

# noVNC 启动脚本
COPY scripts/start-novnc.sh /app/start-novnc.sh
RUN chmod +x /app/start-novnc.sh

# 数据目录
RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99

EXPOSE 8000 6080

CMD ["/app/start-novnc.sh"]
