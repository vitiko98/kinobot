#! /bin/bash

TIME=$(date -u +"%Y.%m.%d.%H.%M")
BACKUP=$HOME/.kino_backup

mkdir -p $BACKUP

cp -fv $REQUESTS_JSON "${BACKUP}/${REQUESTS_JSON##*/}.${TIME}"
cp -fv $KINOBASE "${BACKUP}/${KINOBASE##*/}.${TIME}"
cp -fv $REQUESTS_DB "${BACKUP}/${REQUESTS_DB##*/}.${TIME}"
cp -fv $OFFENSIVE_JSON "${BACKUP}/${OFFENSIVE_JSON##*/}.${TIME}"
