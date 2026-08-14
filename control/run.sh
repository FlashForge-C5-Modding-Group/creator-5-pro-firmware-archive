#!/bin/sh
# Author:		chenhe
# Date:			2022-01-21

set -x

WORK_DIR=`dirname $0`

MCU_LEVELBOARD_M3=levelBoard.hex
MCU_EBOARD_M3=eBoard.hex
MCU_HEATERBOARD_M3=heaterBoard.hex
MCU_NBOARD_M3=nBoard.bin
MCU_GD_M3=mainBoardGD.hex

CHECH_ARCH=`uname -m`
if [ "${CHECH_ARCH}" != "mips" ];then
    echo "Machine architecture error."
    echo ${CHECH_ARCH}
    exit 1
fi

cat $WORK_DIR/mcu.img > /dev/fb0


if [ -f $WORK_DIR/IAPCommand ];then
        chmod a+x $WORK_DIR/IAPCommand
        if [ -f $WORK_DIR/$MCU_EBOARD_M3 ];then
                echo "burn eBoard M3 firmware..."
                $WORK_DIR/IAPCommand $WORK_DIR/$MCU_EBOARD_M3 /dev/ttyS5
                sync
        fi
		
	if [ -f $WORK_DIR/$MCU_HEATERBOARD_M3 ];then
                echo "burn heaterBoard M3 firmware..."
                $WORK_DIR/IAPCommand $WORK_DIR/$MCU_HEATERBOARD_M3 /dev/ttyS4
                sync
        fi
        
        if [ -f $WORK_DIR/$MCU_LEVELBOARD_M3 ];then
                echo "burn levelBoard M3 firmware..."
                $WORK_DIR/IAPCommand $WORK_DIR/$MCU_LEVELBOARD_M3 /dev/ttyS7
                sync
        fi
fi

if [ -f $WORK_DIR/ISPCommand ];then
        chmod a+x $WORK_DIR/ISPCommand
        if [ -f $WORK_DIR/$MCU_GD_M3 ];then
                echo "burn GD M3 firmware..."
                $WORK_DIR/ISPCommand  $WORK_DIR/$MCU_GD_M3
        fi
fi

#if [ -f $WORK_DIR/NationsCommand ];then
#        chmod a+x $WORK_DIR/NationsCommand
#        if [ -f $WORK_DIR/$MCU_NBOARD_M3 ];then
#                echo "burn nBoard firmware..."
#                $WORK_DIR/NationsCommand -c -d --fn $WORK_DIR/$MCU_NBOARD_M3 --v -r
#        fi
#fi


cd /usr/prog/PROGRAM/control/
DIR_COUNT=`find -maxdepth 1 -type d | wc -l`
echo $DIR_COUNT
if [ ${DIR_COUNT} -gt 2 ];then
	CONTROL_VERSION=`ls -d [0-9]* | sort -V | head -n 1`
	echo "rm " $CONTROL_VERSION
        rm -r /usr/prog/PROGRAM/control/$CONTROL_VERSION
fi
exit 0
