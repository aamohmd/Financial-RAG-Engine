FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose the port the app runs on
EXPOSE 8080

# Define the command to run the application
CMD ["fastapi", "run", "rag/api.py", "--port", "8080", "--host", "0.0.0.0"]
