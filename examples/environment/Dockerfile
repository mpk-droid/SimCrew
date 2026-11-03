# Example custom agent environment.
# Extend the published SimCrew base image with extra OS packages or tools.
FROM ghcr.io/mpk-droid/simcrew:latest

USER 0
RUN dnf install -y --nodocs golang && dnf clean all
USER 1001
