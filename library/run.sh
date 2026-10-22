#!/bin/sh

# Author:		chenhe
# Description:	单个固件包升级程序
# Date:			2022-01-21

set -x

WORK_DIR=`dirname $0`
GCODE_DIR="/usr/data/gcodes"

#检测机器的架构,错误马上退出
CHECH_ARCH=`uname -m`
if [ "${CHECH_ARCH}" != "mips" ];then
    echo "Machine architecture error."
    echo ${CHECH_ARCH}
    exit 1
fi

#检测内核版本，错误马上退出
#CHECH_KERNEL=`uname -r`
#if [ "${CHECH_KERNEL}" != "5.6.0-svn539" ];then
#    echo "Kernel version error."
#    echo ${CHECH_KERNEL}
#    exit 1
#fi

# cp -vf /tmp/test /data/
# $1  源文件路径名 /tmp/test
# $2  目标路径名   /data/
cp_file()
{
	SRCFILE="$1"
	DSTFILE="$2`basename $1`"
	if [ ! -f $DSTFILE ];then
		cp -vf ${SRCFILE} $2
		chmod a+x $DSTFILE
	fi
	SRCFILEMD5=`md5sum $SRCFILE | cut -d ' ' -f 1`
	DSTFILEMD5=`md5sum $DSTFILE | cut -d ' ' -f 1`
	while [ "$SRCFILEMD5" != "$DSTFILEMD5" ];
	do
		rm -rf ${DSTFILE}
		cp -vf ${SRCFILE} $2
		chmod a+x $DSTFILE
		sync
		DSTFILEMD5=`md5sum $DSTFILE | cut -d ' ' -f 1`
	done
	#echo ${SRCFILEMD5}
	#echo ${DSTFILEMD5}
}

# free 28M
rm /usr/prog/qt-4.8.6 -rf
# free 22M
rm /usr/prog/opencv-4.10 -rf
# free 3M
rm /usr/prog/wifi/8821cu.ko*
sync

if [ -f $WORK_DIR/zip/font.zip  ]; then
	unzip -o $WORK_DIR/zip/font.zip -d /usr/data/firmwareRes/
	sync
	chmod 777 /usr/data/firmwareRes/font/*
	sync
	sleep 1
fi

if [ -f $WORK_DIR/zip/ffmpeg-402.zip  ]; then
	echo "unzip ffmpeg-4.0.2..."
	unzip -o $WORK_DIR/zip/ffmpeg-402.zip -d /usr/prog/
	sleep 1
	sync
fi

# copy reset factory model
if [ -f "$GCODE_DIR/Doberman‌_PLA_3h26m.gcode" ]; then
        rm "$GCODE_DIR/Doberman‌_PLA_3h26m.gcode"
	sync
fi

if [ -f $GCODE_DIR/3DBenchy_PLA_40m32s.gcode ] || [ -f $GCODE_DIR/3DBenchy_PLA_50m28s.gcode ] || [ -f $GCODE_DIR/3DBenchy_PLA_49m52s.gcode.3mf ]; then
        rm $GCODE_DIR/3DBenchy_PLA_40m32s.gcode
        rm $GCODE_DIR/3DBenchy_PLA_50m28s.gcode
        rm $GCODE_DIR/3DBenchy_PLA_49m52s.gcode.3mf
	sync
	cp $WORK_DIR/model/C5P_3DBenchy_PLA_53m29s.gcode.3mf $GCODE_DIR/
	sync
fi

if [ -f $GCODE_DIR/Logo_PLA_10m43s.gcode ] || [ -f $GCODE_DIR/Logo_PLA_17m6s.gcode.3mf ]; then
        rm $GCODE_DIR/Logo_PLA_10m43s.gcode
        rm $GCODE_DIR/Logo_PLA_17m6s.gcode.3mf
	sync
	cp $WORK_DIR/model/C5P_logo-06_PLA_17m45s.gcode.3mf $GCODE_DIR/
	sync
fi

sync

# 删除更新过后的文件，释放空间
rm $WORK_DIR/zip/*.zip
sync

cd /usr/prog/PROGRAM/library/
DIR_COUNT=`find -maxdepth 1 -type d | wc -l`
echo $DIR_COUNT
if [ ${DIR_COUNT} -gt 2 ];then
        CONTROL_VERSION=`ls -d [0-9]* | sort -V | head -n 1`
        echo "rm " $CONTROL_VERSION
        rm -r /usr/prog/PROGRAM/library/$CONTROL_VERSION
fi

sync
sleep 3

exit 0
