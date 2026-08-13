# Supervisor stopped providing BUILD_FROM by default in 2026.04.0, so the base
# image is named here. Still an ARG so a build can override it.
#
# base-python rather than plain base plus `apk add python3`: it pins the Python
# version instead of inheriting whatever the Alpine release happens to ship.
# 3.12 is the version the tests are run against, and the code needs at least
# 3.11 for enum.StrEnum.
ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.12-alpine3.24-2026.06.1
FROM $BUILD_FROM

# Install requirements for add-on
RUN python3 -m venv scharge_venv
COPY requirements.txt ./
RUN . scharge_venv/bin/activate; pip3 install -r requirements.txt

# Copy data for add-on
COPY src/* /
RUN chmod a+x /mqtt_client.py
COPY run_server.sh ./
RUN chmod a+x /run_server.sh

CMD [ "/run_server.sh" ]
