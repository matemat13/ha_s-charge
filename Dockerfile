ARG BUILD_FROM
FROM $BUILD_FROM

# Install requirements for add-on
RUN apk add --no-cache python3 py3-pip
RUN python3 -m venv scharge_venv
RUN . scharge_venv/bin/activate; pip3 install paho-mqtt aiomqtt websockets

# Copy data for add-on
COPY src/* /
RUN chmod a+x /mqtt_client.py
COPY run_server.sh ./
RUN chmod a+x /run_server.sh

CMD [ "/run_server.sh" ]
