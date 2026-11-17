# The image CI jobs run faire in (the FAIRE_IMAGE variable): DataLad and git-annex for the
# datasets, Apptainer to run the containers that rules declare, and faire itself.
#
#   docker build -t faire .
ARG ALPINE=3.24.2

FROM alpine:${ALPINE}

# squashfuse: the xattr segfault fix (vasi/squashfuse#149) first shipped in 0.6.3. Alpine's stable
# repositories still carry 0.6.1, so this one package comes from `edge` (tagged repository, so
# nothing else is taken from it). Drop this block once the stable release has >= 0.6.3.
RUN echo "@edge https://dl-cdn.alpinelinux.org/alpine/edge/community" >> /etc/apk/repositories \
    && apk add --no-cache "squashfuse@edge>=0.6.3" \
    && apk info -v squashfuse

ENV APPTAINER_TMPDIR="/tmp-apptainer" \
    VIRTUAL_ENV=/opt/faire \
    PATH="/opt/faire/bin:$PATH"

RUN apk add --no-cache \
        apptainer ca-certificates libseccomp squashfs-tools fuse2fs fuse-overlayfs gocryptfs \
        python3 py3-pip git git-annex openssh-client curl bzip2 bash jq 7zip tzdata \
    && mkdir -p "$APPTAINER_TMPDIR" \
    && cp /usr/share/zoneinfo/UTC /etc/localtime \
    && apk del tzdata \
    && rm -rf /tmp/* /var/cache/apk/*

# faire and its dependencies (DataLad, datalad-container, copier, python-gitlab, ...)
COPY pyproject.toml README.md /src/faire/
COPY src /src/faire/src
RUN python3 -m venv "$VIRTUAL_ENV" \
    && pip install --no-cache-dir /src/faire \
    && rm -rf /src \
    && faire --version \
    && git annex version | head -n 1 \
    && datalad --version \
    && apptainer --version

WORKDIR /work
