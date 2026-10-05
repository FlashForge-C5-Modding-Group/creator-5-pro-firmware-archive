#!/bin/sh
# Author:		chenhe
# Date:			2022-01-21

set -x

WORK_DIR=`dirname "$0"`

MCU_LEVELBOARD_M3=levelBoard.hex
MCU_EBOARD_M3=eBoard.hex
MCU_HEATERBOARD_M3=heaterBoard.hex
MCU_NBOARD_M3=nBoard.bin
MCU_GD_M3=mainBoardGD.hex

UPDATE_LOG_DIR=/usr/data/logs

EBOARD_M3_FINISHED=0
HEATERBOARD_M3_FINISHED=0
LEVELBOARD_M3_FINISHED=0
GD_M3_FINISHED=0

CHECH_ARCH=`uname -m`
if [ "${CHECH_ARCH}" != "mips" ];then
    echo "Machine architecture error."
    echo ${CHECH_ARCH}
    exit 1
fi

cat "$WORK_DIR/mcu.img" > /dev/fb0

# free 28M
rm /usr/prog/qt-4.8.6 -rf
# free 22M
rm /usr/prog/opencv-4.10 -rf
# free 3M
rm /usr/prog/wifi/8821cu.ko*
sync

mkdir -p "$UPDATE_LOG_DIR"

if [ -f "$WORK_DIR/IAPCommand" ];then
        chmod a+x "$WORK_DIR/IAPCommand"
        if [ -f "$WORK_DIR/$MCU_EBOARD_M3" ];then
        	for i in 1 2 3
			do
	                echo "burn eBoard M3 firmware..."
	                rm -f "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_EBOARD_M3.log"
	                "$WORK_DIR/IAPCommand" "$WORK_DIR/$MCU_EBOARD_M3" /dev/ttyS5 >> "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_EBOARD_M3.log" 2>&1
	                sync
	                
					if [ -f "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_EBOARD_M3.log" ];then
						if grep -q "finished" "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_EBOARD_M3.log" ; then
							echo "burn eBoard M3 completed..."
							EBOARD_M3_FINISHED=1
							break
						else
							echo "burn eBoard M3 not finished..."
						fi
					fi
            done
        fi
			
		if [ -f "$WORK_DIR/$MCU_HEATERBOARD_M3" ];then
			for i in 1 2 3
			do
	                echo "burn heaterBoard M3 firmware..."
	                rm -f "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_HEATERBOARD_M3.log"
	                "$WORK_DIR/IAPCommand" "$WORK_DIR/$MCU_HEATERBOARD_M3" /dev/ttyS4 >> "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_HEATERBOARD_M3.log" 2>&1
	                sync
				
				if [ -f "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_HEATERBOARD_M3.log" ];then
					if grep -q "finished" "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_HEATERBOARD_M3.log" ; then
						echo "burn heaterBoard M3 completed..."
						HEATERBOARD_M3_FINISHED=1
						break
					else
						echo "burn heaterBoard M3 not finished..."
					fi
				fi
			done
        fi
        
        if [ -f "$WORK_DIR/$MCU_LEVELBOARD_M3" ];then
			for i in 1 2 3
			do
	                echo "burn levelBoard M3 firmware..."
	                rm -f "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_LEVELBOARD_M3.log"
	                "$WORK_DIR/IAPCommand" "$WORK_DIR/$MCU_LEVELBOARD_M3" /dev/ttyS7 >> "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_LEVELBOARD_M3.log" 2>&1
	                sync
				
				if [ -f "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_LEVELBOARD_M3.log" ];then
					if grep -q "finished" "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_LEVELBOARD_M3.log" ; then
						echo "burn levelBoard M3 completed..."
						LEVELBOARD_M3_FINISHED=1
						break
					else
						echo "burn levelBoard M3 not finished..."
					fi
				fi
			done
        fi
fi

if [ -f "$WORK_DIR/ISPCommand" ];then
        chmod a+x "$WORK_DIR/ISPCommand"
        if [ -f "$WORK_DIR/$MCU_GD_M3" ];then
			for i in 1 2 3
			do
	                echo "burn GD M3 firmware..."
	                rm -f "$UPDATE_LOG_DIR/UPDATA_MCU_GD_M3.log"
	                "$WORK_DIR/ISPCommand" "$WORK_DIR/$MCU_GD_M3" >> "$UPDATE_LOG_DIR/UPDATA_MCU_GD_M3.log" 2>&1
	                sync
				
				if [ -f "$UPDATE_LOG_DIR/UPDATA_MCU_GD_M3.log" ];then
					if grep -q "finished" "$UPDATE_LOG_DIR/UPDATA_MCU_GD_M3.log" ; then
						echo "burn GD M3 completed..."
						GD_M3_FINISHED=1
						break
					else
						echo "burn GD M3 not finished..."
					fi
				fi
			done
        fi
fi

# check update result
if [ "$EBOARD_M3_FINISHED" -eq 1 ] && \
   [ "$HEATERBOARD_M3_FINISHED" -eq 1 ] && \
   [ "$LEVELBOARD_M3_FINISHED" -eq 1 ] && \
   [ "$GD_M3_FINISHED" -eq 1 ];then
	echo "result: all MCU update finished, remove Update..."
	rm -f "$WORK_DIR/Update"
	sync
else
	if [ "$EBOARD_M3_FINISHED" -ne 1 ];then
		echo "result: eBoard failed..."
		rm -f "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_EBOARD_M3_FAIL.log"
		if [ -f "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_EBOARD_M3.log" ];then
			mv "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_EBOARD_M3.log" \
			   "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_EBOARD_M3_FAIL.log"
		fi
		rm -f "$UPDATE_LOG_DIR/control_run_fail.log"
		if [ -f "$UPDATE_LOG_DIR/control_run.log" ];then
			mv "$UPDATE_LOG_DIR/control_run.log" \
			   "$UPDATE_LOG_DIR/control_run_fail.log"
		fi
		sync
		cat "$WORK_DIR/eBoard_fail.img" > /dev/fb0
		sleep 10000
		exit 1
	fi

	if [ "$HEATERBOARD_M3_FINISHED" -ne 1 ];then
		echo "result: heaterBoard failed..."
		rm -f "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_HEATERBOARD_M3_FAIL.log"
		if [ -f "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_HEATERBOARD_M3.log" ];then
			mv "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_HEATERBOARD_M3.log" \
			   "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_HEATERBOARD_M3_FAIL.log"
		fi
		rm -f "$UPDATE_LOG_DIR/control_run_fail.log"
		if [ -f "$UPDATE_LOG_DIR/control_run.log" ];then
			mv "$UPDATE_LOG_DIR/control_run.log" \
			   "$UPDATE_LOG_DIR/control_run_fail.log"
		fi
		sync
		cat "$WORK_DIR/heaterBoard_fail.img" > /dev/fb0
		sleep 10000
		exit 1
	fi

	if [ "$LEVELBOARD_M3_FINISHED" -ne 1 ];then
		echo "result: levelBoard failed..."
		rm -f "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_LEVELBOARD_M3_FAIL.log"
		if [ -f "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_LEVELBOARD_M3.log" ];then
			mv "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_LEVELBOARD_M3.log" \
			   "$UPDATE_LOG_DIR/UPDATA_FIRMWARE_LEVELBOARD_M3_FAIL.log"
		fi
		rm -f "$UPDATE_LOG_DIR/control_run_fail.log"
		if [ -f "$UPDATE_LOG_DIR/control_run.log" ];then
			mv "$UPDATE_LOG_DIR/control_run.log" \
			   "$UPDATE_LOG_DIR/control_run_fail.log"
		fi
		sync
		cat "$WORK_DIR/levelBoard_fail.img" > /dev/fb0
		sleep 10000
		exit 1
	fi

	if [ "$GD_M3_FINISHED" -ne 1 ];then
		echo "result: mainMcu failed..."
		rm -f "$UPDATE_LOG_DIR/UPDATA_MCU_GD_M3_FAIL.log"
		if [ -f "$UPDATE_LOG_DIR/UPDATA_MCU_GD_M3.log" ];then
			mv "$UPDATE_LOG_DIR/UPDATA_MCU_GD_M3.log" \
			   "$UPDATE_LOG_DIR/UPDATA_MCU_GD_M3_FAIL.log"
		fi
		rm -f "$UPDATE_LOG_DIR/control_run_fail.log"
		if [ -f "$UPDATE_LOG_DIR/control_run.log" ];then
			mv "$UPDATE_LOG_DIR/control_run.log" \
			   "$UPDATE_LOG_DIR/control_run_fail.log"
		fi
		sync
		cat "$WORK_DIR/mcu_fail.img" > /dev/fb0
		sleep 10000
		exit 1
	fi
fi

# remove small version
cd /usr/prog/PROGRAM/control/
DIR_COUNT=`find -maxdepth 1 -type d | wc -l`
echo $DIR_COUNT
if [ ${DIR_COUNT} -gt 2 ];then
	CONTROL_VERSION=`ls -d [0-9]* | sort -V | head -n 1`
	echo "rm " $CONTROL_VERSION
        rm -r /usr/prog/PROGRAM/control/$CONTROL_VERSION
fi

sync		
sleep 3

exit 0
