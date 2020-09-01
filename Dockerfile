# Main stuff
FROM python:3.8-slim-buster as main

WORKDIR /usr/src/app

COPY requirements.txt .

RUN pip3 install --upgrade pip wheel setuptools \
 && pip3 install -r requirements.txt

COPY . .

# Launch
CMD python3 ./server.py

# Test stuff
FROM main as test
COPY test-requirements.txt .
RUN pip install --no-warn-script-location -r test-requirements.txt

# Run tests
ENTRYPOINT [ "bash", "test.sh" ]

