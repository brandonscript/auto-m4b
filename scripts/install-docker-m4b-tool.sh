#!/bin/bash
# Use the system docker command, not the Poetry entry point
# Find docker by checking common system locations first
DOCKER_CMD=""
for path in /opt/homebrew/bin/docker /usr/local/bin/docker /usr/bin/docker; do
    if [ -x "$path" ]; then
        DOCKER_CMD="$path"
        break
    fi
done

# Fallback to command -v, but skip if it's a Python script (Poetry entry point)
if [ -z "$DOCKER_CMD" ]; then
    candidate=$(command -v docker 2>/dev/null)
    if [ -n "$candidate" ]; then
        # Check if it's NOT a Python script
        if ! head -1 "$candidate" 2>/dev/null | grep -qE "^#!.*python|^from src"; then
            DOCKER_CMD="$candidate"
        fi
    fi
fi

if [ -z "$DOCKER_CMD" ]; then
    echo "Error: docker command not found"
    exit 1
fi

# pull the image if it is not available
if [ ! "$($DOCKER_CMD images -q sandreas/m4b-tool:latest 2>/dev/null)" ]; then
    $DOCKER_CMD pull sandreas/m4b-tool:latest
fi

git_root=$(git rev-parse --show-toplevel)

# change to the root of the git repository
cd $git_root
echo -e "Pulling the latest changes from the m4b-tool repository into $git_root/m4b-tool...\n"

# if m4b-tool dir does not exist, then clone the repository
if [ ! -d "m4b-tool" ]; then
    git clone https://github.com/sandreas/m4b-tool.git
    cd m4b-tool
else # if it does exist, then pull the latest changes
    cd m4b-tool
    # Stash local changes before pulling
    if [ -n "$(git status --porcelain)" ]; then
        echo "Stashing local changes in m4b-tool repository..."
        git stash
    fi
    git pull
fi

# Fix wildcard syntax issue in Dockerfile if present
# The buildx builder doesn't support wildcards in ADD commands
if grep -qE 'ADD\s+\./Dockerfile\s+\./dist/m4b-tool\.phar\*\s+/tmp/' Dockerfile; then
    echo -e "\nFixing wildcard syntax in Dockerfile (buildx builder doesn't support it)..."
    # Replace the problematic line with the fixed version
    sed -i.bak 's|ADD ./Dockerfile ./dist/m4b-tool.phar\* /tmp/|ADD ./Dockerfile /tmp/|' Dockerfile
    rm -f Dockerfile.bak
    echo "Fixed: Changed 'ADD ./Dockerfile ./dist/m4b-tool.phar* /tmp/' to 'ADD ./Dockerfile /tmp/'"
    echo "Note: If you need a custom .phar file, you'll need to add it explicitly with a separate ADD command."
fi

# build docker image - this will take a while
$DOCKER_CMD build . -t m4b-tool

# use the specific pre-release from 2022-07-16
$DOCKER_CMD build . --build-arg M4B_TOOL_DOWNLOAD_LINK=https://github.com/sandreas/m4b-tool/files/10728378/m4b-tool.tar.gz -t m4b-tool

cd ..

echo -e "\nSuggest adding the following to your .bashrc or .zshrc file:"
echo -e "alias m4b-tool='$DOCKER_CMD run --rm -u $(id -u):$(id -g) -v \"$(pwd)\":/mnt m4b-tool:latest'"

echo -e "\nThen test:\nm4b-tool --version"
