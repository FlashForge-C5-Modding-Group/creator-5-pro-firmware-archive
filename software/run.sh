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

rm /usr/prog/qt-4.8.6 -rf
rm /usr/prog/nim -rf
rm /usr/prog/opencv-4.10 -rf
rm /usr/prog/wifi/8821cu.ko*
sync

rm /usr/prog/klipper/klippy/kinematics/__pycache__/*
rm /usr/prog/klipper/klippy/__pycache__/*
rm /usr/prog/klipper/klippy/chelper/__pycache__/*
rm /usr/prog/klipper/klippy/extras/__pycache__/*
sync

cp $WORK_DIR/klipper/klipper_pri.sh  /usr/prog/klipper/klipper_pri.sh
sync

cp $WORK_DIR/klipper/start.sh  /usr/prog/klipper/start.sh
sync

cp $WORK_DIR/klipper/config/* /usr/data/config/ -rf
sync

cp $WORK_DIR/8821cu.ko  /usr/prog/modules/8821cu.ko
sync

cp $WORK_DIR/bin/* /usr/prog/bin/
sync

cp $WORK_DIR/auth/*  /usr/prog/etc/
sync

cp -f $WORK_DIR/app_startup.sh /usr/prog/
sync

if [ -f $WORK_DIR/klipper/klippy.zip  ]; then
	echo "unzip klippy.zip..."
	unzip -o $WORK_DIR/klipper/klippy.zip -d /usr/prog/klipper/
	sleep 1
	sync
fi

if [ -f $WORK_DIR/zip/img.zip  ]; then
	unzip -o $WORK_DIR/zip/img.zip -d /usr/data/firmwareRes/
	sleep 1
	sync
fi

# unzip firmwareExe
unzip -o $WORK_DIR/firmwareExe.zip -d /usr/prog/PROGRAM/software/firmwareExe
sleep 1
sync

# update camera firmware
# 遍历 /dev/video* 设备，查找 name 为 "Integrated Camera: Integrated C" 的摄像头设备
# 找到后输出 videoX 中的编号 X 并退出
CAMERA_INDEX=0
CAMERA_NAME="Integrated Camera: Integrated C"
FIND_CAMERA=0
for device in /dev/video*; do
    # 提取设备编号 X（如 /dev/video0 -> 0）
    CAMERA_INDEX="${device##*video}"
    # 读取设备名称
    CAMERA_NAME_FILE="/sys/class/video4linux/video${CAMERA_INDEX}/name"
    if [ -f "$CAMERA_NAME_FILE" ]; then
        ACTUAL_NAME=$(cat "$CAMERA_NAME_FILE")
        if [ "$ACTUAL_NAME" = "$CAMERA_NAME" ]; then
            FIND_CAMERA=1
            break
        fi
    fi
done
echo "camera is found flag: ${FIND_CAMERA}; index: ${CAMERA_INDEX}"
if [ ${FIND_CAMERA} != 1 ]; then
    echo "camera is flag != 1"
    CAMERA_INDEX=0
fi
echo "camera actuall index is: ${CAMERA_INDEX}"
$WORK_DIR/camera/V4L2_FWUpdate_mips -D ${CAMERA_INDEX} -d $WORK_DIR/camera/x1226.bin -V 1226

# 删除更新过后的文件，释放空间
rm $WORK_DIR/8821cu.ko
rm $WORK_DIR/zip/img.zip
sync

sleep 1

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

sleep 3

exit 0
