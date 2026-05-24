# Uses Microsoft's official Playwright image — includes all Chromium system deps
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium browser for Playwright
RUN playwright install chromium

# Copy bot source
COPY . .

# Railway runs the Procfile, but this CMD is a fallback
CMD ["python", "bot.py"]
