# docker build -t romaklimenko.azurecr.io/botan:latest .
docker buildx build --platform=linux/amd64 -t romaklimenko.azurecr.io/botan:latest .