#!/usr/bin/env bash
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
set -e

# ============================================
# NPM Registry Mirrors (fallback order)
# ============================================
NPM_MIRRORS=(
    "https://registry.npmjs.org"
    "https://registry.npmmirror.com"
    "https://mirrors.cloud.tencent.com/npm/"
    "https://mirrors.ustc.edu.cn/npm/"
    "https://mirrors.tuna.tsinghua.edu.cn/npm/"
)

# Function: Try npm command with mirror fallback
npm_with_fallback() {
    local cmd="$1"
    shift
    local args="$@"
    
    echo "Attempting npm ${cmd}..."
    
    for mirror in "${NPM_MIRRORS[@]}"; do
        echo "Trying npm mirror: ${mirror}"
        if npm --registry "${mirror}" --prefer-offline --no-fund --no-audit ${cmd} ${args} 2>/dev/null; then
            echo "✓ Success with mirror: ${mirror}"
            return 0
        fi
        echo "✗ Failed with mirror: ${mirror}, trying next..."
    done
    
    echo "ERROR: All npm mirrors failed!"
    return 1
}

# Function: Configure npm mirror globally
configure_npm_mirror() {
    local mirror="$1"
    npm config set registry "${mirror}"
    echo "NPM registry set to: ${mirror}"
}

# ============================================
# Puppeteer Dependencies
# ============================================
if [ "$PUPPETEER_SKIP_CHROMIUM_DOWNLOAD" = "false" ]; then
    echo "Installing Chromium dependencies for Puppeteer..."
    apt update -qq
    apt install -y -qq --no-install-recommends chromium
fi

# ============================================
# Superset Frontend Build
# ============================================
if [ "$BUILD_SUPERSET_FRONTEND_IN_DOCKER" = "true" ]; then
    echo "Building Superset frontend in dev mode inside docker container"
    cd /app/superset-frontend

    # Optional: Use environment variable to force specific npm mirror
    if [ -n "$NPM_REGISTRY" ]; then
        echo "Using forced NPM registry: $NPM_REGISTRY"
        configure_npm_mirror "$NPM_REGISTRY"
    fi

    if [ "$NPM_RUN_PRUNE" = "true" ]; then
        echo "Running \"npm run prune\""
        npm_with_fallback "run" "prune"
    fi

    echo "Running \"npm install\""
    npm_with_fallback "install" ""

    echo "Start webpack dev server"
    # Start the webpack dev server, serving dynamically at http://localhost:9000
    # It proxies to the backend served at http://localhost:8088
    npm run dev-server

else
    echo "Skipping frontend build steps - YOU NEED TO RUN IT MANUALLY ON THE HOST!"
    echo "https://superset.apache.org/docs/contributing/development/#webpack-dev-server"
fi
