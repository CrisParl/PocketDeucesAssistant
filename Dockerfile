# Use Python 3.11 (stable for aiohttp/py-cord)
FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Copy requirements first and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your bot code
COPY . .

# Run the bot
CMD ["python", "PocketDeucesAssistant.py"]
