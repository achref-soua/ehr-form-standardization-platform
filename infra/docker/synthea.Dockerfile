# syntax=docker/dockerfile:1.12
FROM eclipse-temurin:25-jre-jammy@sha256:10c251954d0bfe1a59ba93505f8c628d755919412400aa98685764c9353605d6

ARG SYNTHEA_JAR_URL=https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar
ADD --checksum=sha256:ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1 \
    ${SYNTHEA_JAR_URL} /opt/synthea/synthea.jar

RUN groupadd --system --gid 10003 synthea \
    && useradd --system --uid 10003 --gid synthea --home-dir /work synthea \
    && mkdir -p /output /work \
    && chmod 0444 /opt/synthea/synthea.jar \
    && chown -R synthea:synthea /output /work

USER synthea
WORKDIR /work
ENTRYPOINT ["java", "-jar", "/opt/synthea/synthea.jar"]
