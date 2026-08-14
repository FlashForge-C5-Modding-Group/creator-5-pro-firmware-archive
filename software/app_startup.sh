#!/bin/sh

WORK_DIR=/usr/prog
MACHINE=Creator5Pro
PID=0029

insmod /usr/prog/modules/soc_mcu.ko enable_jtag_debug=1

#wait for USB
sleep 2

if [ ! -d /usr/prog/etc ];then
        cp -rf /etc /usr/prog/
        sync
fi

mount /usr/prog/etc /etc

for i in 1 2 3 4;
do
  if [ ! -e /dev/sda$i ]; then
     echo "sda$i not exist"
	 if [ ! -e /dev/sda ];then
     	continue
	 else
	 	echo "find /dev/sda. start mount."
  		mount -t vfat -o,codepage=936,iocharset=utf8 /dev/sda /mnt
	 fi
  else
  	mount -t vfat -o,codepage=936,iocharset=utf8 /dev/sda$i /mnt
  fi

  if [ $? -ne 0 ]; then
        echo "mount /dev/sda or /dev/sda$i to /mnt failed"
        continue
  else
  		ls -1t /mnt/Creator5Pro-*.tgz
		if [ $? -eq 0 ];then
			UPDATEFILE=`ls -1t /mnt/Creator5Pro-*.tgz | head -n 1`
			if [ -f $UPDATEFILE ];then
				echo "find update file: ${UPDATEFILE}"
				rm -rf /usr/data/update
				cp -a ${UPDATEFILE} /usr/data/
				if [ $? -ne 0 ];then
					rm -rf /usr/data/Creator5Pro-*.tgz
					sync
					umount /mnt
					break
				fi
				sync
				mkdir -p /usr/data/update
				sync
				SRCFILE="/usr/data/`basename ${UPDATEFILE}`"
				if [ -f ${SRCFILE} ];then
					#cat /usr/prog/start.img > /dev/fb0
					#tar -xvf ${SRCFILE} -C /usr/data/update/
					export PATH=/usr/prog/openssl-1.0.2d/bin:$PATH
					export LD_LIBRARY_PATH=/usr/prog/openssl-1.0.2d/lib:$LD_LIBRARY_PATH
					/usr/prog/bin/unTar ${SRCFILE}
					sync
					if [ ! -f /usr/data/update/runFirmwareExe.sh ];then
						tar -xvf ${SRCFILE} -C /usr/data/update/
					fi
					sync
					rm -rf ${SRCFILE}
					chmod a+x /usr/data/update/runFirmwareExe.sh
					/usr/data/update/runFirmwareExe.sh ${MACHINE} ${PID}
					if [ $? -eq 0 ];then
						umount /mnt
						rm -rf /usr/data/update
						sleep 100000
					fi
					umount /mnt
					rm -rf /usr/data/update
					break
				fi
			fi
		fi

        if [ -f /mnt/runFirmwareExe.sh ]; then
             chmod a+x /mnt/runFirmwareExe.sh
             /mnt/runFirmwareExe.sh ${MACHINE} ${PID}
			 if [ $? -eq 0 ];then
				umount /mnt
				sleep 100000
			 fi
             umount /mnt
             break
        fi
        umount /mnt
  fi
done

CONTROL_DIR=/usr/prog/PROGRAM/control/
#CONTROL_VERSION=`ls -1t ${CONTROL_DIR} | head -n 1`
cd ${CONTROL_DIR}
CONTROL_VERSION=`ls -d [0-9]* | sort -Vr | head -n 1`
CONTRIL_FLAG=${CONTROL_DIR}${CONTROL_VERSION}/Update
#UpdateM
CONTRIL_M=${CONTROL_DIR}${CONTROL_VERSION}/Update    
echo "check update control file"
echo $CONTRIL_FLAG

if [ -f ${CONTRIL_FLAG} ] || [ -f ${CONTRIL_M} ];then
	cd ${CONTROL_DIR}${CONTROL_VERSION}
	./run.sh
	reboot -f
fi

#rm /usr/data/logs/printer.log*
insmod /usr/prog/modules/8821cu.ko power_on=PB07

killall dhcpcd
killall adbserver.sh
sleep 1
killall adbd

TSNAME="Touchscreen"
EVENT=event1
for i in 1 2 3;
do
        file=/sys/class/input/event$i/device/name
        for name in `cat $file`
        do
                echo $name
        done
        if [ "$name" == $TSNAME ];then
               EVENT=event$i
               break;
        fi
done

echo $EVENT

#export TSLIBDIR=/usr/prog/tslib-1.12
#export TSLIB_TSEVENTTYPE=INPUT
#export TSLIB_CONSOLEDEVICE=none
#export TSLIB_FBDEVICE=/dev/fb0
#export TSLIB_TSDEVICE=/dev/input/$EVENT
#export TSLIB_CALIBFILE=/usr/prog/tslib-1.12/etc/pointercal
#export TSLIB_CONFFILE=/usr/prog/tslib-1.12/etc/ts.conf
#export TSLIB_PLUGINDIR=/usr/prog/tslib-1.12/lib/ts
#export QWS_MOUSE_PROTO=TSLIB:/dev/input/$EVENT
#export LD_PRELOAD=/usr/prog/tslib-1.12/lib/libts.so
#export QT_QPA_PLATFORM_PLUGIN_PATH=/usr/prog/qt-4.8.6/plugins
#export QT_QPA_PLATFORM=linuxfb:tty=/dev/fb0:size=480x800:mmsize=115x170:offset=0
#export QWS_DISPLAY=transformed:rot0:LinuxFB:mmWidth115:mmHeight170:0
#export QT_QWS_FONTDIR=/usr/prog/qt-4.8.6/lib/fonts
#export QT_QPA_GENERIC_PLUGINS=tslib
#export LD_LIBRARY_PATH=//usr/prog/qt-4.8.6/lib:$LD_LIBRARY_PATH

export LD_LIBRARY_PATH=/usr/prog/openssl-1.0.2d/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/prog/curl-7.55.1/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/prog/ffmpeg-402/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/prog/x264/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/prog/libffi-3.4.4/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/prog/libsodium/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/prog/opencv-4.2/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/prog/mjpg-streamer:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/prog/nim/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/prog/libzip-1.10.1/lib:$LD_LIBRARY_PATH

/usr/prog/bin/sys_start.sh &
chmod a+x /usr/prog/bin/mencoder

insmod /usr/prog/modules/gt9xx_touch.ko gtp_i2c_bus_num=0 gtp_x_coords_min=0 gtp_y_coords_min=0 gtp_x_coords_max=800 gtp_y_coords_max=480 gtp_x_coords_flip=0 gtp_y_coords_flip=0 gtp_x_y_coords_exchange=0 gtp_version=0x4 gtp_regulator_name=-1 gtp_power_on_gpio=-1 gtp_reset_gpio=PC08 gtp_irq_gpio=PC07 gtp_max_touch_number=2

/usr/prog/PROGRAM/software/firmwareExe &
sleep 5

count=`ps |grep firmwareExe |grep -v "grep" |wc -l`
if [ 0 == $count ];then
	echo "restart"
	cd  /usr/prog/PROGRAM/software/
	softwareDir=$(ls -ld [0-9]* |awk '/^d/ {print $NF}')
	for SoftwareVer in $softwareDir
	do
    		echo $SoftwareVer
	done
	cp /usr/prog/PROGRAM/software/$SoftwareVer/firmwareExe /usr/prog/PROGRAM/software/
	/usr/prog/PROGRAM/software/firmwareExe &
fi

