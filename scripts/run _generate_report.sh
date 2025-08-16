  echo "md=${OUT_MD}" >> "$GITHUB_OUTPUT"
  shell: /usr/bin/bash --noprofile --norc -e -o pipefail {0}
  env:
    pythonLocation: /opt/hostedtoolcache/Python/3.11.13/x64
    PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.11.13/x64/lib/pkgconfig
    Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.13/x64
    Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.13/x64
    Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.11.13/x64
    LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.11.13/x64/lib
    M365_PFX_PASSWORD: ***
    TITLE: roadmap_report
    SINCE: 
    MONTHS: 
    CLOUD_GENERAL: true
    CLOUD_GCC: false
    CLOUD_GCCH: false
    CLOUD_DOD: false
    PRODUCTS: 
    PUBLIC_IDS: 
/home/runner/work/_temp/6a9a236d-c4e6-4245-b8c2-33965e2caed0.sh: line 27: unexpected EOF while looking for matching `"'
Error: Process completed with exit code 2.