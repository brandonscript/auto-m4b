# FROM phusion/baseimage:jammy-1.0.1 AS ffmpeg
#FROM phusion/baseimage:master
FROM ubuntu:22.04 AS ffmpeg

RUN apt-config dump | grep -we Recommends -e Suggests | sed s/1/0/ | tee /etc/apt/apt.conf.d/999norecommend

ENV TZ=America/Vancouver
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && apt-get install -y \
    build-essential \
    crudini \
    dnsutils \
    fdkaac \
    gcc \
    git \
    git-core \
    iputils-ping \
    libfdk-aac-dev \
    libmp3lame-dev \
    runit-systemd \
    texinfo \
    wget \
    zsh

RUN sh -c "$(wget -O- https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" --unattended

# Fix SSL CAcert issue with git
RUN apt-get install -y --reinstall ca-certificates && update-ca-certificates

#Build layer
RUN echo "---- INSTALL BUILD-DEPENDENCIES ----" && \
    buildDeps='gcc \
    g++ \
    make \
    autoconf \
    automake \
    build-essential \
    cmake \
    git-core \
    libass-dev \
    libfreetype6-dev \
    libgnutls28-dev \
    libmp3lame-dev \
    libsdl2-dev \
    libtool \
    libva-dev \
    libvdpau-dev \
    libvorbis-dev \
    libxcb1-dev \
    libxcb-shm0-dev \
    libxcb-xfixes0-dev \
    meson \
    ninja-build \
    pkg-config \
    texinfo \
    yasm \
    libfdk-aac-dev \
    zlib1g-dev' && \
    set -x && \
    apt-get update && apt-get install -y $buildDeps --no-install-recommends && \
    rm -rf /var/lib/apt/lists/* && \
    echo "---- BUILD & INSTALL MP4V2 ----" && \
    mkdir -p /tmp && \
    cd /tmp && \
    git clone https://github.com/sandreas/mp4v2 && \
    cd mp4v2 && \
    ./configure && \
    make && \
    make install && \
    make distclean && \
    echo "---- BUILD & INSTALL ffmpeg ----" && \
    mkdir -p ~/ffmpeg_sources ~/bin && \
    cd ~/ffmpeg_sources && \
    git -C fdk-aac pull 2> /dev/null || git clone --depth 1 https://github.com/mstorsjo/fdk-aac && \
    cd fdk-aac && \
    autoreconf -fiv && \
    ./configure --prefix="$HOME/ffmpeg_build" --disable-shared && \
    make && \
    make install && \
    make distclean && \
    cd ~/ffmpeg_sources && \
    wget -O ffmpeg-snapshot.tar.bz2 https://ffmpeg.org/releases/ffmpeg-snapshot.tar.bz2 && \
    tar xjvf ffmpeg-snapshot.tar.bz2 && \
    cd ffmpeg && \
    PATH="$HOME/bin:$PATH" PKG_CONFIG_PATH="$HOME/ffmpeg_build/lib/pkgconfig" ./configure \
    --prefix="$HOME/ffmpeg_build" \
    --pkg-config-flags="--static" \
    --extra-cflags="-I$HOME/ffmpeg_build/include" \
    --extra-ldflags="-L$HOME/ffmpeg_build/lib" \
    --extra-libs="-lpthread -lm" \
    --ld="g++" \
    --bindir="$HOME/bin" \
    --enable-libfdk-aac \
    --enable-nonfree && \
    PATH="$HOME/bin:$PATH" make && \
    make install && \
    hash -r && \
    make distclean && \
    mv ~/bin/* /bin/ && \
    echo "---- REMOVE ALL BUILD-DEPENDENCIES ----" && \
    apt-get purge -y --auto-remove $buildDeps && \
    ldconfig && \
    rm -r /tmp/* ~/ffmpeg_sources ~/bin

FROM ffmpeg AS m4b-tool

#ENV WORKDIR /mnt/
#ENV M4BTOOL_TMP_DIR /tmp/m4b-tool/
LABEL Description="Container to run m4b-tool as a deamon."

RUN echo "---- INSTALL M4B-TOOL DEPENDENCIES ----" && \
    apt-get update && apt-get install -y \
    fdkaac \
    php-cli \
    php-intl \
    php-json \
    php-mbstring \
    php-xml \
    libxcb-shm0-dev \
    libxcb-xfixes0-dev \
    libasound-dev \
    libsdl2-dev \
    libva-dev \
    libvdpau-dev

#Mount volumes
VOLUME /temp
VOLUME /config

#install actual m4b-tool
#RUN echo "---- INSTALL M4B-TOOL ----" && \
#    wget https://github.com/sandreas/m4b-tool/releases/download/v.0.4.2/m4b-tool.phar -O /usr/local/bin/m4b-tool && \
#    chmod +x /usr/local/bin/m4b-tool
ARG M4B_TOOL_DOWNLOAD_LINK="https://github.com/sandreas/m4b-tool/releases/latest/download/m4b-tool.tar.gz"
RUN echo "---- INSTALL M4B-TOOL ----" \
    && if [ ! -f /tmp/m4b-tool.phar ]; then \
    wget "${M4B_TOOL_DOWNLOAD_LINK}" -O /tmp/m4b-tool.tar.gz && \
    if [ ! -f /tmp/m4b-tool.phar ]; then \
    tar xzf /tmp/m4b-tool.tar.gz -C /tmp/ && rm /tmp/m4b-tool.tar.gz ;\
    fi \
    fi \
    && mv /tmp/m4b-tool.phar /usr/local/bin/m4b-tool \
    && M4B_TOOL_PRE_RELEASE_LINK=$(wget -q -O - https://github.com/sandreas/m4b-tool/releases/tag/latest | grep -o 'M4B_TOOL_DOWNLOAD_LINK=[^ ]*' | head -1 | cut -d '=' -f 2) \
    && wget "${M4B_TOOL_PRE_RELEASE_LINK}" -O /tmp/m4b-tool.tar.gz \
    && tar xzf /tmp/m4b-tool.tar.gz -C /tmp/ && rm /tmp/m4b-tool.tar.gz \
    && mv /tmp/m4b-tool.phar /usr/local/bin/m4b-tool \
    && chmod +x /usr/local/bin/m4b-tool


# Test that the pre-release version is installed
# ensure `m4b-tool --version` is 'v0.5-prerelease or later'
RUN echo "---- CHECK M4B-TOOL VERSION ----" && \
    echo "m4b-tool version: $(m4b-tool --version)" && \
    m4b-tool --version | grep -qv 'v.0.4.2'

FROM m4b-tool as python

# ENV PUID=""
# ENV PGID=""
# ENV CPU_CORES=""
# ENV SLEEP_TIME=""

RUN echo "---- ADD AUTOM4B USER/GROUP ----"
# set up user account
ARG USERNAME=autom4b
ARG PUID
ARG PGID

RUN if [ -z ${PUID} ] || [ -z ${PGID} ]; then \
    echo "PUID and PGID must be set: pass --build-arg PUID=### --build-arg PGID=## or set in docker-compose.yml > build > args"; \
    exit 1; \
    fi

# check if group exists, if not, create it
RUN getent group ${USERNAME} || groupadd -g ${PGID} ${USERNAME}
# check if user exists, if not, create it but don't prompt for input
RUN getent passwd ${USERNAME} || useradd -m -u ${PUID} -g ${PGID} -s /bin/bash ${USERNAME}

#Python deps
RUN echo "---- INSTALL PYTHON PREREQS----"
# RUN apt-get install -y --reinstall ca-certificates
# RUN add-apt-repository -y 'ppa:deadsnakes/ppa'
RUN apt-get update && apt-get install -y libssl-dev openssl build-essential
# RUN apt-get install -y ffmpeg

USER ${USERNAME}
RUN sh -c "$(wget -O- https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" --unattended
USER root

RUN echo "---- INSTALL PYTHON & PIP ----"

# verify openssl version
RUN openssl version && cd /tmp && wget https://www.python.org/ftp/python/3.12.2/Python-3.12.2.tgz && \
    tar -xvf Python-3.12.2.tgz && \
    cd Python-3.12.2 && \
    ./configure --enable-optimizations && make && make install

# add python dir to path and set as default python
ENV PATH="/usr/local/bin:$PATH"
RUN update-alternatives --install /usr/bin/python python /usr/local/bin/python3.12 1

# check we are running python3.12, and fail if not
RUN echo "---- CHECK PYTHON VERSION ----" && \
    which python || exit 1 && \
    if [ "$(python --version | cut -d ' ' -f 2 | cut -d '.' -f 1-2)" != "3.12" ]; then \
    echo "Python 3.12 is required, but you are running $(python --version | cut -d ' ' -f 2)" && \
    exit 1; \
    fi

# install pip from get-pip.py
RUN echo "---- INSTALL PIP ----" && \
    cd /tmp && \
    wget https://bootstrap.pypa.io/get-pip.py && \
    python get-pip.py && \
    rm get-pip.py

# Switch to our non-root user
# USER ${USERNAME}
# add the default pip bin install location to the PATH
ENV PATH="$PATH:/home/${USERNAME}/.local/bin"

# install deps
RUN echo "---- INSTALL PYTHON DEPENDENCIES ----"
RUN pip install --no-cache-dir --upgrade pip
RUN pip install setuptools wheel pipenv

RUN echo "---- INSTALL AUTO-M4B SVC & DEPENDENCIES ----"

# RUN mkdir -p /etc/service/bot
# ADD runscript.sh /etc/service/bot/run
# ADD auto-m4b-tool.sh /

# copy Pipfile and Pipfile.lock to /auto-m4b
RUN mkdir -p /auto-m4b
ADD Pipfile /auto-m4b/
ADD Pipfile.lock /auto-m4b/
ADD pyproject.toml /auto-m4b/

WORKDIR /auto-m4b

RUN PIPENV_VENV_IN_PROJECT=1 pipenv install --skip-lock
# ffmpeg.probe is bonkers and needs reinstalling here, so, we do it anyway
RUN pipenv run pip install ffmpeg-python --force-reinstall
RUN pipenv run python -c 'import ffmpeg; ffmpeg.probe'

COPY src /auto-m4b/src
# ADD run.sh /auto-m4b/run.sh

# RUN chmod +x /auto-m4b/run.sh
RUN chmod -R 766 /auto-m4b
RUN chown -R ${USERNAME}:${USERNAME} /auto-m4b
USER ${USERNAME}

USER root

# Install spaCy depending on os (linux, windows, or mac – and handle arm64)
# arm64: spacy[apple]
# all others: spacy

# determine platform and if arm64
RUN echo "---- INSTALL SPACY ----" && \
    if [ "$(uname -m)" == "aarch64" ]; then \
    pipenv run pip install "spacy[apple]<4"; \
    else \
    pipenv run pip install "spacy<4"; \
    fi

# Download spaCy model
RUN pipenv run python -m spacy download en_core_web_sm

# RUN pipenv run pip install ffmpeg-python --force-reinstall

# RUN mkdir -p /etc/init
# RUN echo "start on startup\ntask\nexec /auto-m4b/run.sh" > /etc/init/auto-m4b.conf

#use the remommended clean command
RUN apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Remove obnoxious cron php session cleaning
# RUN rm -f /etc/cron.d/php
# RUN systemctl stop phpsessionclean.service &> /dev/null
# RUN systemctl disable phpsessionclean.service &> /dev/null
# RUN systemctl stop phpsessionclean.timer &> /dev/null
# RUN systemctl disable phpsessionclean.timer &> /dev/null

# append `EXTRA_OPTS="-L 0"` to /etc/default/cron
# RUN echo 'EXTRA_OPTS="-L 0"' >> /etc/default/cron

# replace the line that starts with `filter f_syslog3` in /etc/syslog-ng/syslog-ng.conf with `filter f_syslog3 { not facility(cron, auth, authpriv, mail) and not filter(f_debug); };`
# RUN sed -i 's/^filter f_syslog3.*/filter f_syslog3 { not facility(cron, auth, authpriv, mail) and not filter(f_debug); };/' /etc/syslog-ng/syslog-ng.conf

# install zsh and omz and set it as default shell
RUN sed -i 's/\/bin\/bash/\/usr\/bin\/zsh/g' /etc/passwd
RUN chsh -s /usr/bin/zsh
# echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.profile && \
# echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.profile && \
# echo 'eval "$(pyenv init -)"' >> ~/.profile

# Copy my_init because built-in one is broken in later python versions

# ADD my_init_py312.py /usr/sbin/my_init

# keep our container running so we can exec into it
# ENTRYPOINT ["tail", "-f", "/dev/null"]
# add pipenv to path
# ENV PATH="/auto-m4b/.venv/bin:$PATH"

# USER ${USERNAME}
# CMD [ "PYTHONPATH=.:src", "python", "-m", "src", "-l", "-1" ]
USER ${USERNAME}
CMD [ "pipenv", "run", "docker" ]