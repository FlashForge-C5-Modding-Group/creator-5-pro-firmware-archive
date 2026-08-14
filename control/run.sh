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

UPDATE_LOG_DIR=/usr/data/logs

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
        	for i in 1 2 3
			do
                echo "burn eBoard M3 firmware..."
                rm $UPDATE_LOG_DIR/UPDATA_FIRMWARE_EBOARD_M3.log
                $WORK_DIR/IAPCommand $WORK_DIR/$MCU_EBOARD_M3 /dev/ttyS5 >> $UPDATE_LOG_DIR/UPDATA_FIRMWARE_EBOARD_M3.log
                sync
                
				if [ -f $UPDATE_LOG_DIR/UPDATA_FIRMWARE_EBOARD_M3.log ];then
					if grep -q "error\|fail" $UPDATE_LOG_DIR/UPDATA_FIRMWARE_EBOARD_M3.log ; then
						echo "burn eBoard M3 include error | fail..."
					else
						echo "burn eBoard M3 completed..."
						break
					fi
				fi
            done
        fi
		
		if [ -f $WORK_DIR/$MCU_HEATERBOARD_M3 ];then
			for i in 1 2 3
			do
                echo "burn heaterBoard M3 firmware..."
                rm $UPDATE_LOG_DIR/UPDATA_FIRMWARE_HEATERBOARD_M3.log
                $WORK_DIR/IAPCommand $WORK_DIR/$MCU_HEATERBOARD_M3 /dev/ttyS4 >> $UPDATE_LOG_DIR/UPDATA_FIRMWARE_HEATERBOARD_M3.log
                sync
				
				if [ -f $UPDATE_LOG_DIR/UPDATA_FIRMWARE_HEATERBOARD_M3.log ];then
					if grep -q "error\|fail" $UPDATE_LOG_DIR/UPDATA_FIRMWARE_HEATERBOARD_M3.log ; then
						echo "burn heaterBoard M3 include error | fail..."
					else
						echo "burn heaterBoard M3 completed..."
						break
					fi
				fi
			done
        fi
        
        if [ -f $WORK_DIR/$MCU_LEVELBOARD_M3 ];then
			for i in 1 2 3
			do
                echo "burn levelBoard M3 firmware..."
                rm $UPDATE_LOG_DIR/UPDATA_FIRMWARE_LEVELBOARD_M3.log
                $WORK_DIR/IAPCommand $WORK_DIR/$MCU_LEVELBOARD_M3 /dev/ttyS7 >> $UPDATE_LOG_DIR/UPDATA_FIRMWARE_LEVELBOARD_M3.log
                sync
				
				if [ -f $UPDATE_LOG_DIR/UPDATA_FIRMWARE_LEVELBOARD_M3.log ];then
					if grep -q "error\|fail" $UPDATE_LOG_DIR/UPDATA_FIRMWARE_LEVELBOARD_M3.log ; then
						echo "burn levelBoard M3 include error | fail..."
					else
						echo "burn levelBoard M3 completed..."
						break
					fi
				fi
			done
        fi
fi

if [ -f $WORK_DIR/ISPCommand ];then
        chmod a+x $WORK_DIR/ISPCommand
        if [ -f $WORK_DIR/$MCU_GD_M3 ];then
			for i in 1 2 3
			do
                echo "burn GD M3 firmware..."
                rm $UPDATE_LOG_DIR/UPDATA_MCU_GD_M3.log
                $WORK_DIR/ISPCommand  $WORK_DIR/$MCU_GD_M3  >> $UPDATE_LOG_DIR/UPDATA_MCU_GD_M3.log
				
				if [ -f $UPDATE_LOG_DIR/UPDATA_MCU_GD_M3.log ];then
					if grep -q "error\|fail" $UPDATE_LOG_DIR/UPDATA_MCU_GD_M3.log ; then
						echo "burn GD M3 include error | fail..."
					else
						echo "burn GD M3 completed..."
						break
					fi
				fi
			done
        fi
fi

cd /usr/prog/PROGRAM/control/
DIR_COUNT=`find -maxdepth 1 -type d | wc -l`
echo $DIR_COUNT
if [ ${DIR_COUNT} -gt 2 ];then
	CONTROL_VERSION=`ls -d [0-9]* | sort -V | head -n 1`
	echo "rm " $CONTROL_VERSION
        rm -r /usr/prog/PROGRAM/control/$CONTROL_VERSION
fi

exit 0


