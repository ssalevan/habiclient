FROM centos

ADD . /macross

RUN yum groupinstall -y "Development Tools" && yum install -y glibc-devel.i686

RUN git clone https://github.com/cc65/cc65 && cd cc65

WORKDIR /cc65

RUN make clean && make all && make install PREFIX=/usr

WORKDIR /macross

RUN make clean && make macross && mv ./macross /usr/bin

WORKDIR /macross/slinky

RUN make clean && make slinky && mv ./slinky /usr/bin
