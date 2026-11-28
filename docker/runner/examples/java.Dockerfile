# A runner with a Java toolchain: the platform image plus the customer's layer. Build from anywhere:
#   docker build -f java.Dockerfile -t my-registry/octryx-runner-java:1 .
# and run it in place of octryx-runner (compose: `image:` of the runner service; Helm: runner.image).
ARG RUNNER_IMAGE=octryx-runner:local
FROM ${RUNNER_IMAGE}

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends default-jdk-headless maven \
 && rm -rf /var/lib/apt/lists/*
# Everything stays read-only for the agent's account; tool caches go to its home (/tmp/agent-home, a tmpfs).
ENV JAVA_HOME=/usr/lib/jvm/default-java \
    MAVEN_OPTS=-Dmaven.repo.local=/tmp/agent-home/.m2
