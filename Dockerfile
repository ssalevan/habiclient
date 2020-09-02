FROM centos

# Adds the Habitat client repository.
ADD . /habiclient

# Installs all build dependencies.
RUN dnf groupinstall -y "Development Tools" && \
  dnf install -y dnf-plugins-core epel-release glibc-devel.i686 libasan.i686 svn wget && \
  git clone https://github.com/cc65/cc65 && \
  svn checkout https://svn.code.sf.net/p/tass64/code/trunk tass64 && \
  git clone https://bitbucket.org/PTV_Claus/cc1541.git && \
  wget https://bitbucket.org/magli143/exomizer/wiki/downloads/exomizer-3.0.2.zip && \
  mkdir -p /exomizer && unzip ../exomizer-3.0.2.zip && cd src && make && cp exomizer /usr/local/bin && \
  cd /cc65 && make clean && make all && make install PREFIX=/usr && \
  cd /tass64 && make clean && make && make install && \
  cd /cc1541 && make clean && make && make install

WORKDIR /habiclient
