#!/bin/bash

if [[ $# -ne 1 ]]; then
    echo "Usage: package.sh VERSION"
    exit 1
fi

fpm \
    --input-type dir \
    --output-type rpm \
    --name tier1-condor-docker \
    --version $1 \
    --iteration 1 \
    --architecture noarch \
    --prefix '/usr/local/bin/' \
    --vendor 'Science and Technology Facilties Council' \
    --url 'https://github.com/stfc/ral-htcondor-tools' \
    --description 'Scripts and stuff used on worker nodes with HTCondor at RAL' \
    --depends 'python3' \
    docker.py
