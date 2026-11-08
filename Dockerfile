FROM eclipse-temurin:21-jdk@sha256:3e3c176ffed168beb42c607be9bc1639b466cf00261a0fb04425562c9d0c5c2b AS jdk21

FROM python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641 AS maven
COPY scripts/install_apache_maven.py /tmp/install_apache_maven.py
RUN python /tmp/install_apache_maven.py

FROM python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641

# Lets an operator match their own host UID/GID so writes to the bind-mounted
# paths in docker-compose.yml (which keep the HOST's ownership regardless of
# anything set in this image) don't hit permission errors. See
# .env.docker.example.
ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    JAVA_HOME=/opt/java/openjdk \
    MAVEN_HOME=/opt/maven \
    PATH="/opt/maven/bin:/opt/java/openjdk/bin:${PATH}"

COPY --from=jdk21 /opt/java/openjdk /opt/java/openjdk
COPY --from=maven /opt/maven /opt/maven

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

# --create-home so Maven has a writable $HOME/.m2 for its local repository
# cache -- Studio's Build & Run shells out to `mvn` inside this container.
# The base image already owns some low GIDs (e.g. Debian's "dialout" is 20,
# which also happens to be macOS's default "staff" GID) -- reuse whatever
# group already sits at APP_GID instead of colliding with it.
RUN (getent group "${APP_GID}" > /dev/null || groupadd --gid "${APP_GID}" appuser) \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /usr/sbin/nologin appuser

WORKDIR /workspace/EdgeForgeStudio

COPY requirements.txt constraints.txt ./
COPY scripts/verify-packaging-toolchain.py scripts/verify-packaging-toolchain.py

RUN python -m pip install -c constraints.txt pip setuptools wheel \
    && python scripts/verify-packaging-toolchain.py \
    && python -m pip install -r requirements.txt -c constraints.txt

# After the pip-install layer so source edits don't invalidate the dependency
# cache. This is what makes the image launchable on its own: docker-compose.yml
# bind-mounts over this directory for the dev inner loop, but a direct
# `docker run` of the built image (no Compose) has nothing else providing
# `app/` -- without this, "uvicorn app.main:app" fails with
# ModuleNotFoundError before Studio ever starts.
COPY app ./app
COPY LICENSE NOTICE ./

RUN mkdir -p /workspace/data /workspace/EdgeForge /workspace/EdgeForgeKnowledgeServer

# Docker Desktop bind-mounted Engine files can be unreliable for Python imports
# on macOS. Keep a small image-local AppBuilder runtime for manifest validation
# while preserving the user-facing /workspace/EdgeForge mount.
COPY --from=edgeforge_engine appbuilder /opt/EdgeForgeRuntime/appbuilder

# Non-root. Only image-local directories need chowning here -- the bind
# mounts below (source tree, Engine/KS checkouts, generated-apps output) keep
# the HOST's ownership no matter what this image does at build time; that's
# what APP_UID/APP_GID above is for.
RUN chown -R "${APP_UID}:${APP_GID}" /workspace /opt/EdgeForgeRuntime

USER appuser

EXPOSE 8083

# No --reload: this is the image default, what anyone running the built image
# gets. A file-watcher auto-restart belongs to the compose dev inner loop
# (docker-compose.yml, which bind-mounts the source tree), not the shipped
# image.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8083"]
