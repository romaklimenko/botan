FROM python:3.11-alpine
COPY . /
RUN pip install -r requirements.txt
