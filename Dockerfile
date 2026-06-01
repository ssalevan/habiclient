FROM rockylinux:9

# Adds the Habitat client repository.
ADD . /habiclient

# Installs all build dependencies.
# cc65 is PINNED to commit 0fca83500.  It was previously cloned at HEAD, so a
# fresh CI image picked up a newer cc65 that emits a LARGER launcher binary,
# overrunning its $6000-$8800 budget into the title-screen data at $8800 and
# scrambling the top of the title screen on boot.  0fca83500 (cc65 V2.19) is
# the version whose launcher ends at $86C8, safely below $8800.
RUN dnf groupinstall -y "Development Tools" && \
  dnf install -y dnf-plugins-core epel-release glibc-devel glibc-devel.i686 libgcc.i686 libasan svn wget && \
  git clone https://github.com/cc65/cc65 && \
  svn checkout https://svn.code.sf.net/p/tass64/code/trunk tass64 && \
  git clone --depth 1 --branch 4.0 https://github.com/TrantorHF/cc1541.git && \
  wget https://bitbucket.org/magli143/exomizer/wiki/downloads/exomizer-3.0.2.zip && \
  mkdir -p /exomizer && unzip ../exomizer-3.0.2.zip && cd src && make && cp exomizer /usr/local/bin && \
  cd /cc65 && git checkout 0fca83500 && make clean && make all && make install PREFIX=/usr && \
  cd /tass64 && make clean && make && make install && \
  cd /cc1541 && make clean && make && make install

WORKDIR /habiclient
