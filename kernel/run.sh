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

# 读取SD类型和设备类型
sd_type=$(cat /sys/block/mmcblk0/device/type)
dev_type=$(cat /proc/cmdline | awk -F'dev_type=' '{split($2,a," "); print a[1]}')

if [ "$sd_type" = "SD" ] && [ "$dev_type" = "SDNAND" ]; then
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] 验证通过 - SD类型: $sd_type, 设备类型: $dev_type" >> $LOG_FILE
    if [ -f $WORK_DIR/local_ota_update.sh ]; then
        echo "update local_ota_update.sh kernel sd"
        $WORK_DIR/local_ota_update.sh $WORK_DIR/ota_kernel_sd/
    fi
else
    if [ -f $WORK_DIR/local_ota_update.sh ]; then
    	echo "update local_ota_update.sh kernel emmc"
    	$WORK_DIR/local_ota_update.sh $WORK_DIR/ota_kernel_emmc/
    fi
fi

if [ -f $WORK_DIR/module.tar ]; then
    echo "tar module.tar"
    tar -xvf $WORK_DIR/module.tar -C /usr/prog/
    sync  
fi

cd /usr/prog/PROGRAM/kernel/
DIR_COUNT=`find -maxdepth 1 -type d | wc -l`
echo $DIR_COUNT
if [ ${DIR_COUNT} -gt 2 ];then
        KERNEL_VERSION=`ls -d [0-9]* | sort -V | head -n 1`
        echo "rm " $KERNEL_VERSION
        rm -r /usr/prog/PROGRAM/kernel/$KERNEL_VERSION
fi


sync

exit 0
