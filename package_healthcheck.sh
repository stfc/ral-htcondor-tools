#!/bin/bash

if [[ $# -ne 1 ]]; then
    echo "Usage: package.sh VERSION"
    exit 1
fi

fpm \
    --input-type dir \
    --output-type rpm \
    --name tier1-condor-wn-healthcheck \
    --version $1 \
    --iteration 1 \
    --architecture noarch \
    --prefix '/usr/local/bin/' \
    --vendor 'Science and Technology Facilties Council' \
    --url 'https://github.com/stfc/ral-htcondor-tools' \
    --description 'Scripts and stuff used on workernodes with HTCondor at RAL' \
    healthcheck_wn_condor \
    check_cvmfs2.sh
