FROM python:3.10-slim

WORKDIR /app
COPY . /app

# Install dependencies (none if you're just using requests)
RUN pip install requests

CMD ["python", "intercom_report.py"]
