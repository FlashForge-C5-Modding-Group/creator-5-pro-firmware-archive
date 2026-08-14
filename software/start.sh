#!/bin/sh

cmd_mcu write_firmware /usr/prog/libmcu-bare.bin
cmd_mcu bootup
sleep 2

export PATH=$PATH:/usr/prog/Python-3.8.2/bin
export LD_LIBRARY_PATH=/usr/prog/Python-3.8.2/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/prog/openssl-1.0.2d/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/prog/libffi-3.4.4/lib:$LD_LIBRARY_PATH

#python3 /usr/prog/klipper/klippy/klippy.py /usr/data/config/printer.cfg -l /usr/data/logs/printer.log -a /tmp/uds &

/usr/prog/klipper/checkEboard
/usr/prog/klipper/klipperDaemon start
#/usr/prog/nginx/sbin/nginx -p /usr/prog/nginx -c /usr/prog/nginx/conf/nginx.conf
#/usr/prog/klipper/moonrakerDaemon start
#sh /usr/prog/klipper/klipper_pri.sh
