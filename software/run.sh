#!/bin/sh

# Author:		chenhe
# Description:	单个固件包升级程序
# Date:			2022-01-21

set -x

WORK_DIR=`dirname $0`

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

# cp -vf /tmp/test /usr/data/
# $1  源文件路径名 /tmp/test
# $2  目标路径名   /usr/data/
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

if [ -f $WORK_DIR/app_startup.sh  ]; then
        cp -f $WORK_DIR/app_startup.sh /usr/prog/
fi

if [ -f $WORK_DIR/sys_start.sh  ]; then
        cp -f $WORK_DIR/sys_start.sh /usr/prog/bin/
        cp -f $WORK_DIR/freecach.sh /usr/prog/bin/
fi
sync

rm /usr/prog/klipper/klippy/kinematics/__pycache__/*
rm /usr/prog/klipper/klippy/__pycache__/*
rm /usr/prog/klipper/klippy/chelper/__pycache__/*
rm /usr/prog/klipper/klippy/extras/__pycache__/*
sync

cp $WORK_DIR/klipper_pri.sh  /usr/prog/klipper/klipper_pri.sh
sync

cp $WORK_DIR/start.sh  /usr/prog/klipper/start.sh
sync

cp $WORK_DIR/firmwareExe /usr/prog/PROGRAM/software/
sync

cp $WORK_DIR/unTar /usr/prog/bin/unTar
sync

cp $WORK_DIR/wakeup_level /usr/prog/bin/wakeup_level
sync

cp $WORK_DIR/klipper/klippy/*  /usr/prog/klipper/klippy/ -rf
sync

cp $WORK_DIR/klipper/kinematics/*  /usr/prog/klipper/klippy/kinematics/ -rf
sync

cp $WORK_DIR/klipper/extras/*  /usr/prog/klipper/klippy/extras/ -rf
sync

tar -xvf $WORK_DIR/klipper/chelper.tar -C /usr/prog/klipper/klippy/
sync

cp $WORK_DIR/klipper/config/* /usr/data/config/ -rf
sync

cp $WORK_DIR/8821cu.ko  /usr/prog/modules/8821cu.ko
sync

cp $WORK_DIR/passwd  /usr/prog/etc/passwd
sync

cp $WORK_DIR/shadow  /usr/prog/etc/shadow
sync

cd /usr/prog/PROGRAM/software
DIR_COUNT=`find -maxdepth 1 -type d | wc -l`
if [ ${DIR_COUNT} -gt 2 ];then
        VERSION=`ls -d [0-9]* | sort -V | head -n 1`
        echo "rm " $VERSION
        rm -r /usr/prog/PROGRAM/software/$VERSION
fi

rm /usr/data/logs/firmwareExe.core
sync

rm /usr/data/logs/printer*.log*
sync

exit 0
